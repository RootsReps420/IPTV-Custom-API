package com.iptvmonitor.player.player

/**
 * Watch live buffer profiles (watch.js BUFFER_PROFILES).
 *
 * targetSec is the cushion we try to hold after play has started. If it
 * thins, playback eases to 0.97× until it recovers. Stash is mpegts.js
 * startup; ExoPlayer maps that to a modest live LoadControl.
 */
enum class BufferProfile(
    val key: String,
    val label: String,
    val targetSec: Float,
    val hint: String,
) {
    SMALL("small", "Small", 3f, "Start immediately. Smaller jitter cushion."),
    MEDIUM("medium", "Medium", 6f, "Start immediately. Default cushion; eases to 0.97× if it thins."),
    LARGE("large", "Large", 10f, "Start immediately. Larger cushion after playback has started."),
    ;

    companion object {
        fun fromKey(raw: String?): BufferProfile {
            val key = raw?.lowercase()?.trim().orEmpty()
            return entries.firstOrNull { it.key == key } ?: MEDIUM
        }
    }
}
