package com.iptvmonitor.player.data

import okhttp3.Request
import java.io.InputStream
import java.util.zip.GZIPInputStream

private const val XMLTV_MAX_BYTES = 80_000_000L

class CatalogRepository {
    fun load(playlist: SavedPlaylist): Catalog {
        val catalog = loadPlaylist(playlist)
        val epg = runCatching { loadEpg(playlist) }.getOrDefault(emptyMap())
        return catalog.copy(epgByChannel = epg)
    }

    fun loadPlaylist(playlist: SavedPlaylist): Catalog {
        return when (playlist.kind) {
            PlaylistKind.XTREAM -> loadXtream(playlist)
            PlaylistKind.M3U -> loadM3u(playlist, withEpg = false)
        }
    }

    fun loadEpg(playlist: SavedPlaylist): Map<String, List<EpgEvent>> {
        return when (playlist.kind) {
            PlaylistKind.M3U -> {
                val epgUrl = playlist.epgUrl.ifBlank { m3uHeaderEpg(playlist.m3uUrl) }
                if (epgUrl.isBlank()) emptyMap() else loadXmltv(epgUrl)
            }
            PlaylistKind.XTREAM -> {
                val url = XtreamClient(playlist.server, playlist.username, playlist.password).xmltvUrl()
                loadXmltv(url)
            }
        }
    }

    fun seriesEpisodes(playlist: SavedPlaylist, seriesId: String): List<Episode> {
        if (playlist.kind != PlaylistKind.XTREAM) return emptyList()
        val client = XtreamClient(playlist.server, playlist.username, playlist.password)
        return client.seriesEpisodes(seriesId)
    }

    fun liveEpg(playlist: SavedPlaylist, streamId: String): List<EpgEvent> {
        if (playlist.kind != PlaylistKind.XTREAM) return emptyList()
        return runCatching {
            XtreamClient(playlist.server, playlist.username, playlist.password).tableEpg(streamId)
        }.getOrDefault(emptyList())
    }

    fun liveCategories(playlist: SavedPlaylist): List<Category> {
        return loadPlaylist(playlist).liveCategories
    }

    fun discoveredM3uEpg(playlist: SavedPlaylist): String {
        if (playlist.kind != PlaylistKind.M3U) return playlist.epgUrl
        return playlist.epgUrl.ifBlank { m3uHeaderEpg(playlist.m3uUrl) }
    }

    private fun loadXtream(playlist: SavedPlaylist): Catalog {
        val client = XtreamClient(playlist.server, playlist.username, playlist.password)
        client.authenticate()
        return Catalog(
            liveCategories = runCatching { client.liveCategories() }.getOrDefault(emptyList()),
            live = runCatching { client.liveStreams() }.getOrDefault(emptyList()),
            movieCategories = runCatching { client.vodCategories() }.getOrDefault(emptyList()),
            movies = runCatching { client.vodStreams() }.getOrDefault(emptyList()),
            seriesCategories = runCatching { client.seriesCategories() }.getOrDefault(emptyList()),
            series = runCatching { client.seriesShows() }.getOrDefault(emptyList()),
        )
    }

    private fun loadM3u(playlist: SavedPlaylist, withEpg: Boolean): Catalog {
        val request = Request.Builder().url(playlist.m3uUrl.trim()).get().build()
        val body = HttpClients.shared.newCall(request).execute().use { response ->
            if (!response.isSuccessful) {
                throw XtreamException("M3U HTTP ${response.code}")
            }
            val bytes = response.body?.bytes() ?: ByteArray(0)
            if (bytes.size > 40_000_000) {
                throw XtreamException("M3U is larger than 40 MB")
            }
            bytes.toString(Charsets.UTF_8)
        }
        val parsed = M3uParser.parse(body)
        val epgUrl = playlist.epgUrl.ifBlank { parsed.epgUrl }
        val epg = if (withEpg && epgUrl.isNotBlank()) loadXmltv(epgUrl) else emptyMap()
        return Catalog(
            liveCategories = parsed.liveCategories,
            live = parsed.live,
            movieCategories = parsed.movieCategories,
            movies = parsed.movies,
            seriesCategories = parsed.seriesCategories,
            series = emptyList(),
            seriesFiles = parsed.series,
            epgByChannel = epg,
        )
    }

    private fun m3uHeaderEpg(m3uUrl: String): String {
        return runCatching {
            val request = Request.Builder().url(m3uUrl.trim()).get().build()
            HttpClients.shared.newCall(request).execute().use { response ->
                if (!response.isSuccessful) return ""
                val text = response.body?.string().orEmpty()
                M3uParser.parse(text.take(8_000)).epgUrl
            }
        }.getOrDefault("")
    }

    private fun loadXmltv(url: String): Map<String, List<EpgEvent>> {
        return runCatching {
            val request = Request.Builder().url(url).get().build()
            HttpClients.epg.newCall(request).execute().use { response ->
                if (!response.isSuccessful) return emptyMap()
                val body = response.body ?: return emptyMap()
                val length = body.contentLength()
                if (length > XMLTV_MAX_BYTES) {
                    throw XtreamException("EPG is larger than 80 MB")
                }
                xmltvStream(url, body.byteStream()).use { stream ->
                    XmltvParser.parse(stream)
                }
            }
        }.getOrDefault(emptyMap())
    }

    private fun xmltvStream(url: String, raw: InputStream): InputStream {
        val lower = url.lowercase()
        return if (lower.endsWith(".gz") || lower.contains(".xml.gz")) {
            GZIPInputStream(raw)
        } else {
            raw
        }
    }
}
