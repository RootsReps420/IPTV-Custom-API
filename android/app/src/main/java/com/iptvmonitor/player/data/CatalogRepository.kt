package com.iptvmonitor.player.data

import okhttp3.Request

class CatalogRepository {
    fun load(playlist: SavedPlaylist): Catalog {
        return when (playlist.kind) {
            PlaylistKind.XTREAM -> loadXtream(playlist)
            PlaylistKind.M3U -> loadM3u(playlist)
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
            XtreamClient(playlist.server, playlist.username, playlist.password).shortEpg(streamId)
        }.getOrDefault(emptyList())
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

    private fun loadM3u(playlist: SavedPlaylist): Catalog {
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
        val epg = if (epgUrl.isNotBlank()) loadXmltv(epgUrl) else emptyMap()
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

    private fun loadXmltv(url: String): Map<String, List<EpgEvent>> {
        return runCatching {
            val request = Request.Builder().url(url).get().build()
            HttpClients.shared.newCall(request).execute().use { response ->
                if (!response.isSuccessful) return emptyMap()
                val stream = response.body?.byteStream() ?: return emptyMap()
                XmltvParser.parseNowNext(stream)
            }
        }.getOrDefault(emptyMap())
    }
}
