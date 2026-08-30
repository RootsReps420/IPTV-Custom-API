package com.iptvmonitor.player.player

import android.content.Context
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import androidx.media3.common.AudioAttributes
import androidx.media3.common.C
import androidx.media3.common.Format
import androidx.media3.common.MediaItem
import androidx.media3.common.MimeTypes
import androidx.media3.common.PlaybackException
import androidx.media3.common.PlaybackParameters
import androidx.media3.common.Player
import androidx.media3.common.Tracks
import androidx.media3.common.VideoSize
import androidx.media3.common.util.UnstableApi
import androidx.media3.datasource.DataSource
import androidx.media3.datasource.DefaultDataSource
import androidx.media3.datasource.UdpDataSource
import androidx.media3.datasource.okhttp.OkHttpDataSource
import androidx.media3.exoplayer.DefaultLoadControl
import androidx.media3.exoplayer.DefaultRenderersFactory
import androidx.media3.exoplayer.ExoPlayer
import androidx.media3.exoplayer.hls.HlsMediaSource
import androidx.media3.exoplayer.mediacodec.MediaCodecSelector
import androidx.media3.exoplayer.source.MediaSource
import androidx.media3.exoplayer.source.ProgressiveMediaSource
import androidx.media3.exoplayer.trackselection.DefaultTrackSelector
import androidx.media3.exoplayer.upstream.DefaultLoadErrorHandlingPolicy
import androidx.media3.extractor.DefaultExtractorsFactory
import androidx.media3.extractor.ts.DefaultTsPayloadReaderFactory
import com.iptvmonitor.player.data.HttpClients
import com.iptvmonitor.player.data.STREAM_USER_AGENT

