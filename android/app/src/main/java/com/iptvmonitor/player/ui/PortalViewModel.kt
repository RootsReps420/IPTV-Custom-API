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
import com.iptvmonitor.player.data.STREAM_USER_AGENT
import com.iptvmonitor.player.data.HttpClients
import com.iptvmonitor.player.data.SeriesShow
import android.os.Build
import android.os.Environment
import com.iptvmonitor.player.data.ByteProgress
import com.iptvmonitor.player.data.XmltvParser
import com.iptvmonitor.player.data.XtreamClient
import com.iptvmonitor.player.player.BufferProfile
import com.iptvmonitor.player.player.LiveSession
import com.iptvmonitor.player.player.RecordService
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json
import java.io.File
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.TimeoutCancellationException
import kotlinx.coroutines.delay
import kotlinx.coroutines.ensureActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeout
import java.io.InterruptedIOException
import android.os.SystemClock

enum class BrowseTab { LIVE, MOVIES, SHOWS, SEARCH }

const val FAVOURITES_ID = "__favourites__"

data class ItemMenu(
    val item: CatalogItem? = null,
    val show: SeriesShow? = null,
    val event: EpgEvent? = null,
)

data class GroupMenu(
    val category: Category,
)

enum class AppScreen { HOME, LIBRARY, SETTINGS }

enum class ShellLane { RAIL, GROUPS, CHANNELS }

data class GuideSync(
    val running: Boolean = false,
    val kind: String = "",
    val label: String = "",
    val detail: String = "",
    val done: Long = 0,
    val total: Long = 0,
    val startedAt: Long = 0,
    val holdFraction: Float = 0f,
) {
    val rawFraction: Float
        get() = if (total > 0L) (done.toFloat() / total.toFloat()).coerceIn(0f, 1f) else 0f

    val etaSeconds: Int?
        get() {
            if (!running || done <= 0L || total <= done) return null
            if (holdFraction > rawFraction + 0.04f) return null
            val elapsed = (System.currentTimeMillis() - startedAt).coerceAtLeast(1L)
            val remain = total - done
            return ((elapsed.toDouble() / done) * remain / 1000.0).toInt().coerceAtLeast(1)
        }

    val fraction: Float
        get() = maxOf(rawFraction, holdFraction)
}

enum class SettingsPage {
    ROOT, GENERAL, PLAYLISTS, PLAYLIST, GROUPS, EPG, EPG_SOURCES,
    APPEARANCE, PLAYBACK, AFR, VOD, REMOTE, PARENTAL, OTHER, ABOUT,
}

data class TextPrompt(
    val title: String,
    val value: String,
    val hint: String,
    val onSave: (String) -> Unit,
)

data class ChoicePrompt(
    val title: String,
    val options: List<Pair<String, String>>,
    val selectedKey: String,
    val onPick: (String) -> Unit,
)

class PortalViewModel(application: Application) : AndroidViewModel(application) {
    private val store = PlaylistStore(application)
    private val settingsStore = AppSettings(application)
    private val repo = CatalogRepository()

    val session = LiveSession(application, LiveSession.PlaybackConfig()) { liveUi = it }

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
    var settingsRev by mutableStateOf(0)
        private set
    var settingsPage by mutableStateOf(SettingsPage.ROOT)
    var settingsPlaylist by mutableStateOf<SavedPlaylist?>(null)
        private set
    var textPrompt by mutableStateOf<TextPrompt?>(null)
        private set
    var choicePrompt by mutableStateOf<ChoicePrompt?>(null)
        private set
    var showPlaylistEditor by mutableStateOf(false)
        private set
    var playlistEditorInitial by mutableStateOf<SavedPlaylist?>(null)
        private set
    var hiddenLiveDraft by mutableStateOf(setOf<String>())
    var hiddenMovieDraft by mutableStateOf(setOf<String>())
    var hiddenShowDraft by mutableStateOf(setOf<String>())
    var epgLoading by mutableStateOf(false)
        private set
    var epgDayOffset by mutableStateOf(0)
    var groupEditor by mutableStateOf<SavedPlaylist?>(null)
    var groupEditorLive by mutableStateOf<List<Category>>(emptyList())
    var groupEditorMovies by mutableStateOf<List<Category>>(emptyList())
    var groupEditorShows by mutableStateOf<List<Category>>(emptyList())
    var groupEditorLoading by mutableStateOf(false)
    var shellLane by mutableStateOf(ShellLane.RAIL)
    var guideSync by mutableStateOf(GuideSync())
        private set
    var playerGen by mutableStateOf(0)
    var recordingTitle by mutableStateOf<String?>(null)
        private set
    var recordingMessage by mutableStateOf<String?>(null)
    var itemMenu by mutableStateOf<ItemMenu?>(null)
    var groupMenu by mutableStateOf<GroupMenu?>(null)
    var inputGated by mutableStateOf(false)
        private set
    var laneFocusGen by mutableStateOf(0)
        private set

    val isTelevision: Boolean
        get() {
            val ui = getApplication<Application>().resources.configuration.uiMode
            return ui and Configuration.UI_MODE_TYPE_MASK == Configuration.UI_MODE_TYPE_TELEVISION
        }

