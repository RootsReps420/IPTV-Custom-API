package com.iptvmonitor.player.ui

import android.app.Activity
import android.view.WindowManager
import androidx.compose.foundation.background
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
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalView
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.iptvmonitor.player.data.Category
import java.util.Locale

@Composable
fun WatchShell(viewModel: PortalViewModel, showPlayer: Boolean) {
    val view = LocalView.current
    DisposableEffect(viewModel.playing != null) {
        val window = (view.context as? Activity)?.window
        if (viewModel.playing != null) {
            window?.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        }
        onDispose { window?.clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON) }
    }
    WatchBackdrop {
    BoxWithConstraints(Modifier.fillMaxSize()) {
        val wide = maxWidth >= 840.dp || viewModel.isTelevision
        if (wide) {
            Row(Modifier.fillMaxSize()) {
                WatchRail(viewModel, Modifier.width(210.dp).fillMaxHeight(), compact = false)
                CategoryPane(viewModel, Modifier.width(248.dp).fillMaxHeight())
                ChannelPane(viewModel, Modifier.weight(1.15f).fillMaxHeight())
                PreviewPane(viewModel, showPlayer, Modifier.weight(0.92f).fillMaxHeight())
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
                    Text(viewModel.loadingLabel, color = WatchPalette.Muted, modifier = Modifier.padding(top = 12.dp))
                }
            }
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
        Row(
            modifier.background(WatchPalette.Rail).padding(8.dp),
            horizontalArrangement = Arrangement.spacedBy(8.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            tabs.forEach { (tab, label) ->
                RailBtn(label, viewModel.tab == tab, fill = false) {
                    viewModel.tab = tab
                    viewModel.seriesDetail = null
                }
            }
            Spacer(Modifier.weight(1f))
            RailBtn("Playlists", selected = false, fill = false) { viewModel.openHome() }
            RailBtn("Settings", selected = false, fill = false) { viewModel.openSettings() }
        }
        return
    }
    Column(
        modifier.background(WatchPalette.Rail).padding(12.dp),
        verticalArrangement = Arrangement.spacedBy(4.dp),
    ) {
        Text(
            "RootsIPTV",
            color = WatchPalette.Up,
            style = MaterialTheme.typography.headlineSmall,
            modifier = Modifier.padding(start = 6.dp, bottom = 8.dp),
        )
        tabs.forEach { (tab, label) ->
            RailBtn(label, viewModel.tab == tab) {
                viewModel.tab = tab
                viewModel.categoryId = viewModel.currentCategories().firstOrNull()?.id
                viewModel.seriesDetail = null
            }
        }
        Spacer(Modifier.height(8.dp))
        Text(
            viewModel.libraryCaption(),
            color = WatchPalette.Muted,
            fontSize = 10.sp,
            modifier = Modifier.padding(horizontal = 10.dp),
        )
        Text(
            buildString {
                append(viewModel.catalog.live.size)
                append(" live")
                if (viewModel.epgLoading) append(" · EPG…")
                else if (viewModel.catalog.epgByChannel.isNotEmpty()) {
                    append(" · ")
                    append(viewModel.epgHorizonDays())
                    append("d EPG")
                }
            },
            color = WatchPalette.Text,
            fontSize = 12.sp,
            modifier = Modifier.padding(horizontal = 10.dp, vertical = 4.dp),
        )
        RailBtn("Playlists", selected = false) { viewModel.openHome() }
        RailBtn("Sync list", selected = false) {
            viewModel.selectedPlaylist?.let { viewModel.syncPlaylist(it) }
        }
        RailBtn("Sync EPG", selected = false) {
            (viewModel.liveSource ?: viewModel.selectedPlaylist)?.let { viewModel.syncEpg(it) }
        }
        RailBtn("Settings", selected = false) { viewModel.openSettings() }
        viewModel.error?.let {
            Text(it, color = WatchPalette.Down, fontSize = 11.sp, modifier = Modifier.padding(10.dp))
        }
    }
}

@Composable
fun RailBtn(label: String, selected: Boolean, fill: Boolean = true, onClick: () -> Unit) {
    WatchHotBox(
        selected = selected,
        onClick = onClick,
        modifier = if (fill) Modifier.fillMaxWidth() else Modifier,
        chrome = WatchChrome.Rail,
    ) { hot ->
        Text(
            label.uppercase(),
            color = if (hot) WatchPalette.Up else WatchPalette.Muted,
            fontSize = if (fill) 16.sp else 13.sp,
            letterSpacing = 1.sp,
            fontWeight = if (hot) FontWeight.Bold else FontWeight.Medium,
        )
    }
}

@Composable
fun CategoryPane(viewModel: PortalViewModel, modifier: Modifier) {
    val cats = viewModel.currentCategories()
    Column(
        modifier.background(WatchPalette.Panel).padding(8.dp),
        verticalArrangement = Arrangement.spacedBy(6.dp),
    ) {
        if (viewModel.tab == BrowseTab.SEARCH) {
            Text("Search", color = WatchPalette.Muted, modifier = Modifier.padding(8.dp))
            return
        }
        LazyColumn(verticalArrangement = Arrangement.spacedBy(6.dp)) {
            item {
                CatRow("All", "ALL", viewModel.categoryId == null) { viewModel.categoryId = null }
            }
            items(cats, key = { it.id }) { cat: Category ->
                CatRow(cat.name, catMark(cat.name), viewModel.categoryId == cat.id) {
                    viewModel.categoryId = cat.id
                    viewModel.seriesDetail = null
                }
            }
        }
    }
}

@Composable
private fun CatRow(name: String, mark: String, selected: Boolean, onClick: () -> Unit) {
    WatchListRow(
        selected = selected,
        onClick = onClick,
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

fun catMark(name: String): String {
    val letters = name.filter { it.isLetterOrDigit() }.uppercase(Locale.US)
    return letters.take(2).ifBlank { "·" }
}
