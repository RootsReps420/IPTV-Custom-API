package com.iptvmonitor.player.ui

import android.app.Application
import android.content.res.Configuration
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.iptvmonitor.player.data.AppSettings
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
import com.iptvmonitor.player.player.BufferProfile
import com.iptvmonitor.player.player.LiveSession
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.TimeoutCancellationException
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeout

enum class BrowseTab { LIVE, MOVIES, SHOWS, SEARCH }

enum class AppScreen { HOME, LIBRARY, SETTINGS }

class PortalViewModel(application: Application) : AndroidViewModel(application) {
    private val store = PlaylistStore(application)
    private val settingsStore = AppSettings(application)
    private val repo = CatalogRepository()

    val session = LiveSession(application, settingsStore.bufferProfile) { liveUi = it }

    var playlists by mutableStateOf(store.list())
        private set
    var error by mutableStateOf<String?>(null)
    var loading by mutableStateOf(false)
        private set
    var loadingLabel by mutableStateOf("")
        private set

    var screen by mutableStateOf(AppScreen.HOME)
    var cinema by mutableStateOf(false)

    var selectedPlaylist by mutableStateOf<SavedPlaylist?>(null)
        private set
    var liveSource by mutableStateOf<SavedPlaylist?>(null)
        private set
    var vodSource by mutableStateOf<SavedPlaylist?>(null)
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
    var liveUi by mutableStateOf(LiveSession.LiveUiState())
        private set

    var seriesDetail by mutableStateOf<SeriesShow?>(null)
    var episodes by mutableStateOf<List<Episode>>(emptyList())
    var episodesLoading by mutableStateOf(false)

    var bufferProfile by mutableStateOf(settingsStore.bufferProfile)
        private set
    var autoOpenLast by mutableStateOf(settingsStore.autoOpenLast)
        private set
    var epgLoading by mutableStateOf(false)
        private set
    var epgDayOffset by mutableStateOf(0)
    var groupEditor by mutableStateOf<SavedPlaylist?>(null)
    var groupEditorLive by mutableStateOf<List<Category>>(emptyList())
    var groupEditorMovies by mutableStateOf<List<Category>>(emptyList())
    var groupEditorShows by mutableStateOf<List<Category>>(emptyList())
    var groupEditorLoading by mutableStateOf(false)

    val isTelevision: Boolean
        get() {
            val ui = getApplication<Application>().resources.configuration.uiMode
            return ui and Configuration.UI_MODE_TYPE_MASK == Configuration.UI_MODE_TYPE_TELEVISION
        }

    private var epgJob: Job? = null
    private var saveJob: Job? = null

    init {
        session.applyProfile(bufferProfile)
        if (autoOpenLast && playlists.isNotEmpty()) {
            val last = playlists.firstOrNull { it.id == settingsStore.lastPlaylistId } ?: playlists.first()
            openLibrary(last)
        }
    }

    override fun onCleared() {
        session.release()
        super.onCleared()
    }

    fun reloadPlaylists() {
        playlists = store.list()
    }

    fun applyBufferProfile(profile: BufferProfile) {
        bufferProfile = profile
        settingsStore.bufferProfile = profile
        session.applyProfile(profile)
    }

    fun applyAutoOpenLast(value: Boolean) {
        autoOpenLast = value
        settingsStore.autoOpenLast = value
    }

    fun setLiveSourceId(id: String?) {
        settingsStore.liveSourceId = id
        selectedPlaylist?.let { loadCatalog(it) }
    }

    fun setVodSourceId(id: String?) {
        settingsStore.vodSourceId = id
        selectedPlaylist?.let { loadCatalog(it) }
    }

    fun liveSourceId(): String? = settingsStore.liveSourceId
    fun vodSourceId(): String? = settingsStore.vodSourceId

