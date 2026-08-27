package com.iptvmonitor.player.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.grid.GridCells
import androidx.compose.foundation.lazy.grid.LazyVerticalGrid
import androidx.compose.foundation.lazy.grid.items
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.media3.ui.AspectRatioFrameLayout
import androidx.media3.ui.PlayerView
import coil.compose.AsyncImage
import com.iptvmonitor.player.data.CatalogItem
import com.iptvmonitor.player.data.EpgEvent
import com.iptvmonitor.player.data.SeriesShow
import com.iptvmonitor.player.player.BufferProfile
import com.iptvmonitor.player.player.LiveSession
import kotlinx.coroutines.delay
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

@Composable
fun ChannelPane(viewModel: PortalViewModel, modifier: Modifier) {
    val fieldColors = OutlinedTextFieldDefaults.colors(
        focusedBorderColor = WatchPalette.Up,
        unfocusedBorderColor = WatchPalette.Line,
        focusedTextColor = WatchPalette.Text,
        unfocusedTextColor = WatchPalette.Text,
        cursorColor = WatchPalette.Up,
        focusedPlaceholderColor = WatchPalette.Muted,
        unfocusedPlaceholderColor = WatchPalette.Muted,
    )
    Column(
        modifier
            .background(WatchPalette.Stage)
            .padding(start = 16.dp, end = 12.dp, top = 12.dp, bottom = 12.dp),
    ) {
        OutlinedTextField(
            value = viewModel.query,
            onValueChange = { viewModel.query = it },
            modifier = Modifier.fillMaxWidth(),
            singleLine = true,
            placeholder = {
                Text(
                    if (viewModel.tab == BrowseTab.SEARCH) {
                        "Search live, movies, shows…"
                    } else {
                        "Filter this group…"
                    },
                )
            },
            colors = fieldColors,
        )
        Spacer(Modifier.height(8.dp))
        val show = viewModel.seriesDetail
        if (show != null) {
            EpisodePane(viewModel, show)
            return
        }
        when (viewModel.tab) {
            BrowseTab.SHOWS -> {
                if (viewModel.catalog.series.isNotEmpty()) {
                    ShowGrid(viewModel, viewModel.visibleShows())
                } else {
                    PosterGrid(viewModel, viewModel.visibleItems())
                }
            }
            BrowseTab.MOVIES -> PosterGrid(viewModel, viewModel.visibleItems())
            BrowseTab.SEARCH -> SearchPane(viewModel)
            BrowseTab.LIVE -> LiveEpgGuide(viewModel, viewModel.visibleItems(), Modifier.fillMaxSize())
        }
    }
}

@Composable
private fun SearchPane(viewModel: PortalViewModel) {
    val shows = viewModel.visibleShows()
    val items = viewModel.visibleItems()
    if (shows.isEmpty() && items.isEmpty()) {
        Text("Nothing matches.", color = WatchPalette.Muted)
        return
    }
    Column(Modifier.fillMaxSize()) {
        if (shows.isNotEmpty()) {
            Text("Shows", color = WatchPalette.Up, modifier = Modifier.padding(bottom = 6.dp))
            ShowGrid(viewModel, shows, Modifier.height(220.dp))
        }
        LiveList(viewModel, items, Modifier.weight(1f))
    }
}