    val blocksBackgroundFocus: Boolean
        get() = screen == AppScreen.SETTINGS ||
            itemMenu != null ||
            groupMenu != null ||
            choicePrompt != null ||
            textPrompt != null ||
            showPlaylistEditor ||
            groupEditor != null

    fun armInputGate(ms: Long = 1500L) {
        inputGated = true
        gateJob?.cancel()
        gateJob = viewModelScope.launch {
            delay(ms)
            inputGated = false
        }
    }

    fun releaseInputGate() {
        gateJob?.cancel()
        gateJob = viewModelScope.launch {
            delay(40)
            inputGated = false
        }
    }

    fun requestLaneFocus() {
        laneFocusGen += 1
    }

    fun activateLane(lane: ShellLane) {
        if (shellLane != lane) shellLane = lane
    }

    fun peekTab(tab: BrowseTab) {
        if (this.tab == tab) return
        this.tab = tab
        seriesDetail = null
        categoryId = null
    }

    fun peekCategory(id: String?) {
        if (categoryId == id) return
        categoryId = id
        seriesDetail = null
    }

    private var gateJob: Job? = null
    private var xmltvJob: Job? = null
    private var channelEpgJob: Job? = null
    private var saveJob: Job? = null
    private var syncJob: Job? = null
    private var epgGen = 0
    private var epgSessionDone = false
    private var epgSessionPlaylistId: String? = null
    private var groupsDirty = false
    private var lastEpgProgressAt = 0L

    init {
        HttpClients.userAgent = settingsStore.userAgent.ifBlank { STREAM_USER_AGENT }
        session.onPlayerReplaced = { playerGen += 1 }
        session.onVodEnded = { onVodEnded() }
        session.applyConfig(playbackConfig())
        if (autoOpenLast && playlists.isNotEmpty()) {
            val last = playlists.firstOrNull { it.id == settingsStore.lastPlaylistId } ?: playlists.first()
            openLibrary(last)
        } else {
            maybeAutoSync(fromStart = true)
        }
    }

    override fun onCleared() {
        session.release()
        super.onCleared()
    }

    fun reloadPlaylists() {
        playlists = store.list()
    }

    fun prefs(): AppSettings = settingsStore

    fun setPref(block: (AppSettings) -> Unit) {
        val before = playbackConfig()
        block(settingsStore)
        autoOpenLast = settingsStore.autoOpenLast
        bufferProfile = settingsStore.bufferProfile
        HttpClients.userAgent = settingsStore.userAgent.ifBlank { STREAM_USER_AGENT }
        settingsRev += 1
        val after = playbackConfig()
        if (before != after) {
            session.applyConfig(after)
        }
    }

    fun playbackConfig(): LiveSession.PlaybackConfig {
        return LiveSession.PlaybackConfig(
            profile = bufferProfile,
            hardwareVideo = settingsStore.hardwareVideo,
            hardwareAudio = settingsStore.hardwareAudio,
            surroundDefault = settingsStore.surroundDefault,
            passthrough = settingsStore.audioPassthrough,
            tunneled = settingsStore.tunneledPlayback,
            userAgent = settingsStore.userAgent.ifBlank { STREAM_USER_AGENT },
            udpProxy = settingsStore.udpProxy,
        )
    }

    fun applyPlaybackPrefs() {
        session.applyConfig(playbackConfig())
    }

    fun selectTab(tab: BrowseTab) {
        peekTab(tab)
        shellLane = if (tab == BrowseTab.SEARCH) ShellLane.CHANNELS else ShellLane.GROUPS
        requestLaneFocus()
    }

    fun selectCategory(id: String?) {
        peekCategory(id)
        shellLane = ShellLane.CHANNELS
        requestLaneFocus()
    }

    fun popLane(): Boolean {
        return when (shellLane) {
            ShellLane.CHANNELS -> {
                shellLane = ShellLane.GROUPS
                requestLaneFocus()
                true
            }
            ShellLane.GROUPS -> {
                shellLane = ShellLane.RAIL
                requestLaneFocus()
                true
            }
            ShellLane.RAIL -> false
        }
    }

    fun pushLane(): Boolean {
        return when (shellLane) {
            ShellLane.RAIL -> {
                shellLane = if (tab == BrowseTab.SEARCH) ShellLane.CHANNELS else ShellLane.GROUPS
                requestLaneFocus()
                true
            }
            ShellLane.GROUPS -> {
                shellLane = ShellLane.CHANNELS
                requestLaneFocus()
                true
            }
            ShellLane.CHANNELS -> false
        }
    }

    fun openSettingsPage(page: SettingsPage) {
        armInputGate()
        settingsPage = page
        settingsRev += 1
    }

    fun openPlaylistSettings(playlist: SavedPlaylist) {
        armInputGate()
        settingsPlaylist = playlist
        settingsPage = SettingsPage.PLAYLIST
        settingsRev += 1
    }

