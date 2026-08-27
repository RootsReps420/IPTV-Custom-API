package com.iptvmonitor.player.data

import okhttp3.HttpUrl.Companion.toHttpUrlOrNull
import okhttp3.OkHttpClient
import okhttp3.Request
import okio.Buffer
import org.json.JSONArray
import org.json.JSONObject
import java.net.URLEncoder
import java.nio.charset.StandardCharsets

class XtreamException(message: String) : Exception(message)

class XtreamClient(
    rawServer: String,
    private val username: String,
    private val password: String,
) {
    val base: String = normalizeBase(rawServer)

    fun authenticate() {
        val body = getRaw(null, client = HttpClients.probe, maxBytes = 262_144)
        val trimmed = body.trimStart()
        if (trimmed.startsWith("<")) {
            throw XtreamException("Server did not return Xtream JSON")
        }
        val ok = runCatching {
            val auth = JSONObject(body).optJSONObject("user_info")?.opt("auth")
            auth == 1 || auth == "1" || auth == true || auth == "true"
        }.getOrDefault(
            body.contains("\"auth\":1") ||
                body.contains("\"auth\":\"1\"") ||
                body.contains("\"auth\":true"),
        )
        if (!ok) {
            throw XtreamException("Xtream login failed")
        }
    }

    fun liveCategories(): List<Category> = categories("get_live_categories")

    fun liveStreams(): List<CatalogItem> {
        return arrayAction("get_live_streams").mapNotNull { row ->
            val id = row.optString("stream_id").ifBlank { return@mapNotNull null }
            CatalogItem(
                id = id,
                name = row.optString("name").ifBlank { "Channel $id" },
                categoryId = row.optString("category_id"),
                logo = row.optString("stream_icon"),
                playbackUrl = mediaUrl("live", id, row.optString("container_extension").ifBlank { "ts" }),
                kind = MediaKind.LIVE,
                tvgId = row.optString("epg_channel_id"),
                extension = row.optString("container_extension").ifBlank { "ts" },
            )
        }
    }

    fun vodCategories(): List<Category> = categories("get_vod_categories")

    fun vodStreams(): List<CatalogItem> {
        return arrayAction("get_vod_streams").mapNotNull { row ->
            val id = row.optString("stream_id").ifBlank { return@mapNotNull null }
            val ext = row.optString("container_extension").ifBlank { "mp4" }
            CatalogItem(
                id = id,
                name = row.optString("name").ifBlank { "Movie $id" },
                categoryId = row.optString("category_id"),
                logo = row.optString("stream_icon"),
                playbackUrl = mediaUrl("movie", id, ext),
                kind = MediaKind.MOVIE,
                plot = row.optString("plot"),
                extension = ext,
            )
        }
    }

    fun seriesCategories(): List<Category> = categories("get_series_categories")

    fun seriesShows(): List<SeriesShow> {
        return arrayAction("get_series").mapNotNull { row ->
            val id = row.optString("series_id").ifBlank { row.optString("stream_id") }
            if (id.isBlank()) return@mapNotNull null
            SeriesShow(
                id = id,
                name = row.optString("name").ifBlank { "Series $id" },
                categoryId = row.optString("category_id"),
                logo = row.optString("cover").ifBlank { row.optString("stream_icon") },
                plot = row.optString("plot"),
            )
        }
    }

    fun seriesEpisodes(seriesId: String): List<Episode> {
        val json = getJson("get_series_info", mapOf("series_id" to seriesId))
        val episodes = json.optJSONObject("episodes") ?: return emptyList()
        val out = mutableListOf<Episode>()
        val keys = episodes.keys()
        while (keys.hasNext()) {
            val seasonKey = keys.next()
            val seasonNum = seasonKey.toIntOrNull() ?: 0
            val arr = episodes.optJSONArray(seasonKey) ?: continue
            for (i in 0 until arr.length()) {
                val row = arr.optJSONObject(i) ?: continue
                val id = row.optString("id")
                if (id.isBlank()) continue
                val ext = row.optString("container_extension").ifBlank { "mp4" }
                val epNum = row.optString("episode_num").toIntOrNull()
                    ?: row.optInt("episode", i + 1)
                val info = row.optJSONObject("info")
                out += Episode(
                    id = id,
                    title = row.optString("title").ifBlank { "S${seasonNum}E$epNum" },
                    season = seasonNum,
                    episode = epNum,
                    playbackUrl = mediaUrl("series", id, ext),
                    logo = info?.optString("movie_image").orEmpty(),
                )
            }
        }
        return out.sortedWith(compareBy({ it.season }, { it.episode }))
    }

    fun shortEpg(streamId: String, limit: Int = 8): List<EpgEvent> {
        return listingsEpg("get_short_epg", streamId, limit)
    }

    fun tableEpg(streamId: String): List<EpgEvent> {
        val table = listingsEpg("get_simple_data_table", streamId, limit = 0)
        if (table.isNotEmpty()) return table
        return listingsEpg("get_short_epg", streamId, limit = 24)
    }

    fun xmltvUrl(): String {
        val url = base.toHttpUrlOrNull() ?: throw XtreamException("Invalid server URL")
        return url.newBuilder()
            .addPathSegment("xmltv.php")
            .addQueryParameter("username", username)
            .addQueryParameter("password", password)
            .build()
            .toString()
    }

    private fun listingsEpg(action: String, streamId: String, limit: Int): List<EpgEvent> {
        val extra = mutableMapOf("stream_id" to streamId)
        if (limit > 0) extra["limit"] = limit.toString()
        val json = getJson(action, extra)
        val listings = json.optJSONArray("epg_listings") ?: return emptyList()
        val events = mutableListOf<EpgEvent>()
        for (i in 0 until listings.length()) {
            val row = listings.optJSONObject(i) ?: continue
            val start = parseUnixMs(row.opt("start_timestamp") ?: row.opt("start"))
            val end = parseUnixMs(row.opt("stop_timestamp") ?: row.opt("end") ?: row.opt("stop"))
            val title = decodeMaybeBase64(row.optString("title")).ifBlank { "Programme" }
            if (start <= 0L) continue
            events += EpgEvent(
                title = title,
                startMs = start,
                endMs = if (end > start) end else start + 30 * 60 * 1000,
                channelId = streamId,
            )
        }
        return events.sortedBy { it.startMs }
    }

    fun mediaUrl(kind: String, id: String, ext: String): String {
        val user = enc(username)
        val pass = enc(password)
        val suffix = ext.trim().removePrefix(".").ifBlank { if (kind == "live") "ts" else "mp4" }
        val folder = when (kind) {
            "live" -> "live"
            "movie" -> "movie"
            else -> "series"
        }
        return "$base/$folder/$user/$pass/$id.$suffix"
    }

    private fun categories(action: String): List<Category> {
        return arrayAction(action).mapNotNull { row ->
            val id = row.optString("category_id").ifBlank { return@mapNotNull null }
            Category(id = id, name = row.optString("category_name").ifBlank { id })
        }
    }

    private fun arrayAction(action: String): List<JSONObject> {
        val body = getRaw(action)
        val arr = try {
            JSONArray(body)
        } catch (_: Exception) {
            val obj = JSONObject(body)
            obj.optJSONArray("data") ?: return emptyList()
        }
        return (0 until arr.length()).mapNotNull { arr.optJSONObject(it) }
    }

    private fun getJson(action: String?, extra: Map<String, String> = emptyMap()): JSONObject {
        return JSONObject(getRaw(action, extra))
    }

    private fun getRaw(
        action: String?,
        extra: Map<String, String> = emptyMap(),
        client: OkHttpClient = HttpClients.shared,
        maxBytes: Long = Long.MAX_VALUE,
    ): String {
        val builder = (base.toHttpUrlOrNull() ?: throw XtreamException("Invalid server URL"))
            .newBuilder()
            .addPathSegment("player_api.php")
            .addQueryParameter("username", username)
            .addQueryParameter("password", password)
        if (!action.isNullOrBlank()) {
            builder.addQueryParameter("action", action)
        }
        extra.forEach { (k, v) -> builder.addQueryParameter(k, v) }
        val request = Request.Builder().url(builder.build()).get().build()
        client.newCall(request).execute().use { response ->
            if (!response.isSuccessful) {
                throw XtreamException("HTTP ${response.code}")
            }
            val body = response.body ?: return "{}"
            if (maxBytes == Long.MAX_VALUE) {
                return body.string().ifBlank { "{}" }
            }
            val buf = Buffer()
            val source = body.source()
            while (buf.size < maxBytes && !source.exhausted()) {
                val want = minOf(8_192L, maxBytes - buf.size)
                if (source.read(buf, want) == -1L) break
            }
            return buf.readUtf8().ifBlank { "{}" }
        }
    }

    companion object {
        fun normalizeBase(raw: String): String {
            var value = raw.trim()
            if (value.isEmpty()) throw XtreamException("Server URL is empty")
            if (!value.contains("://")) value = "http://$value"
            value = value.trimEnd('/')
            while (value.endsWith("/player_api.php")) {
                value = value.removeSuffix("/player_api.php").trimEnd('/')
            }
            return value
        }

        private fun enc(value: String): String =
            URLEncoder.encode(value, StandardCharsets.UTF_8.name()).replace("+", "%20")

        private fun parseUnixMs(raw: Any?): Long {
            if (raw == null) return 0L
            val text = raw.toString().trim()
            if (text.isEmpty()) return 0L
            val num = text.toLongOrNull() ?: return 0L
            return if (num < 100_000_000_000L) num * 1000 else num
        }

        private fun decodeMaybeBase64(value: String): String {
            val trimmed = value.trim()
            if (trimmed.isEmpty()) return ""
            return try {
                val decoded = android.util.Base64.decode(trimmed, android.util.Base64.DEFAULT)
                String(decoded, StandardCharsets.UTF_8).trim().ifBlank { trimmed }
            } catch (_: Exception) {
                trimmed
            }
        }
    }
}