@Composable
private fun LiveList(viewModel: PortalViewModel, items: List<CatalogItem>, modifier: Modifier) {
    if (items.isEmpty()) {
        Text("Nothing in this group.", color = WatchPalette.Muted, modifier = modifier)
        return
    }
    LazyColumn(modifier, verticalArrangement = Arrangement.spacedBy(6.dp)) {
        itemsIndexed(items, key = { _, item -> item.id + item.playbackUrl }) { index, item ->
            val here = viewModel.playing?.channelId == item.id
            val epg = viewModel.epgFor(item).firstOrNull { it.isNow } ?: viewModel.epgFor(item).firstOrNull()
            WatchListRow(selected = here, onClick = { viewModel.playItem(item) }, modifier = Modifier.fillMaxWidth()) {
                val hot = watchHot()
                Row(
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    Text(
                        channelNum(item, index),
                        color = if (hot) WatchPalette.Up else WatchPalette.Muted,
                        fontSize = 11.sp,
                        modifier = Modifier.width(36.dp),
                    )
                    AsyncImage(
                        model = item.logo.ifBlank { null },
                        contentDescription = null,
                        modifier = Modifier.size(36.dp).background(WatchPalette.Bg),
                        contentScale = ContentScale.Fit,
                    )
                    Column(Modifier.weight(1f)) {
                        Text(
                            item.name,
                            color = if (hot) WatchPalette.Up else WatchPalette.Text,
                            fontWeight = if (hot) FontWeight.Bold else FontWeight.Medium,
                            maxLines = 1,
                            overflow = TextOverflow.Ellipsis,
                            fontSize = 15.sp,
                        )
                        Text(
                            epg?.title ?: item.plot.ifBlank { "Live" },
                            color = if (hot) WatchPalette.Up else WatchPalette.Muted,
                            maxLines = 1,
                            overflow = TextOverflow.Ellipsis,
                            fontSize = 11.sp,
                        )
                    }
                }
            }
        }
    }
}

@Composable
private fun PosterGrid(
    viewModel: PortalViewModel,
    items: List<CatalogItem>,
    modifier: Modifier = Modifier.fillMaxSize(),
) {
    LazyVerticalGrid(
        columns = GridCells.Adaptive(if (viewModel.isTelevision) 160.dp else 120.dp),
        contentPadding = PaddingValues(4.dp),
        horizontalArrangement = Arrangement.spacedBy(8.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp),
        modifier = modifier,
    ) {
        items(items, key = { it.id + it.playbackUrl }) { item ->
            WatchListRow(
                selected = viewModel.playing?.channelId == item.id,
                onClick = { viewModel.playItem(item) },
            ) {
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    AsyncImage(
                        model = item.logo.ifBlank { null },
                        contentDescription = item.name,
                        modifier = Modifier.width(42.dp).height(60.dp).background(WatchPalette.Bg),
                        contentScale = ContentScale.Crop,
                    )
                    Text(
                        item.name,
                        color = watchInk(WatchPalette.Text),
                        fontWeight = watchWeight(FontWeight.Medium),
                        maxLines = 3,
                        overflow = TextOverflow.Ellipsis,
                        fontSize = 13.sp,
                    )
                }
            }
        }
    }
}

@Composable
private fun ShowGrid(
    viewModel: PortalViewModel,
    shows: List<SeriesShow>,
    modifier: Modifier = Modifier.fillMaxSize(),
) {
    LazyVerticalGrid(
        columns = GridCells.Adaptive(if (viewModel.isTelevision) 160.dp else 120.dp),
        contentPadding = PaddingValues(4.dp),
        horizontalArrangement = Arrangement.spacedBy(8.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp),
        modifier = modifier,
    ) {
        items(shows, key = { it.id }) { show ->
            WatchListRow(
                selected = viewModel.seriesDetail?.id == show.id,
                onClick = { viewModel.openSeries(show) },
            ) {
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    AsyncImage(
                        model = show.logo.ifBlank { null },
                        contentDescription = show.name,
                        modifier = Modifier.width(42.dp).height(60.dp).background(WatchPalette.Bg),
                        contentScale = ContentScale.Crop,
                    )
                    Text(
                        show.name,
                        color = watchInk(WatchPalette.Text),
                        fontWeight = watchWeight(FontWeight.Medium),
                        maxLines = 3,
                        overflow = TextOverflow.Ellipsis,
                        fontSize = 13.sp,
                    )
                }
            }
        }
    }
}

