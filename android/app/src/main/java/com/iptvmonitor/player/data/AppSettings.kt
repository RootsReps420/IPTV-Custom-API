package com.iptvmonitor.player.data

import android.content.Context
import com.iptvmonitor.player.player.BufferProfile

private const val PREF = "portal_settings"
private const val KEY_BUFFER = "buffer_profile"
private const val KEY_LAST = "last_playlist_id"
private const val KEY_LIVE = "live_source_id"
private const val KEY_VOD = "vod_source_id"
private const val KEY_AUTO = "auto_open_last"

class AppSettings(context: Context) {
    private val prefs = context.applicationContext.getSharedPreferences(PREF, Context.MODE_PRIVATE)

    var bufferProfile: BufferProfile
        get() = BufferProfile.fromKey(prefs.getString(KEY_BUFFER, BufferProfile.MEDIUM.key))
        set(value) {
            prefs.edit().putString(KEY_BUFFER, value.key).apply()
        }

    var lastPlaylistId: String?
        get() = prefs.getString(KEY_LAST, null)?.ifBlank { null }
        set(value) {
            prefs.edit().putString(KEY_LAST, value.orEmpty()).apply()
        }

    var liveSourceId: String?
        get() = prefs.getString(KEY_LIVE, null)?.ifBlank { null }
        set(value) {
            prefs.edit().putString(KEY_LIVE, value.orEmpty()).apply()
        }

    var vodSourceId: String?
        get() = prefs.getString(KEY_VOD, null)?.ifBlank { null }
        set(value) {
            prefs.edit().putString(KEY_VOD, value.orEmpty()).apply()
        }

    var autoOpenLast: Boolean
        get() = prefs.getBoolean(KEY_AUTO, true)
        set(value) {
            prefs.edit().putBoolean(KEY_AUTO, value).apply()
        }
}
