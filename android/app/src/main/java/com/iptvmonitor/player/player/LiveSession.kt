package com.iptvmonitor.player.player

import android.content.Context
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import androidx.media3.common.C
import androidx.media3.common.MediaItem
import androidx.media3.common.PlaybackException
import androidx.media3.common.PlaybackParameters
import androidx.media3.common.Player
import androidx.media3.common.util.UnstableApi
import androidx.media3.datasource.okhttp.OkHttpDataSource
import androidx.media3.exoplayer.DefaultLoadControl
import androidx.media3.exoplayer.ExoPlayer
import androidx.media3.exoplayer.hls.HlsMediaSource
import androidx.media3.exoplayer.source.MediaSource
import androidx.media3.exoplayer.source.ProgressiveMediaSource
import com.iptvmonitor.player.data.HttpClients
import com.iptvmonitor.player.data.STREAM_USER_AGENT

/**
 * Watch live policy on ExoPlayer (see watch.js).
 *
 * Reconnect on network/EOF/ended, frozen clock (~4s), stall buffering (4.5s).
 * Never pause to wait for buffer. 0.97× when the cushion thins. Max 6 retries,
 * 700ms delay, reset after 30s of healthy play. Small live LoadControl.
 */
@UnstableApi
class LiveSession(
    context: Context,
    private val listener: Listener = Listener {},
) {
    fun interface Listener {
        fun onState(state: LiveUiState)
    }

    data class LiveUiState(
        val badge: String = "",
        val buffering: Boolean = false,
        val reconnecting: Boolean = false,
        val gaveUp: Boolean = false,
        val message: String = "",
    )

    private val appContext = context.applicationContext
    private val main = Handler(Looper.getMainLooper())
    private val dataSourceFactory = OkHttpDataSource.Factory(HttpClients.shared)
        .setUserAgent(STREAM_USER_AGENT)

    val player: ExoPlayer = ExoPlayer.Builder(appContext)
        .setLoadControl(liveLoadControl())
        .setHandleAudioBecomingNoisy(true)
        .build()
        .also { it.playWhenReady = true }

    private var currentUrl: String = ""
    private var isLive: Boolean = false
    private var reconnectTries = 0
    private var reconnectPosted = false
    private var lastPosition = C.TIME_UNSET
    private var lastPositionAt = 0L
    private var bufferingSince = 0L
    private var lastHealthyAt = 0L
    private var startedAt = 0L
    private var released = false

    private val tick = object : Runnable {
        override fun run() {
            if (released || !isLive) return
            tickLive()
            main.postDelayed(this, 200)
        }
    }

    private val playerListener = object : Player.Listener {
        override fun onPlayerError(error: PlaybackException) {
            if (!isLive) {
                listener.onState(
                    LiveUiState(badge = "ERROR", message = error.localizedMessage.orEmpty()),
                )
                return
            }
            scheduleReconnect()
        }

        override fun onPlaybackStateChanged(playbackState: Int) {
            if (!isLive) {
                publish()
                return
            }
            if (playbackState == Player.STATE_ENDED) {
                scheduleReconnect()
            }
            if (playbackState == Player.STATE_BUFFERING) {
                if (bufferingSince == 0L) bufferingSince = now()
            } else {
                bufferingSince = 0L
            }
            publish()
        }

        override fun onIsPlayingChanged(isPlaying: Boolean) {
            if (isPlaying) {
                lastPositionAt = now()
                lastPosition = player.currentPosition
            }
            publish()
        }
    }

    init {
        player.addListener(playerListener)
    }

    fun play(url: String, live: Boolean) {
        currentUrl = url
        isLive = live
        reconnectTries = 0
        reconnectPosted = false
        lastPosition = C.TIME_UNSET
        lastPositionAt = now()
        bufferingSince = 0L
        lastHealthyAt = 0L
        startedAt = now()
        player.playWhenReady = true
        player.setMediaSource(mediaSource(url, live))
        player.prepare()
        player.play()
        main.removeCallbacks(tick)
        if (live) {
            listener.onState(LiveUiState(badge = "BUFFERING", buffering = true))
            main.post(tick)
        } else {
            player.playbackParameters = PlaybackParameters(1f)
            listener.onState(LiveUiState(badge = ""))
        }
    }

    fun userPause(paused: Boolean) {
        if (isLive && paused) {
            // Live: do not pause the HTTP pipe the way Watch avoids video.pause() on stall.
            return
        }
        player.playWhenReady = !paused
    }

    fun stop() {
        isLive = false
        main.removeCallbacks(tick)
        main.removeCallbacksAndMessages(null)
        reconnectPosted = false
        player.stop()
        player.clearMediaItems()
        listener.onState(LiveUiState())
    }

    fun release() {
        released = true
        stop()
        player.removeListener(playerListener)
        player.release()
    }

    private fun tickLive() {
        if (released || !isLive) return
        if (reconnectPosted) return

        if (player.playWhenReady && player.isPlaying &&
            player.playbackState == Player.STATE_READY
        ) {
            val healthyFor = now() - lastHealthyAt
            if (lastHealthyAt == 0L) lastHealthyAt = now()
            if (now() - startedAt > 30_000L || healthyFor > 30_000L) {
                reconnectTries = 0
            }
        }

        val aheadMs = bufferedAheadMs()
        pace(aheadMs)

        if (player.playbackState == Player.STATE_BUFFERING &&
            !player.playWhenReady
        ) {
            player.playWhenReady = true
        }

        if (bufferingSince > 0L && now() - bufferingSince >= STALL_MS && aheadMs < 1_500) {
            if (now() - startedAt > 2_500L) {
                scheduleReconnect()
                return
            }
        }

        val pos = player.currentPosition
        if (player.playWhenReady && player.playbackState != Player.STATE_IDLE) {
            if (lastPosition == C.TIME_UNSET || kotlin.math.abs(pos - lastPosition) > 50) {
                lastPosition = pos
                lastPositionAt = now()
            } else if (now() - lastPositionAt >= FROZEN_MS) {
                if (aheadMs > 1_500 && !player.playWhenReady) {
                    lastPositionAt = now()
                } else if (now() - startedAt > 2_000L) {
                    lastPositionAt = now()
                    scheduleReconnect()
                    return
                }
            }
        }
        publish()
    }

    private fun pace(aheadMs: Long) {
        if (!player.playWhenReady || player.playbackState != Player.STATE_READY) return
        val ahead = aheadMs / 1000f
        val low = 1.8f
        val recover = 4.0f
        val rate = player.playbackParameters.speed
        when {
            ahead > 0.2f && ahead < low -> {
                if (kotlin.math.abs(rate - 0.97f) > 0.001f) {
                    player.playbackParameters = PlaybackParameters(0.97f)
                }
            }
            ahead >= recover && kotlin.math.abs(rate - 1f) > 0.001f -> {
                player.playbackParameters = PlaybackParameters(1f)
            }
        }
    }

    private fun scheduleReconnect() {
        if (!isLive || reconnectPosted || released) return
        if (reconnectTries >= MAX_TRIES) {
            listener.onState(
                LiveUiState(
                    badge = "DROPPED",
                    gaveUp = true,
                    message = "Live stream dropped. Open the channel again.",
                ),
            )
            return
        }
        reconnectTries += 1
        reconnectPosted = true
        listener.onState(
            LiveUiState(
                badge = "RECONNECT ${reconnectTries}/$MAX_TRIES",
                reconnecting = true,
                buffering = true,
            ),
        )
        main.postDelayed({
            reconnectPosted = false
            if (released || !isLive || currentUrl.isBlank()) return@postDelayed
            startedAt = now()
            lastPosition = C.TIME_UNSET
            lastPositionAt = now()
            bufferingSince = 0L
            player.playbackParameters = PlaybackParameters(1f)
            player.setMediaSource(mediaSource(currentUrl, live = true))
            player.prepare()
            player.playWhenReady = true
            player.play()
        }, RECONNECT_DELAY_MS)
    }

    private fun mediaSource(url: String, live: Boolean): MediaSource {
        val item = MediaItem.fromUri(url)
        val lower = url.lowercase()
        return if (lower.contains(".m3u8") || lower.contains("application/vnd.apple")) {
            HlsMediaSource.Factory(dataSourceFactory)
                .setAllowChunklessPreparation(true)
                .createMediaSource(item)
        } else {
            ProgressiveMediaSource.Factory(dataSourceFactory).createMediaSource(item)
        }
    }

    private fun bufferedAheadMs(): Long {
        val pos = player.currentPosition
        val buf = player.bufferedPosition
        if (pos == C.TIME_UNSET || buf == C.TIME_UNSET) return 0L
        return (buf - pos).coerceAtLeast(0L)
    }

    private fun publish() {
        if (!isLive) {
            listener.onState(LiveUiState())
            return
        }
        val buffering = player.playbackState == Player.STATE_BUFFERING ||
            (!player.isPlaying && player.playWhenReady && now() - startedAt < 4_000L)
        val badge = when {
            reconnectPosted -> "RECONNECT"
            buffering -> "BUFFERING"
            else -> "LIVE"
        }
        listener.onState(
            LiveUiState(
                badge = badge,
                buffering = buffering,
                reconnecting = reconnectPosted,
            ),
        )
    }

    private fun now() = SystemClock.elapsedRealtime()

    companion object {
        private const val FROZEN_MS = 4_000L
        private const val STALL_MS = 4_500L
        private const val RECONNECT_DELAY_MS = 700L
        private const val MAX_TRIES = 6

        fun liveLoadControl(): DefaultLoadControl {
            return DefaultLoadControl.Builder()
                .setBufferDurationsMs(
                    /* minBufferMs */ 1_500,
                    /* maxBufferMs */ 8_000,
                    /* bufferForPlaybackMs */ 400,
                    /* bufferForPlaybackAfterRebufferMs */ 800,
                )
                .setPrioritizeTimeOverSizeThresholds(true)
                .build()
        }
    }
}