    fun savePlaylist(playlist: SavedPlaylist) {
        saveJob?.cancel()
        saveJob = viewModelScope.launch {
            loading = true
            loadingLabel = "Checking playlist…"
            error = null
            try {
                withTimeout(28_000) {
                    withContext(Dispatchers.IO) {
                        repo.probe(playlist)
                    }
                }
                store.upsert(playlist)
                reloadPlaylists()
                if (settingsStore.liveSourceId == null && playlist.kind == PlaylistKind.M3U) {
                    settingsStore.liveSourceId = playlist.id
                }
                if (settingsStore.vodSourceId == null && playlist.kind == PlaylistKind.XTREAM) {
                    settingsStore.vodSourceId = playlist.id
                }
            } catch (exc: TimeoutCancellationException) {
                error = "Portal did not answer in time. Check the URL and try again."
            } catch (exc: CancellationException) {
                throw exc
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
        if (settingsStore.liveSourceId == id) settingsStore.liveSourceId = null
        if (settingsStore.vodSourceId == id) settingsStore.vodSourceId = null
        if (selectedPlaylist?.id == id) {
            closeLibrary()
        }
        reloadPlaylists()
    }

    fun openLibrary(playlist: SavedPlaylist) {
        selectedPlaylist = playlist
        settingsStore.lastPlaylistId = playlist.id
        session.stop()
        playing = null
        cinema = false
        tab = BrowseTab.LIVE
        categoryId = null
        query = ""
        seriesDetail = null
        screen = AppScreen.LIBRARY
        loadCatalog(playlist)
    }

    fun refreshCatalog() {
        val playlist = selectedPlaylist ?: return
        loadCatalog(playlist)
    }

    private fun loadCatalog(playlist: SavedPlaylist, keepEpg: Boolean = false, fetchEpg: Boolean = true) {
        viewModelScope.launch {
            loading = true
            loadingLabel = "Loading catalogue…"
            error = null
            val previousEpg = if (keepEpg) catalog.epgByChannel else emptyMap()
            try {
                val livePl = playlists.firstOrNull { it.id == settingsStore.liveSourceId } ?: playlist
                val vodPl = playlists.firstOrNull { it.id == settingsStore.vodSourceId } ?: playlist
                liveSource = livePl
                vodSource = vodPl
                catalog = withContext(Dispatchers.IO) {
                    if (livePl.id == vodPl.id) {
                        stamp(repo.loadPlaylist(livePl), livePl.id)
                    } else {
                        mergeCatalogs(
                            stamp(repo.loadPlaylist(livePl), livePl.id),
                            stamp(repo.loadPlaylist(vodPl), vodPl.id),
                        )
                    }.copy(epgByChannel = previousEpg)
                }
                categoryId = null
                epgDayOffset = 0
            } catch (exc: Exception) {
                catalog = Catalog()
                error = exc.message ?: "Catalogue failed"
            } finally {
                loading = false
                loadingLabel = ""
            }
            if (fetchEpg) {
                val livePl = liveSource ?: return@launch
                val vodPl = vodSource
                fetchEpgFor(livePl, vodPl)
            }
        }
    }

    fun syncPlaylist(playlist: SavedPlaylist) {
        viewModelScope.launch {
            loading = true
            loadingLabel = "Syncing playlist…"
            error = null
            try {
                val streams = withContext(Dispatchers.IO) { repo.loadPlaylist(playlist) }
                val headerEpg = if (playlist.kind == PlaylistKind.M3U) {
                    streams.let { playlist.epgUrl.ifBlank { repo.discoveredM3uEpg(playlist) } }
                } else {
                    playlist.epgUrl
                }
                store.upsert(
                    playlist.copy(
                        epgUrl = playlist.epgUrl.ifBlank { headerEpg },
                        lastPlaylistSyncAt = System.currentTimeMillis(),
                    ),
                )
                reloadPlaylists()
                refreshSourceRefs()
                if (usesPlaylist(playlist.id) && selectedPlaylist != null) {
                    val stamped = stamp(streams, playlist.id)
                    catalog = when {
                        liveSource?.id == vodSource?.id ->
                            stamped.copy(epgByChannel = catalog.epgByChannel)
                        playlist.id == liveSource?.id -> catalog.copy(
                            live = stamped.live,
                            liveCategories = stamped.liveCategories,
                        )
                        playlist.id == vodSource?.id -> catalog.copy(
                            movieCategories = stamped.movieCategories,
                            movies = stamped.movies,
                            seriesCategories = stamped.seriesCategories,
                            series = stamped.series,
                            seriesFiles = stamped.seriesFiles,
                        )
                        else -> catalog
                    }
                }
            } catch (exc: Exception) {
                error = exc.message ?: "Playlist sync failed"
            } finally {
                loading = false
                loadingLabel = ""
            }
        }
    }

    fun syncEpg(playlist: SavedPlaylist) {
        viewModelScope.launch {
            epgLoading = true
            loadingLabel = "Syncing EPG…"
            error = null
            try {
                val epg = withContext(Dispatchers.IO) { repo.loadEpg(playlist) }
                store.upsert(playlist.copy(lastEpgSyncAt = System.currentTimeMillis()))
                reloadPlaylists()
                refreshSourceRefs()
                if (usesPlaylist(playlist.id) || selectedPlaylist != null) {
                    catalog = catalog.copy(epgByChannel = catalog.epgByChannel + epg)
                    playing?.let { target ->
                        catalog.live.firstOrNull { it.id == target.channelId }?.let { refreshLiveEpg(it) }
                    }
                }
            } catch (exc: Exception) {
                error = exc.message ?: "EPG sync failed"
            } finally {
                epgLoading = false
                loadingLabel = ""
            }
        }
    }

    fun openGroupEditor(playlist: SavedPlaylist) {
        groupEditor = playlist
        viewModelScope.launch {
            groupEditorLoading = true
            try {
                val loaded = withContext(Dispatchers.IO) { repo.loadPlaylist(playlist) }
                groupEditorLive = loaded.liveCategories
                groupEditorMovies = loaded.movieCategories
                groupEditorShows = loaded.seriesCategories
            } catch (exc: Exception) {
                error = exc.message ?: "Could not load groups"
                groupEditor = null
            } finally {
                groupEditorLoading = false
            }
        }
    }

    fun saveHiddenGroups(
        playlist: SavedPlaylist,
        hiddenLive: List<String>,
        hiddenMovies: List<String>,
        hiddenShows: List<String>,
    ) {
        store.upsert(
            playlist.copy(
                hiddenLiveCategories = hiddenLive,
                hiddenMovieCategories = hiddenMovies,
                hiddenSeriesCategories = hiddenShows,
            ),
        )
        reloadPlaylists()
        refreshSourceRefs()
        groupEditor = null
        if (categoryId != null && currentCategories().none { it.id == categoryId }) {
            categoryId = null
        }
    }

    fun closeGroupEditor() {
        groupEditor = null
    }

    private fun fetchEpgFor(livePl: SavedPlaylist, vodPl: SavedPlaylist?) {
        viewModelScope.launch {
            epgLoading = true
            loadingLabel = "Syncing EPG…"
            try {
                val epg = withContext(Dispatchers.IO) {
                    val liveEpg = repo.loadEpg(livePl)
                    if (vodPl == null || vodPl.id == livePl.id) {
                        liveEpg
                    } else {
                        liveEpg + repo.loadEpg(vodPl)
                    }
                }
                catalog = catalog.copy(epgByChannel = epg)
                store.upsert(livePl.copy(lastEpgSyncAt = System.currentTimeMillis()))
                if (vodPl != null && vodPl.id != livePl.id) {
                    store.upsert(vodPl.copy(lastEpgSyncAt = System.currentTimeMillis()))
                }
                reloadPlaylists()
                refreshSourceRefs()
            } catch (exc: Exception) {
                error = exc.message ?: "EPG sync failed"
            } finally {
                epgLoading = false
                loadingLabel = ""
            }
        }
    }

    private fun usesPlaylist(id: String): Boolean {
        return selectedPlaylist?.id == id || liveSource?.id == id || vodSource?.id == id
    }

    private fun refreshSourceRefs() {
        liveSource = playlists.firstOrNull { it.id == liveSource?.id } ?: liveSource
        vodSource = playlists.firstOrNull { it.id == vodSource?.id } ?: vodSource
        selectedPlaylist = playlists.firstOrNull { it.id == selectedPlaylist?.id } ?: selectedPlaylist
    }

    fun closeLibrary() {
        session.stop()
        selectedPlaylist = null
        catalog = Catalog()
        playing = null
        cinema = false
        seriesDetail = null
        liveEpg = emptyList()
        screen = AppScreen.HOME
    }

    fun openHome() {
        closeLibrary()
    }

    fun openSettings() {
        cinema = false
        screen = AppScreen.SETTINGS
    }

    fun backFromSettings() {
        screen = if (selectedPlaylist != null) AppScreen.LIBRARY else AppScreen.HOME
    }

    fun currentCategories(): List<Category> {
        val hidden = hiddenIdsForTab()
        val all = when (tab) {
            BrowseTab.LIVE, BrowseTab.SEARCH -> catalog.liveCategories
            BrowseTab.MOVIES -> catalog.movieCategories
            BrowseTab.SHOWS -> catalog.seriesCategories
        }
        return all.filter { it.id !in hidden }
    }

    fun visibleItems(): List<CatalogItem> {
        val q = query.trim().lowercase()
        if (tab == BrowseTab.SEARCH) {
            val all = catalog.live + catalog.movies + catalog.seriesFiles
            return all.filter { item ->
                !isHidden(item) && (q.isEmpty() || item.name.lowercase().contains(q))
            }
        }
        val hidden = hiddenIdsForTab()
        val items = when (tab) {
            BrowseTab.LIVE -> catalog.live
            BrowseTab.MOVIES -> catalog.movies
            BrowseTab.SHOWS -> catalog.seriesFiles
            BrowseTab.SEARCH -> emptyList()
        }
        return items.filter { item ->
            item.categoryId !in hidden &&
                (categoryId == null || item.categoryId == categoryId) &&
                (q.isEmpty() || item.name.lowercase().contains(q))
        }
    }

    fun visibleShows(): List<SeriesShow> {
        val q = query.trim().lowercase()
        val hidden = hiddenIds(MediaKind.SERIES)
        if (tab == BrowseTab.SEARCH) {
            return catalog.series.filter { show ->
                show.categoryId !in hidden && (q.isEmpty() || show.name.lowercase().contains(q))
            }
        }
        return catalog.series.filter { show ->
            show.categoryId !in hidden &&
                (categoryId == null || show.categoryId == categoryId) &&
                (q.isEmpty() || show.name.lowercase().contains(q))
        }
    }

    fun epgHorizonDays(): Int {
        val now = startOfLocalDay(System.currentTimeMillis())
        val latest = catalog.epgByChannel.values.flatten().maxOfOrNull { it.endMs } ?: return 1
        val days = ((latest - now) / 86_400_000L).toInt() + 1
        return days.coerceIn(1, 7)
    }

    private fun hiddenIdsForTab(): Set<String> {
        return when (tab) {
            BrowseTab.LIVE, BrowseTab.SEARCH -> hiddenIds(MediaKind.LIVE)
            BrowseTab.MOVIES -> hiddenIds(MediaKind.MOVIE)
            BrowseTab.SHOWS -> hiddenIds(MediaKind.SERIES)
        }
    }

    private fun hiddenIds(kind: MediaKind): Set<String> {
        val liveHidden = liveSource?.hiddenLiveCategories.orEmpty()
        val movieHidden = vodSource?.hiddenMovieCategories.orEmpty()
            .ifEmpty { liveSource?.hiddenMovieCategories.orEmpty() }
        val showHidden = vodSource?.hiddenSeriesCategories.orEmpty()
            .ifEmpty { liveSource?.hiddenSeriesCategories.orEmpty() }
        return when (kind) {
            MediaKind.LIVE -> liveHidden
            MediaKind.MOVIE -> movieHidden
            MediaKind.SERIES -> showHidden
        }.toSet()
    }

    private fun isHidden(item: CatalogItem): Boolean {
        return item.categoryId in hiddenIds(item.kind)
    }

    fun epgFor(item: CatalogItem): List<EpgEvent> {
        val byId = catalog.epgByChannel[item.tvgId].orEmpty()
        val byName = catalog.epgByChannel[item.id].orEmpty()
        val byTitle = catalog.epgByChannel[item.name].orEmpty()
        return (byId + byName + byTitle).distinctBy { it.startMs to it.title }
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
        cinema = !isTelevision
        if (item.kind == MediaKind.LIVE) refreshLiveEpg(item)
    }

    fun playEpisode(show: SeriesShow, episode: Episode) {
        playing = PlayTarget(
            title = "${show.name} · ${episode.title}",
            url = episode.playbackUrl,
            live = false,
            logo = episode.logo.ifBlank { show.logo },
        )
        cinema = !isTelevision
    }

    fun stopPlayback() {
        session.stop()
        playing = null
        cinema = false
        liveEpg = emptyList()
    }

    fun showCinema(on: Boolean) {
        cinema = on
    }

    fun openSeries(show: SeriesShow) {
        val playlist = playlists.firstOrNull { it.id == show.sourcePlaylistId }
            ?: vodSource
            ?: selectedPlaylist
            ?: return
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

    fun libraryCaption(): String {
        val live = liveSource
        val vod = vodSource
        return when {
            live != null && vod != null && live.id != vod.id ->
                "Live · ${live.name}   Movies · ${vod.name}"
            selectedPlaylist != null -> {
                val p = selectedPlaylist!!
                if (p.kind == PlaylistKind.XTREAM) "Xtream · ${p.username}" else "M3U"
            }
            else -> ""
        }
    }

    private fun refreshLiveEpg(item: CatalogItem) {
        epgJob?.cancel()
        val fromXml = epgFor(item)
        if (fromXml.isNotEmpty()) {
            liveEpg = fromXml
            return
        }
        val playlist = playlists.firstOrNull { it.id == item.sourcePlaylistId }
            ?: liveSource
            ?: selectedPlaylist
            ?: return
        epgJob = viewModelScope.launch {
            liveEpg = withContext(Dispatchers.IO) { repo.liveEpg(playlist, item.id) }
        }
    }

    private fun stamp(catalog: Catalog, playlistId: String): Catalog {
        return catalog.copy(
            live = catalog.live.map { it.copy(sourcePlaylistId = playlistId) },
            movies = catalog.movies.map { it.copy(sourcePlaylistId = playlistId) },
            seriesFiles = catalog.seriesFiles.map { it.copy(sourcePlaylistId = playlistId) },
            series = catalog.series.map { it.copy(sourcePlaylistId = playlistId) },
        )
    }

    private fun mergeCatalogs(liveCat: Catalog, vodCat: Catalog): Catalog {
        return Catalog(
            liveCategories = liveCat.liveCategories.ifEmpty { vodCat.liveCategories },
            live = liveCat.live.ifEmpty { vodCat.live },
            movieCategories = vodCat.movieCategories.ifEmpty { liveCat.movieCategories },
            movies = vodCat.movies.ifEmpty { liveCat.movies },
            seriesCategories = vodCat.seriesCategories.ifEmpty { liveCat.seriesCategories },
            series = vodCat.series.ifEmpty { liveCat.series },
            seriesFiles = vodCat.seriesFiles.ifEmpty { liveCat.seriesFiles },
            epgByChannel = liveCat.epgByChannel + vodCat.epgByChannel,
        )
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