@Composable
private fun EpisodePane(viewModel: PortalViewModel, show: SeriesShow) {
    Column(Modifier.fillMaxSize()) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            RailBtn("Back", selected = false, fill = false) { viewModel.seriesDetail = null }
            Text(show.name, color = WatchPalette.Text, modifier = Modifier.padding(start = 12.dp))
        }
        Spacer(Modifier.height(8.dp))
        if (viewModel.episodesLoading) {
            CircularProgressIndicator(color = WatchPalette.Up)
        } else if (viewModel.episodes.isEmpty()) {
            Text("No episodes returned.", color = WatchPalette.Muted)
        } else {
            val grouped = viewModel.episodes.groupBy { it.season }
            LazyColumn(verticalArrangement = Arrangement.spacedBy(6.dp)) {
                grouped.forEach { (season, eps) ->
                    item { Text("Season $season", color = WatchPalette.Up, modifier = Modifier.padding(top = 8.dp)) }
                    items(eps, key = { it.id }) { ep ->
                        WatchListRow(
                            selected = false,
                            onClick = { viewModel.playEpisode(show, ep) },
                            modifier = Modifier.fillMaxWidth(),
                        ) {
                            Text(
                                "E${ep.episode}  ${ep.title}",
                                color = watchInk(WatchPalette.Text),
                                fontWeight = watchWeight(FontWeight.Medium),
                                maxLines = 1,
                                overflow = TextOverflow.Ellipsis,
                            )
                        }
                    }
                }
            }
        }
    }
}

