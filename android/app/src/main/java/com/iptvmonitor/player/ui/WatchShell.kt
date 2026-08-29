package com.iptvmonitor.player.ui

import android.app.Activity
import android.view.WindowManager
import androidx.compose.animation.core.animateDpAsState
import androidx.compose.foundation.background
import androidx.compose.foundation.focusGroup
import androidx.compose.foundation.focusable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusProperties
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.focus.onFocusChanged
import androidx.compose.ui.focus.FocusDirection
import androidx.compose.ui.platform.LocalFocusManager
import androidx.compose.ui.platform.LocalView
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.iptvmonitor.player.data.Category
import java.util.Locale
import kotlinx.coroutines.delay

@Composable
fun WatchShell(viewModel: PortalViewModel, showPlayer: Boolean, modifier: Modifier = Modifier) {
    val view = LocalView.current
    DisposableEffect(viewModel.playing != null) {
        val window = (view.context as? Activity)?.window
        if (viewModel.playing != null) {
            window?.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        }
        onDispose { window?.clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON) }
    }
    WatchBackdrop {
        Column(modifier.fillMaxSize()) {
            if (viewModel.prefs().showSyncBar || viewModel.settingsRev >= 0) {
                if (viewModel.prefs().showSyncBar) {
                    SyncStatusBar(viewModel)
                }
            }
            BoxWithConstraints(Modifier.weight(1f).fillMaxWidth()) {
                val wide = maxWidth >= 840.dp || viewModel.isTelevision
                val lane = viewModel.shellLane
                val railReq = remember { FocusRequester() }
                val groupsReq = remember { FocusRequester() }
                val channelsReq = remember { FocusRequester() }
                val focus = LocalFocusManager.current
                LaunchedEffect(viewModel.laneFocusGen) {
                    if (viewModel.laneFocusGen == 0) return@LaunchedEffect
                    delay(60)
                    runCatching {
                        when (viewModel.shellLane) {
                            ShellLane.RAIL -> railReq.requestFocus()
                            ShellLane.GROUPS -> groupsReq.requestFocus()
                            ShellLane.CHANNELS -> channelsReq.requestFocus()
                        }
                        focus.moveFocus(FocusDirection.Down)
                    }
                }
                val railW by animateDpAsState(
                    targetValue = when {
                        !wide -> 0.dp
                        lane == ShellLane.RAIL -> 210.dp
                        else -> 72.dp
                    },
                    label = "rail",
                )
                val catW by animateDpAsState(
                    targetValue = when {
                        !wide -> 0.dp
                        lane == ShellLane.RAIL -> 248.dp
                        lane == ShellLane.GROUPS -> 300.dp
                        else -> 64.dp
                    },
                    label = "cats",
                )
                val previewH by animateDpAsState(
                    targetValue = when {
                        !wide -> 0.dp
                        !showPlayer -> 0.dp
                        lane == ShellLane.CHANNELS && viewModel.tab == BrowseTab.LIVE -> 128.dp
                        lane == ShellLane.CHANNELS -> 148.dp
                        else -> 196.dp
                    },
                    label = "preview",
                )
                if (wide) {
                    Row(Modifier.fillMaxSize()) {
                        WatchRail(
                            viewModel,
                            Modifier
                                .width(railW)
                                .fillMaxHeight()
                                .focusRequester(railReq)
                                .focusable()
                                .focusGroup()
                                .onFocusChanged { if (it.hasFocus) viewModel.activateLane(ShellLane.RAIL) }
                                .laneBack(viewModel, ShellLane.RAIL),
                            compact = lane != ShellLane.RAIL,
                        )
                        CategoryPane(
                            viewModel,
                            Modifier
                                .width(catW)
                                .fillMaxHeight()
                                .focusRequester(groupsReq)
                                .focusable()
                                .focusGroup()
                                .onFocusChanged { if (it.hasFocus) viewModel.activateLane(ShellLane.GROUPS) }
                                .laneBack(viewModel, ShellLane.GROUPS),
                            compact = lane == ShellLane.CHANNELS,
                        )
                        Column(Modifier.weight(1f).fillMaxHeight()) {
                            if (previewH > 0.dp) {
                                PreviewPane(
                                    viewModel,
                                    showPlayer,
                                    Modifier
                                        .fillMaxWidth()
                                        .height(previewH)
                                        .focusProperties { canFocus = false },
                                    banner = true,
                                )
                            }
                            ChannelPane(
                                viewModel,
                                Modifier
                                    .weight(1f)
                                    .fillMaxWidth()
                                    .focusRequester(channelsReq)
                                    .focusable()
                                    .focusGroup()
                                    .onFocusChanged { if (it.hasFocus) viewModel.activateLane(ShellLane.CHANNELS) },
                            )
                        }
                    }
                } else {
                    Column(Modifier.fillMaxSize()) {
                        WatchRail(viewModel, Modifier.fillMaxWidth(), compact = true)
                        ChannelPane(viewModel, Modifier.weight(1f).fillMaxWidth())
                    }
                }
                if (viewModel.loading) {
                    Box(
                        Modifier.fillMaxSize().background(WatchPalette.Bg.copy(alpha = 0.72f)),
                        contentAlignment = Alignment.Center,
                    ) {
                        Column(horizontalAlignment = Alignment.CenterHorizontally) {
                            CircularProgressIndicator(color = WatchPalette.Up)
                            Text(
                                viewModel.loadingLabel,
                                color = WatchPalette.Muted,
                                modifier = Modifier.padding(top = 12.dp),
                            )
                        }
                    }
                }
            }
        }
    }
}

