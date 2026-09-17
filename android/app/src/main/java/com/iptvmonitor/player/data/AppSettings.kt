package com.iptvmonitor.player.data

import android.content.Context
import com.iptvmonitor.player.player.BufferProfile

private const val PREF = "portal_settings"

class AppSettings(context: Context) {
    private val prefs = context.applicationContext.getSharedPreferences(PREF, Context.MODE_PRIVATE)

    var bufferProfile: BufferProfile
        get() = BufferProfile.fromKey(prefs.getString("buffer_profile", BufferProfile.MEDIUM.key))
        set(value) {
            prefs.edit().putString("buffer_profile", value.key).apply()
        }

    var lastPlaylistId: String?
        get() = prefs.getString("last_playlist_id", null)?.ifBlank { null }
        set(value) {
            prefs.edit().putString("last_playlist_id", value.orEmpty()).apply()
        }

    var liveSourceId: String?
        get() = prefs.getString("live_source_id", null)?.ifBlank { null }
        set(value) {
            prefs.edit().putString("live_source_id", value.orEmpty()).apply()
        }

    var vodSourceId: String?
        get() = prefs.getString("vod_source_id", null)?.ifBlank { null }
        set(value) {
            prefs.edit().putString("vod_source_id", value.orEmpty()).apply()
        }

    var autoOpenLast: Boolean
        get() = prefs.getBoolean("auto_open_last", true)
        set(value) {
            prefs.edit().putBoolean("auto_open_last", value).apply()
        }

    var autoStartBoot: Boolean by bool("auto_start_boot", false)
    var autoStartWake: Boolean by bool("auto_start_wake", false)
    var confirmExit: Boolean by bool("confirm_exit", false)
    var okOpensCinema: Boolean by bool("ok_opens_cinema", false)

    var userAgent: String
        get() = prefs.getString("user_agent", "") ?: ""
        set(value) {
            prefs.edit().putString("user_agent", value).apply()
            HttpClients.userAgent = value.ifBlank { STREAM_USER_AGENT }
        }

    var extraEpgUrl: String
        get() = prefs.getString("extra_epg_url", "") ?: ""
        set(value) {
            prefs.edit().putString("extra_epg_url", value.trim()).apply()
        }

    var epgPastDays: Int by int("epg_past_days", 1)
    var epgHorizonDays: Int by int("epg_horizon_days", 7)
    var epgUpdateHours: Int by int("epg_update_hours", 4)
    var storeEpgDescriptions: Boolean by bool("store_epg_desc", true)
    var epgUpdateOnStart: Boolean by bool("epg_update_on_start", true)
    var epgUpdateOnPlaylistChange: Boolean by bool("epg_update_on_change", true)
    var lastEpgStatus: String
        get() = prefs.getString("last_epg_status", "") ?: ""
        set(value) {
            prefs.edit().putString("last_epg_status", value).apply()
        }

    var playlistUpdateHours: Int by int("playlist_update_hours", 4)
    var playlistUpdateOnStart: Boolean by bool("playlist_update_on_start", true)

    var hardwareVideo: Boolean by bool("hw_video", true)
    var hardwareAudio: Boolean by bool("hw_audio", true)
    var afrEnabled: Boolean by bool("afr_enabled", false)
    var afrForTv: Boolean by bool("afr_tv", false)
    var afrForVod: Boolean by bool("afr_vod", false)
    var afrSwitchRefresh: Boolean by bool("afr_refresh", true)
    var afrOnly5060: Boolean by bool("afr_5060", false)
    var afrSwitchResolution: Boolean by bool("afr_res", false)
    var afrDelaySec: Int by int("afr_delay", 0)
    var surroundDefault: Boolean by bool("surround_default", false)
    var audioPassthrough: Boolean by bool("audio_passthrough", false)
    var tunneledPlayback: Boolean by bool("tunneled", false)
    var autoplayNextEpisode: Boolean by bool("autoplay_next", true)

    var showSyncBar: Boolean by bool("show_sync_bar", true)
    var udpProxy: String
        get() = prefs.getString("udp_proxy", "") ?: ""
        set(value) {
            prefs.edit().putString("udp_proxy", value.trim()).apply()
        }

    var parentalEnabled: Boolean by bool("parental_on", false)
    var parentalPin: String
        get() = prefs.getString("parental_pin", "") ?: ""
        set(value) {
            prefs.edit().putString("parental_pin", value.filter { it.isDigit() }.take(8)).apply()
        }

    private fun bool(key: String, default: Boolean) = BooleanPref(prefs, key, default)
    private fun int(key: String, default: Int) = IntPref(prefs, key, default)
}

private class BooleanPref(
    private val prefs: android.content.SharedPreferences,
    private val key: String,
    private val default: Boolean,
) {
    operator fun getValue(thisRef: Any?, property: kotlin.reflect.KProperty<*>): Boolean =
        prefs.getBoolean(key, default)

    operator fun setValue(thisRef: Any?, property: kotlin.reflect.KProperty<*>, value: Boolean) {
        prefs.edit().putBoolean(key, value).commit()
    }
}

private class IntPref(
    private val prefs: android.content.SharedPreferences,
    private val key: String,
    private val default: Int,
) {
    operator fun getValue(thisRef: Any?, property: kotlin.reflect.KProperty<*>): Int =
        prefs.getInt(key, default)

    operator fun setValue(thisRef: Any?, property: kotlin.reflect.KProperty<*>, value: Int) {
        prefs.edit().putInt(key, value).commit()
    }
}
