package com.iptvmonitor.player.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.grid.GridCells
import androidx.compose.foundation.lazy.grid.LazyVerticalGrid
import androidx.compose.foundation.lazy.grid.items
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.FilterChip
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.ScrollableTabRow
import androidx.compose.material3.Tab
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import coil.compose.AsyncImage
import com.iptvmonitor.player.data.CatalogItem
import com.iptvmonitor.player.data.EpgEvent
import com.iptvmonitor.player.data.SeriesShow
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

@Composable
fun BrowseScreen(viewModel: PortalViewModel) {
    val playlist = viewModel.selectedPlaylist ?: return
    Column(Modifier.fillMaxSize()) {
        Row(
            Modifier
                .fillMaxWidth()
                .padding(16.dp),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Column(Modifier.weight(1f)) {
                Text(playlist.name, style = MaterialTheme.typography.headlineSmall)
                Text(
                    "${viewModel.catalog.live.size} live · ${viewModel.catalog.movies.size} movies · ${viewModel.catalog.series.size} shows",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            TextButton(onClick = { viewModel.closePlaylist() }) { Text("Playlists") }
        }
        ScrollableTabRow(selectedTabIndex = viewModel.tab.ordinal) {
            BrowseTab.entries.forEach { tab ->
                Tab(
                    selected = viewModel.tab == tab,
                    onClick = {
                        viewModel.tab = tab
                        viewModel.categoryId = viewModel.currentCategories().firstOrNull()?.id
                    },
                    text = { Text(tab.name) },
                )
            }
        }
        OutlinedTextField(
            value = viewModel.query,
            onValueChange = { viewModel.query = it },
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 16.dp, vertical = 8.dp),
            singleLine = true,
            label = { Text("Search") },
        )
        if (viewModel.loading) {
            Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                Column(horizontalAlignment = Alignment.CenterHorizontally) {
                    CircularProgressIndicator()
                    Text(viewModel.loadingLabel, modifier = Modifier.padding(top = 12.dp))
                }
            }
            return
        }
        viewModel.error?.let {
            Text(it, color = MaterialTheme.colorScheme.error, modifier = Modifier.padding(16.dp))
        }
        Row(Modifier.fillMaxSize()) {
            val cats = viewModel.currentCategories()
            if (cats.isNotEmpty()) {
                LazyColumn(
                    Modifier.width(if (viewModel.isTelevision) 260.dp else 180.dp),
                    contentPadding = PaddingValues(8.dp),
                    verticalArrangement = Arrangement.spacedBy(4.dp),
                ) {
                    item {
                        FilterChip(
                            selected = viewModel.categoryId == null,
                            onClick = { viewModel.categoryId = null },
                            label = { Text("All") },
                        )
                    }
                    items(cats, key = { it.id }) { cat ->
                        FilterChip(
                            selected = viewModel.categoryId == cat.id,
                            onClick = { viewModel.categoryId = cat.id },
                            label = { Text(cat.name, maxLines = 1, overflow = TextOverflow.Ellipsis) },
                        )
                    }
                }
            }
            when (viewModel.tab) {
                BrowseTab.SHOWS -> {
                    if (viewModel.catalog.series.isNotEmpty()) {
                        ShowGrid(viewModel, viewModel.visibleShows())
                    } else {
                        ItemGrid(viewModel, viewModel.visibleItems())
                    }
                }
                else -> ItemGrid(viewModel, viewModel.visibleItems())
            }
        }
    }

    val show = viewModel.seriesDetail
    if (show != null) {
        EpisodeSheet(viewModel, show)
    }
}

@Composable
private fun ItemGrid(viewModel: PortalViewModel, items: List<CatalogItem>) {
    LazyVerticalGrid(
        columns = GridCells.Adaptive(if (viewModel.isTelevision) 180.dp else 140.dp),
        contentPadding = PaddingValues(12.dp),
        horizontalArrangement = Arrangement.spacedBy(10.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp),
        modifier = Modifier.fillMaxSize(),
    ) {
        items(items, key = { it.id + it.playbackUrl }) { item ->
            Card(onClick = { viewModel.playItem(item) }) {
                Column {
                    AsyncImage(
                        model = item.logo.ifBlank { null },
                        contentDescription = item.name,
                        modifier = Modifier
                            .fillMaxWidth()
                            .aspectRatio(16f / 9f),
                        contentScale = ContentScale.Crop,
                    )
                    Text(
                        item.name,
                        modifier = Modifier.padding(8.dp),
                        maxLines = 2,
                        overflow = TextOverflow.Ellipsis,
                        style = MaterialTheme.typography.bodyMedium,
                    )
                    val epg = viewModel.epgFor(item).firstOrNull { it.isNow } ?: viewModel.epgFor(item).firstOrNull()
                    if (epg != null) {
                        Text(
                            epg.title,
                            modifier = Modifier.padding(horizontal = 8.dp, vertical = 0.dp),
                            maxLines = 1,
                            overflow = TextOverflow.Ellipsis,
                            style = MaterialTheme.typography.labelSmall,
                            color = MaterialTheme.colorScheme.primary,
                        )
                    }
                }
            }
        }
    }
}

@Composable
private fun ShowGrid(viewModel: PortalViewModel, shows: List<SeriesShow>) {
    LazyVerticalGrid(
        columns = GridCells.Adaptive(if (viewModel.isTelevision) 180.dp else 140.dp),
        contentPadding = PaddingValues(12.dp),
        horizontalArrangement = Arrangement.spacedBy(10.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp),
        modifier = Modifier.fillMaxSize(),
    ) {
        items(shows, key = { it.id }) { show ->
            Card(onClick = { viewModel.openSeries(show) }) {
                Column {
                    AsyncImage(
                        model = show.logo.ifBlank { null },
                        contentDescription = show.name,
                        modifier = Modifier
                            .fillMaxWidth()
                            .aspectRatio(2f / 3f),
                        contentScale = ContentScale.Crop,
                    )
                    Text(
                        show.name,
                        modifier = Modifier.padding(8.dp),
                        maxLines = 2,
                        overflow = TextOverflow.Ellipsis,
                    )
                }
            }
        }
    }
}

@Composable
private fun EpisodeSheet(viewModel: PortalViewModel, show: SeriesShow) {
    androidx.compose.material3.AlertDialog(
        onDismissRequest = { viewModel.seriesDetail = null },
        title = { Text(show.name) },
        text = {
            if (viewModel.episodesLoading) {
                CircularProgressIndicator()
            } else if (viewModel.episodes.isEmpty()) {
                Text("No episodes returned.")
            } else {
                LazyColumn {
                    items(viewModel.episodes, key = { it.id }) { ep ->
                        TextButton(onClick = { viewModel.playEpisode(show, ep) }) {
                            Text("S${ep.season}E${ep.episode}  ${ep.title}")
                        }
                    }
                }
            }
        },
        confirmButton = {
            Button(onClick = { viewModel.seriesDetail = null }) { Text("Close") }
        },
    )
}

fun formatEpgTime(event: EpgEvent): String {
    val fmt = SimpleDateFormat("HH:mm", Locale.getDefault())
    return "${fmt.format(Date(event.startMs))}–${fmt.format(Date(event.endMs))}"
}