@Composable
fun SyncStatusBar(viewModel: PortalViewModel) {
    val sync = viewModel.guideSync
    val live = viewModel.liveSource ?: viewModel.selectedPlaylist
    val listAge = live?.lastPlaylistSyncAt ?: 0L
    val epgAge = live?.lastEpgSyncAt ?: 0L
    val idle = buildString {
        append(viewModel.catalog.live.size)
        append(" channels")
        val epgCh = viewModel.catalog.epgByChannel.size
        if (epgCh > 0) {
            append(" · ")
            append(epgCh)
            append(" EPG")
        }
        if (listAge > 0L) {
            append(" · list ")
            append(ageLabel(listAge))
        }
        if (epgAge > 0L) {
            append(" · EPG ")
            append(ageLabel(epgAge))
        }
        viewModel.recordingTitle?.let {
            append(" · REC ")
            append(it)
        }
    }
    val line = if (sync.running) {
        val eta = sync.etaSeconds?.let { formatEta(it) }
        listOf(sync.label, sync.detail, eta).filter { !it.isNullOrBlank() }.joinToString(" · ")
    } else {
        viewModel.prefs().lastEpgStatus.ifBlank { idle }
    }
    Column(
        Modifier
            .fillMaxWidth()
            .background(WatchPalette.Rail)
            .padding(horizontal = 16.dp, vertical = 8.dp),
    ) {
        Row(
            Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text(
                if (sync.running) sync.label else "Guide",
                color = WatchPalette.Up,
                fontSize = 12.sp,
                fontWeight = FontWeight.SemiBold,
            )
            Text(
                line,
                color = WatchPalette.Text,
                fontSize = 12.sp,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
                modifier = Modifier.padding(start = 12.dp).weight(1f, fill = false),
            )
            if (sync.running && sync.kind == "epg") {
                Row(
                    horizontalArrangement = Arrangement.spacedBy(8.dp),
                    modifier = Modifier.padding(start = 12.dp),
                ) {
                    GhostBtn("Cancel") { viewModel.cancelEpg() }
                    GhostBtn("Restart") { viewModel.restartEpg() }
                }
            }
        }
        if (sync.running) {
            if (sync.total > 0L) {
                LinearProgressIndicator(
                    progress = { sync.fraction },
                    modifier = Modifier.fillMaxWidth().padding(top = 6.dp).height(3.dp),
                    color = WatchPalette.Up,
                    trackColor = WatchPalette.Line,
                )
            } else {
                LinearProgressIndicator(
                    modifier = Modifier.fillMaxWidth().padding(top = 6.dp).height(3.dp),
                    color = WatchPalette.Up,
                    trackColor = WatchPalette.Line,
                )
            }
        }
    }
}

