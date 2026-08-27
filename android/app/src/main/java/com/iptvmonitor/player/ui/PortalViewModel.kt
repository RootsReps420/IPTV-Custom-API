package com.iptvmonitor.player.ui

import android.app.Application
import android.content.res.Configuration
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.iptvmonitor.player.data.Catalog
import com.iptvmonitor.player.data.CatalogItem
import com.iptvmonitor.player.data.CatalogRepository
import com.iptvmonitor.player.data.Category
import com.iptvmonitor.player.data.Episode
import com.iptvmonitor.player.data.EpgEvent
import com.iptvmonitor.player.data.MediaKind
import com.iptvmonitor.player.data.PlaylistKind
import com.iptvmonitor.player.data.PlaylistStore
import com.iptvmonitor.player.data.SavedPlaylist
import com.iptvmonitor.player.data.SeriesShow
import com.iptvmonitor.player.data.XtreamClient
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

enum class BrowseTab { LIVE, MOVIES, SHOWS }

class PortalViewModel(application: Application) : AndroidViewModel(application) {
    private val store = PlaylistStore(application)
    private val repo = CatalogRepository()

    var playlists by mutableStateOf(store.list())
        private set
    var error by mutableStateOf<String?>(null)
    var loading by mutableStateOf(false)
        private set
    var loadingLabel by mutableStateOf("")
        private set

    var selectedPlaylist by mutableStateOf<SavedPlaylist?>(null)
        private set
    var catalog by mutableStateOf(Catalog())
        private set
    var tab by mutableStateOf(BrowseTab.LIVE)
    var categoryId by mutableStateOf<String?>(null)
    var query by mutableStateOf("")

    var playing by mutableStateOf<PlayTarget?>(null)
        private set
    var liveEpg by mutableStateOf<List<EpgEvent>>(emptyList())
        private set

    var seriesDetail by mutableStateOf<SeriesShow?>(null)
    var episodes by mutableStateOf<List<Episode>>(emptyList())
    var episodesLoading by mutableStateOf(false)

    val isTelevision: Boolean
        get() {
            val ui = getApplication<Application>().resources.configuration.uiMode
            return ui and Configuration.UI_MODE_TYPE_MASK == Configuration.UI_MODE_TYPE_TELEVISION
        }

    private var epgJob: Job? = null

    fun reloadPlaylists() {
        playlists = store.list()
    }

    fun savePlaylist(playlist: SavedPlaylist) {
        viewModelScope.launch {
            loading = true
            loadingLabel = "Checking playlist…"
            error = null
            try {
                withContext(Dispatchers.IO) {
                    if (playlist.kind == PlaylistKind.XTREAM) {
                        XtreamClient(
                            playlist.server,
                            playlist.username,
                            playlist.password,
                        ).authenticate()
                    } else {
                        repo.load(playlist.copy(epgUrl = ""))
                    }
                }
                store.upsert(playlist)
                reloadPlaylists()
            } catch (exc: Exception) {
                error = exc.message ?: "Could not load playlist"
            } finally {
                loading = false
                loadingLabel = ""
            }
        }
    }

    fun deletePlaylist(id: String) {
        store.delete(id)
        if (selectedPlaylist?.id == id) {
            selectedPlaylist = null
            catalog = Catalog()
        }
        reloadPlaylists()
    }

    fun openPlaylist(playlist: SavedPlaylist) {
        selectedPlaylist = playlist
        tab = BrowseTab.LIVE
        categoryId = null
        query = ""
        seriesDetail = null
        viewModelScope.launch {
            loading = true
            loadingLabel = "Loading catalogue…"
            error = null
            try {
                catalog = withContext(Dispatchers.IO) { repo.load(playlist) }
                categoryId = null
            } catch (exc: Exception) {
                catalog = Catalog()
                error = exc.message ?: "Catalogue failed"
            } finally {
                loading = false
                loadingLabel = ""
            }
        }
    }

    fun closePlaylist() {
        selectedPlaylist = null
        catalog = Catalog()
        playing = null
        seriesDetail = null
    }

    fun currentCategories(): List<Category> {
        return when (tab) {
            BrowseTab.LIVE -> catalog.liveCategories
            BrowseTab.MOVIES -> catalog.movieCategories
            BrowseTab.SHOWS -> catalog.seriesCategories
        }
    }

    fun visibleItems(): List<CatalogItem> {
        val q = query.trim().lowercase()
        val items = when (tab) {
            BrowseTab.LIVE -> catalog.live
            BrowseTab.MOVIES -> catalog.movies
            BrowseTab.SHOWS -> catalog.seriesFiles
        }
        return items.filter { item ->
            (categoryId == null || item.categoryId == categoryId) &&
                (q.isEmpty() || item.name.lowercase().contains(q))
        }
    }

    fun visibleShows(): List<SeriesShow> {
        val q = query.trim().lowercase()
        return catalog.series.filter { show ->
            (categoryId == null || show.categoryId == categoryId) &&
                (q.isEmpty() || show.name.lowercase().contains(q))
        }
    }

    fun epgFor(item: CatalogItem): List<EpgEvent> {
        val byId = catalog.epgByChannel[item.tvgId].orEmpty()
        val byName = catalog.epgByChannel[item.id].orEmpty()
        return (byId + byName).distinctBy { it.startMs to it.title }
    }

    fun playItem(item: CatalogItem) {
        seriesDetail = null
        playing = PlayTarget(
            title = item.name,
            url = item.playbackUrl,
            live = item.kind == MediaKind.LIVE,
            logo = item.logo,
            channelId = item.id,
            tvgId = item.tvgId,
        )
        if (item.kind == MediaKind.LIVE) refreshLiveEpg(item)
    }

    fun playEpisode(show: SeriesShow, episode: Episode) {
        playing = PlayTarget(
            title = "${show.name} · ${episode.title}",
            url = episode.playbackUrl,
            live = false,
            logo = episode.logo.ifBlank { show.logo },
        )
    }

    fun stopPlayback() {
        playing = null
        liveEpg = emptyList()
    }

    fun openSeries(show: SeriesShow) {
        val playlist = selectedPlaylist ?: return
        seriesDetail = show
        episodes = emptyList()
        viewModelScope.launch {
            episodesLoading = true
            try {
                episodes = withContext(Dispatchers.IO) { repo.seriesEpisodes(playlist, show.id) }
            } catch (exc: Exception) {
                error = exc.message ?: "Could not load episodes"
            } finally {
                episodesLoading = false
            }
        }
    }

    private fun refreshLiveEpg(item: CatalogItem) {
        epgJob?.cancel()
        val fromXml = epgFor(item)
        if (fromXml.isNotEmpty()) {
            liveEpg = fromXml
            return
        }
        val playlist = selectedPlaylist ?: return
        epgJob = viewModelScope.launch {
            liveEpg = withContext(Dispatchers.IO) { repo.liveEpg(playlist, item.id) }
        }
    }
}

data class PlayTarget(
    val title: String,
    val url: String,
    val live: Boolean,
    val logo: String = "",
    val channelId: String = "",
    val tvgId: String = "",
)