@UnstableApi
class LiveSession(
    context: Context,
    private var config: PlaybackConfig = PlaybackConfig(),
    private val listener: Listener = Listener {},
) {
    fun interface Listener {
        fun onState(state: LiveUiState)
    }

    data class PlaybackConfig(
        val profile: BufferProfile = BufferProfile.MEDIUM,
        val hardwareVideo: Boolean = true,
        val hardwareAudio: Boolean = true,
        val surroundDefault: Boolean = false,
        val passthrough: Boolean = false,
        val tunneled: Boolean = false,
        val userAgent: String = STREAM_USER_AGENT,
        val udpProxy: String = "",
    )

    data class LiveUiState(
        val badge: String = "",
        val buffering: Boolean = false,
        val reconnecting: Boolean = false,
        val gaveUp: Boolean = false,
        val message: String = "",
        val width: Int = 0,
        val height: Int = 0,
        val videoCodec: String = "",
        val audioCodec: String = "",
        val audioChannels: Int = 0,
        val aheadSec: Float = 0f,
        val frameRate: Float = 0f,
    )

    private val appContext = context.applicationContext
    private val main = Handler(Looper.getMainLooper())
    var onVodEnded: (() -> Unit)? = null
    var onPlayerReplaced: (() -> Unit)? = null

    private var trackSelector = DefaultTrackSelector(appContext)
    var player: ExoPlayer = buildPlayer(config)
        private set

    private var currentUrl: String = ""
    private var isLive: Boolean = false
    private var reconnectTries = 0
    private var reconnectPosted = false
    private var bufferingSince = 0L
    private var lastHealthyAt = 0L
    private var startedAt = 0L
    private var released = false
    private var videoWidth = 0
    private var videoHeight = 0
    private var videoCodec = ""
    private var audioCodec = ""
    private var audioChannels = 0
    private var frameRate = 0f
    private var applySeq = 0

    private val tick = object : Runnable {
        override fun run() {
            if (released || !isLive) return
            tickLive()
            main.postDelayed(this, 250)
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
            if (!isLive && playbackState == Player.STATE_ENDED) {
                main.post { onVodEnded?.invoke() }
                publish()
                return
            }
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
            if (isPlaying) lastHealthyAt = now()
            publish()
        }

        override fun onVideoSizeChanged(videoSize: VideoSize) {
            videoWidth = videoSize.width
            videoHeight = videoSize.height
            publish()
        }

        override fun onTracksChanged(tracks: Tracks) {
            var video = ""
            var audio = ""
            var channels = 0
            for (group in tracks.groups) {
                for (i in 0 until group.length) {
                    if (!group.isTrackSelected(i)) continue
                    val format = group.getTrackFormat(i)
                    when (group.type) {
                        C.TRACK_TYPE_VIDEO -> {
                            video = prettyCodec(format)
                            if (format.frameRate > 0f) frameRate = format.frameRate
                        }
                        C.TRACK_TYPE_AUDIO -> {
                            audio = prettyCodec(format)
                            channels = format.channelCount
                        }
                    }
                }
            }
            if (video.isNotBlank()) videoCodec = video
            if (audio.isNotBlank()) audioCodec = audio
            if (channels > 0) audioChannels = channels
            publish()
        }
    }

    init {
        player.addListener(playerListener)
        applyTrackPrefs(config)
    }

    fun play(url: String, live: Boolean) {
        val resolved = resolveUrl(url)
        currentUrl = resolved
        isLive = live
        reconnectTries = 0
        reconnectPosted = false
        bufferingSince = 0L
        lastHealthyAt = 0L
        startedAt = now()
        videoWidth = 0
        videoHeight = 0
        videoCodec = ""
        audioCodec = ""
        audioChannels = 0
        frameRate = 0f
        main.removeCallbacks(tick)
        player.stop()
        player.playWhenReady = true
        player.setMediaSource(mediaSource(resolved, live))
        player.prepare()
        player.play()
        if (live) {
            listener.onState(LiveUiState(badge = "BUFFERING", buffering = true))
            main.post(tick)
        } else {
            player.playbackParameters = PlaybackParameters(1f)
            listener.onState(LiveUiState(badge = ""))
        }
    }

    fun applyConfig(next: PlaybackConfig) {
        val rebuild = next.profile != config.profile ||
            next.hardwareVideo != config.hardwareVideo ||
            next.hardwareAudio != config.hardwareAudio ||
            next.userAgent != config.userAgent ||
            next.udpProxy != config.udpProxy ||
            next.tunneled != config.tunneled ||
            next.passthrough != config.passthrough
        val url = currentUrl
        val live = isLive
        config = next
        if (!rebuild) {
            applyTrackPrefs(next)
            return
        }
        val seq = ++applySeq
        main.post {
            if (released || seq != applySeq) return@post
            replacePlayer()
            if (url.isNotBlank()) play(url, live)
        }
    }

    fun applyProfile(next: BufferProfile) {
        applyConfig(config.copy(profile = next))
    }

    fun applyTrackPrefs(surroundDefault: Boolean, passthrough: Boolean, tunneled: Boolean) {
        applyConfig(
            config.copy(
                surroundDefault = surroundDefault,
                passthrough = passthrough,
                tunneled = tunneled,
            ),
        )
    }

    fun retry() {
        if (currentUrl.isBlank()) return
        reconnectTries = 0
        play(currentUrl, isLive)
    }

    fun userPause(paused: Boolean) {
        if (isLive && paused) return
        player.playWhenReady = !paused
    }

    fun stop() {
        isLive = false
        main.removeCallbacks(tick)
        reconnectPosted = false
        currentUrl = ""
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

    private fun replacePlayer() {
        val old = player
        old.removeListener(playerListener)
        old.stop()
        old.release()
        trackSelector = DefaultTrackSelector(appContext)
        player = buildPlayer(config)
        player.addListener(playerListener)
        applyTrackPrefs(config)
        onPlayerReplaced?.invoke()
    }

    private fun buildPlayer(cfg: PlaybackConfig): ExoPlayer {
        val renderers = DefaultRenderersFactory(appContext)
            .setEnableDecoderFallback(true)
            .setExtensionRendererMode(DefaultRenderersFactory.EXTENSION_RENDERER_MODE_ON)
            .setMediaCodecSelector { mimeType, secure, tunneling ->
                val all = MediaCodecSelector.DEFAULT.getDecoderInfos(mimeType, secure, tunneling)
                val hw = all.filter { !it.softwareOnly }
                val sw = all.filter { it.softwareOnly }
                when {
                    mimeType.startsWith("video") ->
                        if (cfg.hardwareVideo) hw.ifEmpty { all } else sw.ifEmpty { all }
                    mimeType.startsWith("audio") ->
                        if (cfg.hardwareAudio) hw.ifEmpty { all } else sw.ifEmpty { all }
                    else -> all
                }
            }
        return ExoPlayer.Builder(appContext)
            .setRenderersFactory(renderers)
            .setTrackSelector(trackSelector)
            .setLoadControl(loadControlFor(cfg.profile))
            .setHandleAudioBecomingNoisy(true)
            .setWakeMode(C.WAKE_MODE_NETWORK)
            .setAudioAttributes(
                AudioAttributes.Builder()
                    .setUsage(C.USAGE_MEDIA)
                    .setContentType(C.AUDIO_CONTENT_TYPE_MOVIE)
                    .build(),
                true,
            )
            .build()
            .also { it.playWhenReady = true }
    }

    private fun applyTrackPrefs(cfg: PlaybackConfig) {
        val builder = trackSelector.buildUponParameters()
            .setTunnelingEnabled(cfg.tunneled)
        when {
            cfg.passthrough -> {
                builder.setPreferredAudioMimeTypes(
                    MimeTypes.AUDIO_E_AC3,
                    MimeTypes.AUDIO_AC3,
                    MimeTypes.AUDIO_DTS,
                    MimeTypes.AUDIO_TRUEHD,
                    MimeTypes.AUDIO_AAC,
                )
                builder.setMaxAudioChannelCount(Int.MAX_VALUE)
            }
            cfg.surroundDefault -> {
                builder.setPreferredAudioMimeTypes(
                    MimeTypes.AUDIO_E_AC3,
                    MimeTypes.AUDIO_AC3,
                    MimeTypes.AUDIO_DTS,
                    MimeTypes.AUDIO_TRUEHD,
                    MimeTypes.AUDIO_AAC,
                )
                builder.setMaxAudioChannelCount(8)
            }
            else -> {
                builder.setPreferredAudioMimeTypes(MimeTypes.AUDIO_AAC, MimeTypes.AUDIO_MPEG)
                builder.setMaxAudioChannelCount(2)
            }
        }
        trackSelector.parameters = builder.build()
    }

    private fun tickLive() {
        if (released || !isLive || reconnectPosted) return
        player.playWhenReady = true
        if (player.isPlaying && player.playbackState == Player.STATE_READY) {
            lastHealthyAt = now()
            if (now() - startedAt > 30_000L) reconnectTries = 0
        }
        val aheadMs = bufferedAheadMs()
        val stalling = player.playbackState == Player.STATE_BUFFERING &&
            bufferingSince > 0L &&
            now() - bufferingSince >= STALL_MS &&
            aheadMs < 800 &&
            now() - startedAt > 4_000L
        if (stalling) {
            scheduleReconnect()
            return
        }
        publish()
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
            lastHealthyAt = 0L
            bufferingSince = 0L
            player.playbackParameters = PlaybackParameters(1f)
            player.setMediaSource(mediaSource(currentUrl, live = true))
            player.prepare()
            player.playWhenReady = true
            player.play()
        }, RECONNECT_DELAY_MS)
    }

    private fun resolveUrl(url: String): String {
        val trimmed = url.trim()
        val proxy = config.udpProxy.trim()
        if (trimmed.startsWith("udp://", ignoreCase = true) && proxy.isNotBlank()) {
            val rest = trimmed.removePrefix("udp://").removePrefix("UDP://")
            val host = if (proxy.contains("://")) proxy.trimEnd('/') else "http://$proxy"
            return "$host/udp/$rest"
        }
        return trimmed
    }

    private fun mediaSource(url: String, live: Boolean): MediaSource {
        val item = MediaItem.fromUri(url)
        val lower = url.lowercase()
        val okHttp = OkHttpDataSource.Factory(HttpClients.stream)
            .setUserAgent(config.userAgent.ifBlank { STREAM_USER_AGENT })
        val http = DefaultDataSource.Factory(appContext, okHttp)
        val policy = object : DefaultLoadErrorHandlingPolicy() {
            override fun getMinimumLoadableRetryCount(dataType: Int): Int = 2
        }
        return when {
            lower.startsWith("udp://") -> {
                val udp = DefaultDataSource.Factory(appContext, DataSource.Factory { UdpDataSource() })
                ProgressiveMediaSource.Factory(udp, mpegTsExtractors())
                    .setLoadErrorHandlingPolicy(policy)
                    .createMediaSource(item)
            }
            lower.contains(".m3u8") || lower.contains("application/vnd.apple") -> {
                HlsMediaSource.Factory(http)
                    .setAllowChunklessPreparation(true)
                    .setLoadErrorHandlingPolicy(policy)
                    .createMediaSource(item)
            }
            else -> ProgressiveMediaSource.Factory(http, mpegTsExtractors())
                .setLoadErrorHandlingPolicy(policy)
                .createMediaSource(item)
        }
    }

    private fun bufferedAheadMs(): Long {
        val pos = player.currentPosition
        val buf = player.bufferedPosition
        if (pos == C.TIME_UNSET || buf == C.TIME_UNSET) return 0L
        return (buf - pos).coerceAtLeast(0L)
    }

    private fun publish() {
        val ahead = bufferedAheadMs() / 1000f
        if (!isLive) {
            listener.onState(
                LiveUiState(
                    width = videoWidth,
                    height = videoHeight,
                    videoCodec = videoCodec,
                    audioCodec = audioCodec,
                    audioChannels = audioChannels,
                    aheadSec = ahead,
                    frameRate = frameRate,
                ),
            )
            return
        }
        val buffering = player.playbackState == Player.STATE_BUFFERING ||
            (!player.isPlaying && player.playWhenReady && now() - startedAt < 4_000L)
        val badge = when {
            reconnectPosted -> "RECONNECT ${reconnectTries}/$MAX_TRIES"
            buffering -> "BUFFERING"
            else -> "LIVE"
        }
        listener.onState(
            LiveUiState(
                badge = badge,
                buffering = buffering,
                reconnecting = reconnectPosted,
                width = videoWidth,
                height = videoHeight,
                videoCodec = videoCodec,
                audioCodec = audioCodec,
                audioChannels = audioChannels,
                aheadSec = ahead,
                frameRate = frameRate,
            ),
        )
    }

    private fun prettyCodec(format: Format): String {
        val text = listOfNotNull(format.sampleMimeType, format.codecs)
            .joinToString(" ")
            .lowercase()
        return when {
            text.contains("ec-3") || text.contains("eac3") -> "E-AC-3"
            text.contains("ac-3") || text.contains("ac3") -> "AC-3"
            text.contains("truehd") || text.contains("mlp") -> "TrueHD"
            text.contains("dts") -> "DTS"
            text.contains("hevc") || text.contains("h265") || text.contains("hvc1") -> "HEVC"
            text.contains("avc") || text.contains("h264") -> "H.264"
            text.contains("av01") || text.contains("av1") -> "AV1"
            text.contains("vp9") -> "VP9"
            text.contains("mp4a") || text.contains("aac") -> "AAC"
            text.contains("opus") -> "Opus"
            else -> ""
        }
    }

    private fun mpegTsExtractors(): DefaultExtractorsFactory {
        return DefaultExtractorsFactory()
            .setTsExtractorFlags(
                DefaultTsPayloadReaderFactory.FLAG_ALLOW_NON_IDR_KEYFRAMES or
                    DefaultTsPayloadReaderFactory.FLAG_DETECT_ACCESS_UNITS,
            )
    }

    private fun now() = SystemClock.elapsedRealtime()

    companion object {
        private const val STALL_MS = 12_000L
        private const val RECONNECT_DELAY_MS = 900L
        private const val MAX_TRIES = 6

        fun loadControlFor(profile: BufferProfile): DefaultLoadControl {
            val (min, max, play, rebuf) = when (profile) {
                BufferProfile.SMALL -> listOf(1_200, 8_000, 350, 600)
                BufferProfile.MEDIUM -> listOf(2_000, 18_000, 450, 900)
                BufferProfile.LARGE -> listOf(3_500, 32_000, 700, 1_400)
            }
            return DefaultLoadControl.Builder()
                .setBufferDurationsMs(min, max, play, rebuf)
                .setPrioritizeTimeOverSizeThresholds(true)
                .build()
        }
    }
}

private operator fun <T> List<T>.component1() = this[0]
private operator fun <T> List<T>.component2() = this[1]
private operator fun <T> List<T>.component3() = this[2]
private operator fun <T> List<T>.component4() = this[3]
