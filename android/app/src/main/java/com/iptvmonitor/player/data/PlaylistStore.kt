package com.iptvmonitor.player.data

import android.content.Context
import android.content.SharedPreferences
import android.util.Log
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKey
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json

private const val PREF_FILE = "portal_playlists"
private const val KEY = "playlists_json"
private const val TAG = "PlaylistStore"

class PlaylistStore(context: Context) {
    private val json = Json {
        ignoreUnknownKeys = true
        encodeDefaults = true
    }
    private val prefs: SharedPreferences = openPrefs(context.applicationContext)

    fun list(): List<SavedPlaylist> {
        val raw = prefs.getString(KEY, null) ?: return emptyList()
        return runCatching { json.decodeFromString<List<SavedPlaylist>>(raw) }.getOrDefault(emptyList())
    }

    fun get(id: String): SavedPlaylist? = list().firstOrNull { it.id == id }

    fun upsert(playlist: SavedPlaylist) {
        val next = list().filterNot { it.id == playlist.id } + playlist
        prefs.edit().putString(KEY, json.encodeToString(next)).apply()
    }

    fun delete(id: String) {
        val next = list().filterNot { it.id == id }
        prefs.edit().putString(KEY, json.encodeToString(next)).apply()
    }

    private fun openPrefs(context: Context): SharedPreferences {
        return try {
            val master = MasterKey.Builder(context)
                .setKeyScheme(MasterKey.KeyScheme.AES256_GCM)
                .build()
            EncryptedSharedPreferences.create(
                context,
                PREF_FILE,
                master,
                EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
                EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM,
            )
        } catch (exc: Exception) {
            Log.w(TAG, "Encrypted prefs unavailable; using private prefs", exc)
            context.getSharedPreferences(PREF_FILE + "_fallback", Context.MODE_PRIVATE)
        }
    }
}