    fun popSettings() {
        if (settingsPage == SettingsPage.GROUPS) {
            closeGroupEditor()
        }
        settingsPage = when (settingsPage) {
            SettingsPage.ROOT -> {
                backFromSettings()
                SettingsPage.ROOT
            }
            SettingsPage.GROUPS -> SettingsPage.PLAYLIST
            SettingsPage.PLAYLIST -> SettingsPage.PLAYLISTS
            SettingsPage.AFR, SettingsPage.VOD -> SettingsPage.PLAYBACK
            SettingsPage.EPG_SOURCES -> SettingsPage.EPG
            else -> SettingsPage.ROOT
        }
        settingsRev += 1
    }

    fun startAddPlaylist() {
        armInputGate()
        playlistEditorInitial = null
        showPlaylistEditor = true
    }

    fun startEditPlaylist(playlist: SavedPlaylist) {
        armInputGate()
        playlistEditorInitial = playlist
        showPlaylistEditor = true
    }

    fun closePlaylistEditor() {
        showPlaylistEditor = false
        playlistEditorInitial = null
    }

    fun openTextPrompt(title: String, value: String, hint: String, onSave: (String) -> Unit) {
        armInputGate()
        textPrompt = TextPrompt(title, value, hint, onSave)
    }

    fun closeTextPrompt() {
        textPrompt = null
    }

    fun openChoice(
        title: String,
        options: List<Pair<String, String>>,
        selectedKey: String,
        onPick: (String) -> Unit,
    ) {
        armInputGate()
        choicePrompt = ChoicePrompt(title, options, selectedKey, onPick)
    }

    fun closeChoice() {
        choicePrompt = null
    }

    suspend fun peekM3uEpg(url: String): String {
        val trimmed = url.trim()
        if (!trimmed.startsWith("http", ignoreCase = true)) return ""
        return withContext(Dispatchers.IO) { repo.peekM3uEpg(trimmed) }
    }

    fun formatSyncStamp(ms: Long): String {
        if (ms <= 0L) return "Never"
        return SimpleDateFormat("dd MMM yyyy  HH:mm", Locale.UK).format(Date(ms))
    }

    fun cycleLiveSource() {
        val ids = listOf<String?>(null) + playlists.map { it.id }
        val idx = ids.indexOf(settingsStore.liveSourceId).let { if (it < 0) 0 else it }
        setLiveSourceId(ids[(idx + 1) % ids.size])
        settingsRev += 1
    }

    fun cycleVodSource() {
        val ids = listOf<String?>(null) + playlists.map { it.id }
        val idx = ids.indexOf(settingsStore.vodSourceId).let { if (it < 0) 0 else it }
        setVodSourceId(ids[(idx + 1) % ids.size])
        settingsRev += 1
    }

    fun epgUrlPreview(playlist: SavedPlaylist): String {
        return playlist.epgUrl.ifBlank {
            if (playlist.kind == PlaylistKind.XTREAM) "xmltv.php" else ""
        }
    }

    fun clearEpg() {
        cancelEpg(clear = true)
    }

    fun cancelEpg(clear: Boolean = false) {
        val wasRunning = xmltvJob?.isActive == true || guideSync.running
        epgGen += 1
        xmltvJob?.cancel()
        xmltvJob = null
        repo.cancelEpgDownload()
        epgLoading = false
        loadingLabel = ""
        guideSync = GuideSync()
        if (clear) {
            catalog = catalog.copy(epgByChannel = emptyMap())
            liveEpg = emptyList()
            settingsStore.lastEpgStatus = "EPG cleared"
            val pl = liveSource ?: selectedPlaylist
            if (pl != null) {
                store.upsert(pl.copy(lastEpgCount = 0, lastEpgSyncAt = 0L))
                reloadPlaylists()
                refreshSourceRefs()
            }
            epgSessionDone = false
        } else if (wasRunning) {
            settingsStore.lastEpgStatus = "EPG cancelled"
        }
        settingsRev += 1
        error = null
    }

    fun restartEpg() {
        val live = liveSource ?: selectedPlaylist ?: playlists.firstOrNull()
        if (live == null) {
            settingsStore.lastEpgStatus = "No playlist"
            settingsRev += 1
            return
        }
        cancelEpg(clear = false)
        epgSessionDone = false
        fetchEpgFor(live, vodSource, force = true)
    }

    fun requestEpgUpdate() {
        val live = liveSource ?: selectedPlaylist ?: playlists.firstOrNull()
        if (live == null) {
            settingsStore.lastEpgStatus = "No playlist"
            settingsRev += 1
            return
        }
        epgSessionDone = false
        fetchEpgFor(live, vodSource, force = true)
    }

    fun syncAllPlaylists() {
        val items = playlists.toList()
        syncJob?.cancel()
        syncJob = viewModelScope.launch {
            items.forEach { runSyncPlaylist(it) }
        }
    }

    fun setAllGroupsHidden(hidden: Boolean) {
        if (groupEditorLoading) return
        val live = if (hidden) groupEditorLive.map { it.id }.toSet() else emptySet()
        val movies = if (hidden) groupEditorMovies.map { it.id }.toSet() else emptySet()
        val shows = if (hidden) groupEditorShows.map { it.id }.toSet() else emptySet()
        hiddenLiveDraft = live
        hiddenMovieDraft = movies
        hiddenShowDraft = shows
        val playlist = settingsPlaylist ?: groupEditor ?: return
        saveHiddenGroups(playlist, live.toList(), movies.toList(), shows.toList(), close = false)
    }

