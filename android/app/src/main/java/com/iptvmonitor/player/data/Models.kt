package com.iptvmonitor.player.data

import kotlinx.serialization.Serializable
import java.util.UUID

@Serializable
enum class PlaylistKind {
    XTREAM,
    M3U,
}

enum class MediaKind {
    LIVE,
    MOVIE,
    SERIES,
}

@Serializable
data class SavedPlaylist(
    val id: String = UUID.randomUUID().toString(),
    val name: String,
    val kind: PlaylistKind,
    val server: String = "",
    val username: String = "",
    val password: String = "",
    val m3uUrl: String = "",
    val epgUrl: String = "",
)

data class Category(
    val id: String,
    val name: String,
)

data class CatalogItem(
    val id: String,
    val name: String,
    val categoryId: String,
    val logo: String = "",
    val playbackUrl: String,
    val kind: MediaKind,
    val tvgId: String = "",
    val plot: String = "",
    val extension: String = "ts",
)

data class SeriesShow(
    val id: String,
    val name: String,
    val categoryId: String,
    val logo: String = "",
    val plot: String = "",
)

data class Episode(
    val id: String,
    val title: String,
    val season: Int,
    val episode: Int,
    val playbackUrl: String,
    val logo: String = "",
)

data class EpgEvent(
    val title: String,
    val startMs: Long,
    val endMs: Long,
    val channelId: String = "",
) {
    val isNow: Boolean
        get() {
            val now = System.currentTimeMillis()
            return now in startMs until endMs
        }
}

data class Catalog(
    val liveCategories: List<Category> = emptyList(),
    val live: List<CatalogItem> = emptyList(),
    val movieCategories: List<Category> = emptyList(),
    val movies: List<CatalogItem> = emptyList(),
    val seriesCategories: List<Category> = emptyList(),
    val series: List<SeriesShow> = emptyList(),
    val seriesFiles: List<CatalogItem> = emptyList(),
    val epgByChannel: Map<String, List<EpgEvent>> = emptyMap(),
) {
    val isEmpty: Boolean
        get() = live.isEmpty() && movies.isEmpty() && series.isEmpty() && seriesFiles.isEmpty()
}