@Composable
fun PreviewPane(viewModel: PortalViewModel, showPlayer: Boolean, modifier: Modifier) {
    val target = viewModel.playing
    val ui = viewModel.liveUi
    var nowMs by remember { mutableLongStateOf(System.currentTimeMillis()) }
    LaunchedEffect(Unit) {
        while (true) {
            nowMs = System.currentTimeMillis()
            delay(1000)
        }
    }
    val clock = remember(nowMs) {
        SimpleDateFormat("EEE d MMM HH:mm", Locale.getDefault()).format(Date(nowMs))
    }
    Column(modifier.background(WatchPalette.Preview).padding(12.dp)) {
        Box(
            Modifier
                .fillMaxWidth()
                .aspectRatio(16f / 9f)
                .border(1.dp, WatchPalette.Line)
                .background(WatchPalette.Bg)
                .clickable(enabled = target != null) { viewModel.showCinema(true) },
        ) {
            if (showPlayer && target != null) {
                AndroidView(
                    factory = { ctx ->
                        PlayerView(ctx).apply {
                            player = viewModel.session.player
                            useController = false
                            resizeMode = AspectRatioFrameLayout.RESIZE_MODE_FIT
                            setShowBuffering(PlayerView.SHOW_BUFFERING_NEVER)
                        }
                    },
                    update = { playerView -> playerView.player = viewModel.session.player },
                    modifier = Modifier.fillMaxSize(),
                )
            } else if (target != null) {
                Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                    Text("Playing full screen", color = WatchPalette.Muted)
                }
            }
            if (target?.live == true && ui.badge.isNotBlank()) {
                val badgeBg = if (ui.buffering || ui.reconnecting || ui.gaveUp) WatchPalette.Line else WatchPalette.LiveRed
                Text(
                    ui.badge,
                    color = WatchPalette.Text,
                    fontSize = 11.sp,
                    modifier = Modifier
                        .align(Alignment.TopEnd)
                        .padding(10.dp)
                        .background(badgeBg)
                        .padding(horizontal = 8.dp, vertical = 3.dp),
                )
            }
            if (ui.buffering && target != null) {
                CircularProgressIndicator(
                    color = WatchPalette.Text,
                    modifier = Modifier.align(Alignment.Center).size(42.dp),
                    strokeWidth = 3.dp,
                )
            }
        }
        val stat = streamStatLine(ui)
        if (stat.isNotBlank()) {
            val uhd = ui.width >= 3800 || ui.height >= 2100
            Text(
                stat,
                color = if (uhd) WatchPalette.Up else WatchPalette.Muted,
                fontSize = 11.sp,
                modifier = Modifier.padding(top = 8.dp),
            )
        }
        if (target?.live == true) {
            Row(
                Modifier.padding(top = 8.dp),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(6.dp),
            ) {
                Text("Live buffer", color = WatchPalette.Muted, fontSize = 11.sp)
                BufferProfile.entries.forEach { profile ->
                    BoxChip(profile.label, viewModel.bufferProfile == profile) {
                        viewModel.applyBufferProfile(profile)
                    }
                }
            }
        }
        Text(clock, color = WatchPalette.Muted, fontSize = 12.sp, modifier = Modifier.padding(top = 10.dp))
        Text(target?.title ?: "Select a channel", color = WatchPalette.Text, style = MaterialTheme.typography.titleMedium)
        val upcoming = upcomingEpg(viewModel.liveEpg)
        if (upcoming.isNotEmpty()) {
            val nowEvent = upcoming.firstOrNull { it.isNow } ?: upcoming.first()
            val span = (nowEvent.endMs - nowEvent.startMs).coerceAtLeast(1L)
            val frac = ((nowMs - nowEvent.startMs).toFloat() / span).coerceIn(0f, 1f)
            LinearProgressIndicator(
                progress = { frac },
                modifier = Modifier.fillMaxWidth().padding(top = 8.dp).height(3.dp),
                color = WatchPalette.Up,
                trackColor = WatchPalette.Line,
            )
            upcoming.take(8).forEach { event ->
                val tag = if (event.isNow) "NOW" else formatEpgTime(event)
                Text(
                    "$tag  ${event.title}",
                    color = if (event.isNow) WatchPalette.Up else WatchPalette.Muted,
                    fontSize = 12.sp,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                    modifier = Modifier.padding(top = 4.dp),
                )
            }
        }
        if (ui.message.isNotBlank()) {
            Text(ui.message, color = WatchPalette.Down, fontSize = 12.sp, modifier = Modifier.padding(top = 8.dp))
        }
        Row(Modifier.padding(top = 10.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            if (target != null) {
                BoxChip("Full screen", selected = false) { viewModel.showCinema(true) }
            }
            if (ui.gaveUp) {
                BoxChip("Retry", selected = false) { viewModel.session.retry() }
            }
        }
    }
}

private fun channelNum(item: CatalogItem, index: Int): String {
    val digits = item.id.filter { it.isDigit() }.takeLast(4)
    return digits.ifBlank { (index + 1).toString() }
}

private fun streamStatLine(ui: LiveSession.LiveUiState): String {
    val bits = mutableListOf<String>()
    if (ui.width > 0 && ui.height > 0) {
        bits += "${ui.width}×${ui.height}"
        val tag = when {
            ui.width >= 3800 || ui.height >= 2100 -> "4K"
            ui.width >= 1800 || ui.height >= 800 -> "1080p"
            ui.width >= 1200 -> "720p"
            else -> ""
        }
        if (tag.isNotBlank()) bits += tag
    }
    if (ui.videoCodec.isNotBlank()) bits += ui.videoCodec
    if (ui.audioCodec.isNotBlank()) bits += ui.audioCodec
    if (ui.audioChannels >= 6) bits += "5.1"
    else if (ui.audioChannels == 2) bits += "stereo"
    if (ui.aheadSec > 0.05f) bits += String.format(Locale.US, "%.1fs", ui.aheadSec)
    return bits.joinToString(" · ")
}

fun formatEpgTime(event: EpgEvent): String {
    val fmt = SimpleDateFormat("HH:mm", Locale.getDefault())
    return "${fmt.format(Date(event.startMs))}–${fmt.format(Date(event.endMs))}"
}