@Composable
fun WatchRail(viewModel: PortalViewModel, modifier: Modifier, compact: Boolean) {
    val tabs = listOf(
        BrowseTab.LIVE to "TV",
        BrowseTab.MOVIES to "Movies",
        BrowseTab.SHOWS to "Shows",
        BrowseTab.SEARCH to "Search",
    )
    if (compact) {
        Column(
            modifier.background(WatchPalette.Rail).padding(vertical = 10.dp, horizontal = 6.dp),
            verticalArrangement = Arrangement.spacedBy(6.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            tabs.forEach { (tab, label) ->
                RailBtn(label.take(2), viewModel.tab == tab, onFocused = { viewModel.peekTab(tab) }) {
                    viewModel.selectTab(tab)
                }
            }
            Spacer(Modifier.weight(1f))
            RailBtn("SET", selected = false) { viewModel.openSettings() }
        }
        return
    }
    val live = viewModel.liveSource ?: viewModel.selectedPlaylist
    val listAt = live?.lastPlaylistSyncAt ?: 0L
    val epgAt = live?.lastEpgSyncAt ?: 0L
    val channels = if (viewModel.catalog.live.isNotEmpty()) viewModel.catalog.live.size else live?.lastLiveCount ?: 0
    val epgCount = if (viewModel.catalog.epgByChannel.isNotEmpty()) viewModel.catalog.epgByChannel.size else live?.lastEpgCount ?: 0
    Column(
        modifier.background(WatchPalette.Rail).padding(12.dp),
        verticalArrangement = Arrangement.spacedBy(4.dp),
    ) {
        BrandMark(modifier = Modifier.padding(start = 6.dp, bottom = 8.dp), size = 15.sp)
        tabs.forEach { (tab, label) ->
            RailBtn(label, viewModel.tab == tab, onFocused = { viewModel.peekTab(tab) }) {
                viewModel.selectTab(tab)
            }
        }
        Spacer(Modifier.weight(1f))
        RailSyncBlock(
            title = "Last playlist sync",
            stamp = viewModel.formatSyncStamp(listAt),
            count = if (channels > 0) "$channels channels" else "No channels yet",
        )
        RailSyncBlock(
            title = "Last EPG sync",
            stamp = viewModel.formatSyncStamp(epgAt),
            count = when {
                viewModel.guideSync.running && viewModel.guideSync.kind == "epg" ->
                    viewModel.guideSync.detail.ifBlank { "Updating…" }
                epgCount > 0 -> "$epgCount EPG"
                else -> "No EPG yet"
            },
        )
        RailBtn("Settings", selected = false) { viewModel.openSettings() }
    }
}

@Composable
private fun RailSyncBlock(title: String, stamp: String, count: String) {
    Column(
        Modifier
            .fillMaxWidth()
            .padding(horizontal = 10.dp, vertical = 8.dp),
        verticalArrangement = Arrangement.spacedBy(2.dp),
    ) {
        Text(
            title.uppercase(Locale.US),
            color = WatchPalette.Muted,
            fontSize = 10.sp,
            letterSpacing = 1.1.sp,
            fontWeight = FontWeight.SemiBold,
        )
        Text(stamp, color = WatchPalette.Text, fontSize = 13.sp, fontWeight = FontWeight.Medium)
        Text(count, color = WatchPalette.Up, fontSize = 12.sp)
    }
}

@Composable
fun RailBtn(
    label: String,
    selected: Boolean,
    fill: Boolean = true,
    onFocused: (() -> Unit)? = null,
    onClick: () -> Unit,
) {
    WatchHotBox(
        selected = selected,
        onClick = onClick,
        onFocused = onFocused,
        modifier = if (fill) Modifier.fillMaxWidth() else Modifier,
        chrome = WatchChrome.Rail,
    ) { hot ->
        Text(
            label.uppercase(Locale.US),
            color = if (hot) WatchPalette.Up else WatchPalette.Muted,
            fontSize = if (fill) 15.sp else 13.sp,
            letterSpacing = 0.6.sp,
            fontWeight = if (hot) FontWeight.Bold else FontWeight.Medium,
            maxLines = 1,
        )
    }
}

@Composable
fun CategoryPane(viewModel: PortalViewModel, modifier: Modifier, compact: Boolean = false) {
    val cats = viewModel.currentCategories()
    Column(
        modifier.background(WatchPalette.Panel).padding(if (compact) 4.dp else 8.dp),
        verticalArrangement = Arrangement.spacedBy(6.dp),
    ) {
        if (viewModel.tab == BrowseTab.SEARCH) {
            if (!compact) Text("Search", color = WatchPalette.Muted, modifier = Modifier.padding(8.dp))
            return
        }
        LazyColumn(
            modifier = Modifier.fillMaxHeight(),
            verticalArrangement = Arrangement.spacedBy(6.dp),
        ) {
            item {
                CatRow("Favourites", "★", viewModel.categoryId == FAVOURITES_ID, compact, onFocused = {
                    viewModel.peekCategory(FAVOURITES_ID)
                }) {
                    viewModel.selectCategory(FAVOURITES_ID)
                }
            }
            item {
                CatRow("All", "ALL", viewModel.categoryId == null, compact, onFocused = {
                    viewModel.peekCategory(null)
                }) {
                    viewModel.selectCategory(null)
                }
            }
            items(cats, key = { it.id }) { cat: Category ->
                CatRow(
                    cat.name,
                    catMark(cat.name),
                    viewModel.categoryId == cat.id,
                    compact,
                    onFocused = { viewModel.peekCategory(cat.id) },
                    onLongClick = { viewModel.openGroupMenu(cat) },
                ) {
                    viewModel.selectCategory(cat.id)
                }
            }
        }
    }
}

@Composable
private fun CatRow(
    name: String,
    mark: String,
    selected: Boolean,
    compact: Boolean,
    onFocused: (() -> Unit)? = null,
    onLongClick: (() -> Unit)? = null,
    onClick: () -> Unit,
) {
    WatchListRow(
        selected = selected,
        onClick = onClick,
        onFocused = onFocused,
        onLongClick = onLongClick,
        modifier = Modifier.fillMaxWidth(),
        chrome = WatchChrome.Cat,
    ) {
        val hot = watchHot()
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Box(
                Modifier
                    .width(22.dp)
                    .height(22.dp)
                    .background(if (hot) WatchPalette.Hover22 else WatchPalette.Panel2),
                contentAlignment = Alignment.Center,
            ) {
                Text(mark, color = if (hot) WatchPalette.Up else WatchPalette.Text, fontSize = 9.sp)
            }
            if (!compact) {
                Text(
                    name,
                    color = if (hot) WatchPalette.Up else WatchPalette.Muted,
                    fontWeight = if (hot) FontWeight.Bold else FontWeight.Normal,
                    maxLines = 2,
                    overflow = TextOverflow.Ellipsis,
                    fontSize = 14.sp,
                )
            }
        }
    }
}

fun catMark(name: String): String {
    val letters = name.filter { it.isLetterOrDigit() }.uppercase(Locale.US)
    return letters.take(2).ifBlank { "·" }
}

private fun ageLabel(ms: Long): String {
    val min = (System.currentTimeMillis() - ms) / 60_000L
    return when {
        min < 1L -> "just now"
        min < 60L -> "${min}m ago"
        min < 1_440L -> "${min / 60L}h ago"
        else -> "${min / 1_440L}d ago"
    }
}

private fun formatEta(seconds: Int): String {
    val m = seconds / 60
    val s = seconds % 60
    return if (m <= 0) "ETA ${s}s" else "ETA $m:${s.toString().padStart(2, '0')}"
}