    fun applyBufferProfile(profile: BufferProfile) {
        bufferProfile = profile
        settingsStore.bufferProfile = profile
        session.applyConfig(playbackConfig())
        settingsRev += 1
    }

    fun applyAutoOpenLast(value: Boolean) {
        autoOpenLast = value
        settingsStore.autoOpenLast = value
        settingsRev += 1
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
                val discovered = withTimeout(28_000) {
                    withContext(Dispatchers.IO) {
                        repo.probe(playlist)
                    }
                }
                val ready = playlist.copy(epgUrl = playlist.epgUrl.ifBlank { discovered })
                store.upsert(ready)
                reloadPlaylists()
                if (settingsStore.liveSourceId == null && ready.kind == PlaylistKind.M3U) {
                    settingsStore.liveSourceId = ready.id
                }
                if (settingsStore.vodSourceId == null && ready.kind == PlaylistKind.XTREAM) {
                    settingsStore.vodSourceId = ready.id
                }
                loadingLabel = "Syncing playlist…"
                runSyncPlaylist(store.get(ready.id) ?: ready)
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
        shellLane = ShellLane.RAIL
        if (playlist.id != epgSessionPlaylistId) {
            epgSessionDone = false
            epgSessionPlaylistId = playlist.id
        }
        loadCatalog(playlist)
        maybeAutoSync(fromStart = false)
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
                maybeStartEpg(force = false)
            }
        }
    }

    fun syncPlaylist(playlist: SavedPlaylist) {
        syncJob?.cancel()
        syncJob = viewModelScope.launch {
            runSyncPlaylist(playlist)
        }
    }

    private suspend fun runSyncPlaylist(playlist: SavedPlaylist) {
        val started = System.currentTimeMillis()
        loading = true
        loadingLabel = "Syncing playlist…"
        error = null
        guideSync = GuideSync(
            running = true,
            kind = "list",
            label = "Updating channels",
            detail = playlist.name,
            startedAt = started,
        )
        try {
            val streams = withContext(Dispatchers.IO) { repo.loadPlaylist(playlist) }
            val headerEpg = if (playlist.kind == PlaylistKind.M3U) {
                playlist.epgUrl.ifBlank { repo.discoveredM3uEpg(playlist) }
            } else {
                playlist.epgUrl
            }
            store.upsert(
                playlist.copy(
                    epgUrl = playlist.epgUrl.ifBlank { headerEpg },
                    lastPlaylistSyncAt = System.currentTimeMillis(),
                    lastLiveCount = streams.live.size,
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
        } catch (exc: CancellationException) {
            throw exc
        } catch (exc: Exception) {
            error = exc.message ?: "Playlist sync failed"
        } finally {
            loading = false
            loadingLabel = ""
            guideSync = GuideSync()
        }
        if (
            settingsStore.epgUpdateOnPlaylistChange &&
            selectedPlaylist != null &&
            catalog.epgByChannel.isEmpty() &&
            xmltvJob?.isActive != true &&
            !epgSessionDone
        ) {
            val live = liveSource ?: selectedPlaylist ?: return
            maybeStartEpg(force = false)
        }
    }

    fun syncEpg(playlist: SavedPlaylist) {
        fetchEpgFor(playlist, if (vodSource?.id == playlist.id) null else vodSource, force = true)
    }

    fun openGroupEditor(playlist: SavedPlaylist) {
        armInputGate()
        val latest = store.get(playlist.id) ?: playlist
        groupEditor = latest
        settingsPlaylist = latest
        hiddenLiveDraft = latest.hiddenLiveCategories.toSet()
        hiddenMovieDraft = latest.hiddenMovieCategories.toSet()
        hiddenShowDraft = latest.hiddenSeriesCategories.toSet()
        viewModelScope.launch {
            groupEditorLoading = true
            try {
                val loaded = withContext(Dispatchers.IO) { repo.loadPlaylist(latest) }
                val saved = store.get(latest.id) ?: latest
                groupEditor = saved
                settingsPlaylist = saved
                groupEditorLive = loaded.liveCategories
                groupEditorMovies = loaded.movieCategories
                groupEditorShows = loaded.seriesCategories
                hiddenLiveDraft = saved.hiddenLiveCategories.toSet()
                hiddenMovieDraft = saved.hiddenMovieCategories.toSet()
                hiddenShowDraft = saved.hiddenSeriesCategories.toSet()
            } catch (exc: Exception) {
                error = exc.message ?: "Could not load groups"
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
        close: Boolean = true,
    ) {
        val latest = store.get(playlist.id) ?: playlist
        store.upsert(
            latest.copy(
                hiddenLiveCategories = hiddenLive,
                hiddenMovieCategories = hiddenMovies,
                hiddenSeriesCategories = hiddenShows,
            ),
        )
        reloadPlaylists()
        refreshSourceRefs()
        val saved = playlists.firstOrNull { it.id == playlist.id }
        settingsPlaylist = saved ?: settingsPlaylist
        groupEditor = if (close) null else saved ?: groupEditor
        if (categoryId != null && currentCategories().none { it.id == categoryId }) {
            categoryId = null
        }
        groupsDirty = true
        settingsRev += 1
    }

    fun closeGroupEditor() {
        val restart = groupsDirty && (xmltvJob?.isActive == true || guideSync.running)
        groupsDirty = false
        groupEditor = null
        if (restart) {
            restartEpg()
        }
    }

    private fun maybeStartEpg(force: Boolean) {
        val live = liveSource ?: selectedPlaylist ?: return
        if (xmltvJob?.isActive == true && !force) return
        if (!force) {
            if (epgSessionDone) return
            if (!settingsStore.epgUpdateOnStart) return
        }
        fetchEpgFor(live, vodSource, force = force)
    }

    private fun fetchEpgFor(livePl: SavedPlaylist, vodPl: SavedPlaylist?, @Suppress("UNUSED_PARAMETER") force: Boolean) {
        xmltvJob?.cancel()
        repo.cancelEpgDownload()
        val gen = ++epgGen
        val started = System.currentTimeMillis()
        lastEpgProgressAt = 0L
        xmltvJob = viewModelScope.launch {
            epgLoading = true
            error = null
            guideSync = GuideSync(
                running = true,
                kind = "epg",
                label = "Updating EPG",
                detail = "Connecting…",
                startedAt = started,
            )
            settingsStore.lastEpgStatus = "Updating EPG…"
            settingsRev += 1
            try {
                val epg = withContext(Dispatchers.IO) {
                    val extra = listOf(settingsStore.extraEpgUrl)
                    val progress = ByteProgress { read, total, label ->
                        val now = SystemClock.uptimeMillis()
                        if (now - lastEpgProgressAt < 400L && (total <= 0L || read < total)) return@ByteProgress
                        lastEpgProgressAt = now
                        if (gen != epgGen) return@ByteProgress
                        viewModelScope.launch(Dispatchers.Main.immediate) {
                            if (gen != epgGen) return@launch
                            val prev = guideSync
                            val done = maxOf(prev.done, read)
                            val tot = when {
                                total <= 0L -> prev.total
                                prev.total <= 0L -> total
                                else -> maxOf(prev.total, total)
                            }
                            val raw = if (tot > 0L) (done.toFloat() / tot.toFloat()).coerceIn(0f, 1f) else 0f
                            guideSync = prev.copy(
                                running = true,
                                kind = "epg",
                                label = "Updating EPG",
                                detail = label,
                                done = done,
                                total = tot,
                                startedAt = started,
                                holdFraction = maxOf(prev.fraction, raw),
                            )
                        }
                    }
                    val liveMap = repo.loadEpg(
                        livePl,
                        extraUrls = extra,
                        pastDays = settingsStore.epgPastDays,
                        horizonDays = settingsStore.epgHorizonDays,
                        storeDescriptions = settingsStore.storeEpgDescriptions,
                        onProgress = progress,
                    )
                    if (vodPl == null || vodPl.id == livePl.id) {
                        liveMap
                    } else {
                        mergeEpgMaps(
                            liveMap,
                            repo.loadEpg(
                                vodPl,
                                extraUrls = extra,
                                pastDays = settingsStore.epgPastDays,
                                horizonDays = settingsStore.epgHorizonDays,
                                storeDescriptions = settingsStore.storeEpgDescriptions,
                                onProgress = progress,
                            ),
                        )
                    }
                }
                ensureActive()
                if (gen != epgGen) return@launch
                catalog = catalog.copy(epgByChannel = epg)
                val channels = epg.values.distinctBy { System.identityHashCode(it) }.size
                val status = if (channels > 0) {
                    "EPG updated · $channels channels"
                } else {
                    "EPG download finished but no programmes matched"
                }
                settingsStore.lastEpgStatus = status
                store.upsert(
                    livePl.copy(
                        lastEpgSyncAt = System.currentTimeMillis(),
                        lastEpgCount = channels,
                    ),
                )
                if (vodPl != null && vodPl.id != livePl.id) {
                    store.upsert(
                        vodPl.copy(
                            lastEpgSyncAt = System.currentTimeMillis(),
                            lastEpgCount = channels,
                        ),
                    )
                }
                reloadPlaylists()
                refreshSourceRefs()
                playing?.let { target ->
                    catalog.live.firstOrNull { it.id == target.channelId }?.let { refreshLiveEpg(it) }
                }
                epgSessionDone = true
                settingsRev += 1
            } catch (exc: CancellationException) {
                if (gen == epgGen) {
                    settingsStore.lastEpgStatus = "EPG cancelled"
                    settingsRev += 1
                }
                throw exc
            } catch (exc: Exception) {
                if (gen != epgGen) return@launch
                val cancelled = exc is InterruptedIOException ||
                    exc.message?.contains("Canceled", ignoreCase = true) == true ||
                    exc.message?.contains("Socket closed", ignoreCase = true) == true
                settingsStore.lastEpgStatus = if (cancelled) {
                    "EPG cancelled"
                } else {
                    exc.message ?: "EPG sync failed"
                }
                epgSessionDone = true
                settingsRev += 1
            } finally {
                if (gen == epgGen) {
                    epgLoading = false
                    loadingLabel = ""
                    guideSync = GuideSync()
                }
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
        cancelEpg(clear = false)
        session.stop()
        selectedPlaylist = null
        catalog = Catalog()
        playing = null
        cinema = false
        seriesDetail = null
        liveEpg = emptyList()
        screen = AppScreen.HOME
        epgSessionDone = false
        epgSessionPlaylistId = null
        error = null
    }

    fun openHome() {
        closeLibrary()
    }

    fun openSettings() {
        cinema = false
        settingsPage = SettingsPage.ROOT
        armInputGate()
        if (settingsStore.parentalEnabled && settingsStore.parentalPin.isNotBlank()) {
            openTextPrompt("PIN", "", "Enter PIN") { pin ->
                if (pin == settingsStore.parentalPin) {
                    screen = AppScreen.SETTINGS
                    settingsRev += 1
                } else {
                    error = "Wrong PIN"
                }
            }
            return
        }
        screen = AppScreen.SETTINGS
        settingsRev += 1
    }

    fun backFromSettings() {
        closeGroupEditor()
        screen = if (selectedPlaylist != null) AppScreen.LIBRARY else AppScreen.HOME
    }

    fun currentCategories(): List<Category> {
        val hidden = hiddenIdsForTab()
        val all = when (tab) {
            BrowseTab.LIVE, BrowseTab.SEARCH -> catalog.liveCategories
            BrowseTab.MOVIES -> catalog.movieCategories
            BrowseTab.SHOWS -> catalog.seriesCategories
        }.filter { it.id !in hidden }
        val pl = groupOwner()
        val order = when (tab) {
            BrowseTab.LIVE, BrowseTab.SEARCH -> pl?.liveGroupOrder.orEmpty()
            BrowseTab.MOVIES -> pl?.movieGroupOrder.orEmpty()
            BrowseTab.SHOWS -> pl?.showGroupOrder.orEmpty()
        }
        val names = groupNames(pl)
        if (order.isEmpty() && names.isEmpty()) return all
        val byId = all.associateBy { it.id }
        val out = ArrayList<Category>(all.size)
        val seen = HashSet<String>()
        for (id in order) {
            val cat = byId[id] ?: continue
            out += cat.copy(name = names[id] ?: cat.name)
            seen += id
        }
        for (cat in all) {
            if (cat.id in seen) continue
            out += cat.copy(name = names[cat.id] ?: cat.name)
        }
        return out
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
        if (categoryId == FAVOURITES_ID) {
            val favs = favouriteIds(tab)
            return items.filter { item ->
                item.id in favs && item.categoryId !in hidden &&
                    (q.isEmpty() || item.name.lowercase().contains(q))
            }
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
        if (categoryId == FAVOURITES_ID) {
            val favs = favouriteIds(BrowseTab.SHOWS)
            return catalog.series.filter { show ->
                show.id in favs && show.categoryId !in hidden &&
                    (q.isEmpty() || show.name.lowercase().contains(q))
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
        val map = catalog.epgByChannel
        if (map.isEmpty()) return emptyList()
        val keys = listOf(item.tvgId, item.tvgName, item.name, item.id)
        for (raw in keys) {
            val trimmed = raw.trim()
            if (trimmed.isEmpty()) continue
            map[trimmed]?.takeIf { it.isNotEmpty() }?.let { return it }
            map[trimmed.lowercase(Locale.US)]?.takeIf { it.isNotEmpty() }?.let { return it }
            val compact = XmltvParser.epgKey(trimmed)
            if (compact.isNotEmpty()) {
                map[compact]?.takeIf { it.isNotEmpty() }?.let { return it }
            }
        }
        return emptyList()
    }

    fun openItemMenu(item: CatalogItem? = null, show: SeriesShow? = null, event: EpgEvent? = null) {
        armInputGate()
        itemMenu = ItemMenu(item = item, show = show, event = event)
    }

    fun closeItemMenu() {
        itemMenu = null
    }

    fun openGroupMenu(category: Category) {
        armInputGate()
        groupMenu = GroupMenu(category)
    }

    fun closeGroupMenu() {
        groupMenu = null
    }

    fun moveGroup(id: String, delta: Int) {
        val pl = groupOwner() ?: return
        val ids = currentCategories().map { it.id }.toMutableList()
        val index = ids.indexOf(id)
        if (index < 0) return
        val dest = (index + delta).coerceIn(0, ids.lastIndex)
        if (dest == index) return
        val moved = ids.removeAt(index)
        ids.add(dest, moved)
        store.upsert(withGroupOrder(pl, ids))
        reloadPlaylists()
        refreshSourceRefs()
    }

    fun renameGroup(id: String, name: String) {
        val trimmed = name.trim()
        if (trimmed.isEmpty()) return
        val pl = groupOwner() ?: return
        store.upsert(withGroupName(pl, id, trimmed))
        reloadPlaylists()
        refreshSourceRefs()
        closeGroupMenu()
    }

    fun canMoveGroup(id: String, delta: Int): Boolean {
        val ids = currentCategories().map { it.id }
        val index = ids.indexOf(id)
        if (index < 0) return false
        val dest = index + delta
        return dest in ids.indices
    }

    private fun groupOwner(): SavedPlaylist? {
        val id = when (tab) {
            BrowseTab.LIVE, BrowseTab.SEARCH -> liveSource?.id ?: selectedPlaylist?.id
            BrowseTab.MOVIES, BrowseTab.SHOWS -> vodSource?.id ?: selectedPlaylist?.id
        } ?: return null
        return playlists.firstOrNull { it.id == id }
    }

    private fun groupNames(pl: SavedPlaylist?): Map<String, String> {
        return when (tab) {
            BrowseTab.LIVE, BrowseTab.SEARCH -> pl?.liveGroupNames.orEmpty()
            BrowseTab.MOVIES -> pl?.movieGroupNames.orEmpty()
            BrowseTab.SHOWS -> pl?.showGroupNames.orEmpty()
        }
    }

    private fun withGroupOrder(pl: SavedPlaylist, ids: List<String>): SavedPlaylist {
        return when (tab) {
            BrowseTab.LIVE, BrowseTab.SEARCH -> pl.copy(liveGroupOrder = ids)
            BrowseTab.MOVIES -> pl.copy(movieGroupOrder = ids)
            BrowseTab.SHOWS -> pl.copy(showGroupOrder = ids)
        }
    }

    private fun withGroupName(pl: SavedPlaylist, id: String, name: String): SavedPlaylist {
        return when (tab) {
            BrowseTab.LIVE, BrowseTab.SEARCH -> pl.copy(liveGroupNames = pl.liveGroupNames + (id to name))
            BrowseTab.MOVIES -> pl.copy(movieGroupNames = pl.movieGroupNames + (id to name))
            BrowseTab.SHOWS -> pl.copy(showGroupNames = pl.showGroupNames + (id to name))
        }
    }

    fun isFavourite(item: CatalogItem): Boolean {
        return item.id in favouriteIdsForKind(item.kind)
    }

    fun isFavouriteShow(show: SeriesShow): Boolean {
        return show.id in favouriteIds(BrowseTab.SHOWS)
    }

    fun toggleFavourite(item: CatalogItem) {
        val playlist = playlists.firstOrNull { it.id == item.sourcePlaylistId }
            ?: favouritePlaylist()
            ?: return
        val next = when (item.kind) {
            MediaKind.LIVE -> playlist.copy(favouriteLiveIds = playlist.favouriteLiveIds.toggleId(item.id))
            MediaKind.MOVIE -> playlist.copy(favouriteMovieIds = playlist.favouriteMovieIds.toggleId(item.id))
            MediaKind.SERIES -> playlist.copy(favouriteShowIds = playlist.favouriteShowIds.toggleId(item.id))
        }
        store.upsert(next)
        reloadPlaylists()
        refreshSourceRefs()
        closeItemMenu()
    }

    fun toggleFavouriteShow(show: SeriesShow) {
        val playlist = playlists.firstOrNull { it.id == show.sourcePlaylistId }
            ?: favouritePlaylist()
            ?: return
        store.upsert(playlist.copy(favouriteShowIds = playlist.favouriteShowIds.toggleId(show.id)))
        reloadPlaylists()
        refreshSourceRefs()
        closeItemMenu()
    }

    private fun favouritePlaylist(): SavedPlaylist? {
        val id = when (tab) {
            BrowseTab.LIVE, BrowseTab.SEARCH -> liveSource?.id ?: selectedPlaylist?.id
            BrowseTab.MOVIES, BrowseTab.SHOWS -> vodSource?.id ?: selectedPlaylist?.id
        } ?: return null
        return playlists.firstOrNull { it.id == id }
    }

    private fun favouriteIds(tab: BrowseTab): Set<String> {
        val pl = favouritePlaylist() ?: return emptySet()
        return when (tab) {
            BrowseTab.LIVE -> pl.favouriteLiveIds
            BrowseTab.MOVIES -> pl.favouriteMovieIds
            BrowseTab.SHOWS -> pl.favouriteShowIds
            BrowseTab.SEARCH -> pl.favouriteLiveIds + pl.favouriteMovieIds + pl.favouriteShowIds
        }.toSet()
    }

    private fun favouriteIdsForKind(kind: MediaKind): Set<String> {
        val pl = favouritePlaylist() ?: return emptySet()
        return when (kind) {
            MediaKind.LIVE -> pl.favouriteLiveIds
            MediaKind.MOVIE -> pl.favouriteMovieIds
            MediaKind.SERIES -> pl.favouriteShowIds
        }.toSet()
    }

    private fun List<String>.toggleId(id: String): List<String> {
        return if (id in this) filter { it != id } else this + id
    }

    fun playItem(item: CatalogItem, event: EpgEvent? = null) {
        seriesDetail = null
        val same = playing?.channelId == item.id && playing?.url == item.playbackUrl && !cinema
        if (same && event == null) {
            cinema = true
            return
        }
        if (event != null && !event.isNow && event.endMs < System.currentTimeMillis()) {
            playCatchup(item, event)
            return
        }
        playing = PlayTarget(
            title = item.name,
            url = item.playbackUrl,
            live = item.kind == MediaKind.LIVE,
            logo = item.logo,
            channelId = item.id,
            tvgId = item.tvgId,
        )
        cinema = !isTelevision || settingsStore.okOpensCinema
        if (item.kind == MediaKind.LIVE) refreshLiveEpg(item)
    }

    private fun playCatchup(item: CatalogItem, event: EpgEvent) {
        val playlist = playlists.firstOrNull { it.id == item.sourcePlaylistId }
            ?: liveSource
            ?: selectedPlaylist
        val url = if (playlist?.kind == PlaylistKind.XTREAM) {
            XtreamClient(playlist.server, playlist.username, playlist.password)
                .timeshiftUrl(item.id, event.startMs, event.endMs)
        } else {
            item.playbackUrl
        }
        playing = PlayTarget(
            title = "${item.name} · ${event.title}",
            url = url,
            live = false,
            logo = item.logo,
            channelId = item.id,
            tvgId = item.tvgId,
        )
        cinema = !isTelevision || settingsStore.okOpensCinema
        liveEpg = epgFor(item)
    }

    fun playEpisode(show: SeriesShow, episode: Episode) {
        playing = PlayTarget(
            title = "${show.name} · ${episode.title}",
            url = episode.playbackUrl,
            live = false,
            logo = episode.logo.ifBlank { show.logo },
            showId = show.id,
            episodeId = episode.id,
        )
        cinema = !isTelevision || settingsStore.okOpensCinema
    }

    private fun onVodEnded() {
        if (!settingsStore.autoplayNextEpisode) return
        val show = seriesDetail ?: return
        val currentId = playing?.episodeId ?: return
        val idx = episodes.indexOfFirst { it.id == currentId }
        val next = episodes.getOrNull(idx + 1) ?: return
        playEpisode(show, next)
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
        channelEpgJob?.cancel()
        val fromXml = epgFor(item)
        if (fromXml.isNotEmpty()) {
            liveEpg = fromXml
            return
        }
        val playlist = playlists.firstOrNull { it.id == item.sourcePlaylistId }
            ?: liveSource
            ?: selectedPlaylist
            ?: return
        channelEpgJob = viewModelScope.launch {
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

    private fun mergeEpgMaps(
        a: Map<String, List<EpgEvent>>,
        b: Map<String, List<EpgEvent>>,
    ): Map<String, List<EpgEvent>> {
        if (a.isEmpty()) return b
        if (b.isEmpty()) return a
        val out = a.mapValues { it.value.toMutableList() }.toMutableMap()
        b.forEach { (key, events) ->
            out.getOrPut(key) { mutableListOf() }.addAll(events)
        }
        return out.mapValues { (_, events) ->
            events.sortedBy { it.startMs }.distinctBy { it.startMs to it.title }
        }
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

    private fun maybeAutoSync(fromStart: Boolean) {
        viewModelScope.launch {
            if (fromStart && settingsStore.playlistUpdateOnStart) {
                playlists.toList().forEach { pl ->
                    val interval = (if (pl.updateIntervalHours > 0) pl.updateIntervalHours else settingsStore.playlistUpdateHours)
                        .coerceAtLeast(1) * 3_600_000L
                    val age = System.currentTimeMillis() - pl.lastPlaylistSyncAt
                    if (pl.lastPlaylistSyncAt == 0L || age > interval) {
                        runSyncPlaylist(pl)
                    }
                }
            }
        }
    }

    fun startRecording(item: CatalogItem, event: EpgEvent? = null) {
        val ctx = getApplication<Application>()
        if (recordingTitle != null) {
            RecordService.stop(ctx)
            recordingTitle = null
            recordingMessage = "Recording stopped"
            return
        }
        val duration = if (event != null && event.endMs > System.currentTimeMillis()) {
            event.endMs - System.currentTimeMillis()
        } else {
            0L
        }
        val title = if (event != null) "${item.name} · ${event.title}" else item.name
        RecordService.start(ctx, item.playbackUrl, title, duration)
        recordingTitle = title
        recordingMessage = "Recording to Movies/ROOTSIPTV"
    }

    fun stopRecording() {
        RecordService.stop(getApplication())
        recordingTitle = null
    }

    fun onRecordingFinished(message: String?) {
        recordingTitle = null
        recordingMessage = message
    }

    fun exportBackup(): String {
        val ctx = getApplication<Application>()
        val raw = Json { encodeDefaults = true; prettyPrint = true }.encodeToString(playlists)
        val name = "ROOTSIPTV-backup-${SimpleDateFormat("yyyyMMdd-HHmm", Locale.US).format(Date())}.json"
        val dir = if (Build.VERSION.SDK_INT >= 19) {
            ctx.getExternalFilesDir(Environment.DIRECTORY_DOCUMENTS) ?: ctx.filesDir
        } else {
            ctx.filesDir
        }
        val file = File(dir, name)
        file.writeText(raw)
        return file.absolutePath
    }
}

data class PlayTarget(
    val title: String,
    val url: String,
    val live: Boolean,
    val logo: String = "",
    val channelId: String = "",
    val tvgId: String = "",
    val showId: String = "",
    val episodeId: String = "",
)
