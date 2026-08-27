package com.iptvmonitor.player.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import com.iptvmonitor.player.data.Category
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.selection.selectable
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.RadioButton
import androidx.compose.material3.RadioButtonDefaults
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.iptvmonitor.player.data.PlaylistKind
import com.iptvmonitor.player.data.SavedPlaylist
import com.iptvmonitor.player.player.BufferProfile

@Composable
fun HomeScreen(viewModel: PortalViewModel) {
    var editor by remember { mutableStateOf<SavedPlaylist?>(null) }
    var creating by remember { mutableStateOf(false) }

    WatchBackdrop {
        Column(
            Modifier
                .fillMaxSize()
                .verticalScroll(rememberScrollState())
                .padding(horizontal = 28.dp, vertical = 36.dp),
            verticalArrangement = Arrangement.spacedBy(16.dp),
        ) {
            Text("ROOTSIPTV", color = WatchPalette.Up, style = MaterialTheme.typography.labelLarge)
            Text("Playlists", style = MaterialTheme.typography.headlineLarge)
            Text(
                "Add an Xtream login and/or an M3U URL. Point Live at the M3U and Movies at Xtream in Settings if you want both.",
                color = WatchPalette.Muted,
                style = MaterialTheme.typography.bodyMedium,
            )
            Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                WatchAction("Add playlist") { creating = true }
                WatchAction("Settings") { viewModel.openSettings() }
            }
            if (viewModel.loading) {
                Row(
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(12.dp),
                ) {
                    CircularProgressIndicator(color = WatchPalette.Up)
                    Text(viewModel.loadingLabel.ifBlank { "Working…" }, color = WatchPalette.Muted)
                }
            }
            viewModel.error?.let { Text(it, color = WatchPalette.Down) }
            if (viewModel.playlists.isEmpty() && !viewModel.loading) {
                Text("No playlists yet.", color = WatchPalette.Muted)
            }
            viewModel.playlists.forEach { item ->
                WatchListRow(
                    selected = false,
                    onClick = { viewModel.openLibrary(item) },
                    modifier = Modifier.fillMaxWidth().widthIn(max = 720.dp),
                ) {
                    Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
                        Text(item.name, color = watchInk(WatchPalette.Text), style = MaterialTheme.typography.titleMedium)
                        Text(
                            if (item.kind == PlaylistKind.XTREAM) "Xtream · ${item.username}" else "M3U",
                            color = watchInk(WatchPalette.Muted),
                            style = MaterialTheme.typography.bodySmall,
                        )
                        Text(
                            "List ${syncAge(item.lastPlaylistSyncAt)} · EPG ${syncAge(item.lastEpgSyncAt)}",
                            color = WatchPalette.Muted,
                            style = MaterialTheme.typography.bodySmall,
                        )
                        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                            TextButton(onClick = { viewModel.syncPlaylist(item) }) { Text("Sync playlist", color = WatchPalette.Up) }
                            TextButton(onClick = { viewModel.syncEpg(item) }) { Text("Sync EPG", color = WatchPalette.Up) }
                        }
                        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                            TextButton(onClick = { viewModel.openGroupEditor(item) }) { Text("Groups", color = WatchPalette.Up) }
                            TextButton(onClick = { editor = item }) { Text("Edit", color = WatchPalette.Up) }
                            TextButton(onClick = { viewModel.deletePlaylist(item.id) }) {
                                Text("Delete", color = WatchPalette.Down)
                            }
                        }
                    }
                }
            }
        }
    }

    if (creating || editor != null) {
        PlaylistEditorDialog(
            initial = editor,
            onDismiss = {
                creating = false
                editor = null
            },
            onSave = {
                viewModel.savePlaylist(it)
                creating = false
                editor = null
            },
        )
    }

    viewModel.groupEditor?.let { playlist ->
        GroupEditorDialog(
            viewModel = viewModel,
            playlist = playlist,
            onDismiss = { viewModel.closeGroupEditor() },
        )
    }
}

@Composable
fun SettingsScreen(viewModel: PortalViewModel) {
    WatchBackdrop {
        Column(
            Modifier
                .fillMaxSize()
                .verticalScroll(rememberScrollState())
                .padding(28.dp),
            verticalArrangement = Arrangement.spacedBy(16.dp),
        ) {
            Text("ROOTSIPTV", color = WatchPalette.Up, style = MaterialTheme.typography.labelLarge)
            Text("Settings", style = MaterialTheme.typography.headlineLarge)
            Text("Live buffer", color = WatchPalette.Muted, style = MaterialTheme.typography.labelLarge)
            Text(
                "Same Small / Medium / Large cushion as Watch. Change it before a channel; 0.97× still eases in if the buffer thins.",
                color = WatchPalette.Muted,
                style = MaterialTheme.typography.bodySmall,
            )
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                BufferProfile.entries.forEach { profile ->
                    val here = viewModel.bufferProfile == profile
                    BoxChip(profile.label, here) { viewModel.applyBufferProfile(profile) }
                }
            }
            Text(viewModel.bufferProfile.hint, color = WatchPalette.Muted, style = MaterialTheme.typography.bodySmall)

            Spacer(Modifier.height(8.dp))
            Text("Library sources", color = WatchPalette.Muted, style = MaterialTheme.typography.labelLarge)
            Text(
                "Live can come from an M3U while Movies and Shows come from Xtream.",
                color = WatchPalette.Muted,
                style = MaterialTheme.typography.bodySmall,
            )
            SourcePicker("Live source", viewModel.playlists, viewModel.liveSourceId(), viewModel.selectedPlaylist?.id) {
                viewModel.setLiveSourceId(it)
            }
            SourcePicker("Movies & shows", viewModel.playlists, viewModel.vodSourceId(), viewModel.selectedPlaylist?.id) {
                viewModel.setVodSourceId(it)
            }

            Spacer(Modifier.height(8.dp))
            WatchListRow(selected = viewModel.autoOpenLast, onClick = { viewModel.applyAutoOpenLast(!viewModel.autoOpenLast) }) {
                Text(
                    if (viewModel.autoOpenLast) "Open last library on launch" else "Start on the playlist list",
                    color = watchInk(WatchPalette.Text),
                )
            }

            WatchAction("Back") { viewModel.backFromSettings() }
        }
    }
}

@Composable
private fun SourcePicker(
    title: String,
    playlists: List<SavedPlaylist>,
    selectedId: String?,
    fallbackId: String?,
    onPick: (String?) -> Unit,
) {
    val current = selectedId ?: fallbackId
    Column(
        verticalArrangement = Arrangement.spacedBy(6.dp),
        modifier = Modifier.fillMaxWidth().widthIn(max = 640.dp),
    ) {
        Text(title, color = WatchPalette.Text, style = MaterialTheme.typography.titleMedium)
        WatchListRow(selected = selectedId == null, onClick = { onPick(null) }) {
            Text("Same as the playlist you open", color = watchInk(WatchPalette.Muted))
        }
        playlists.forEach { item ->
            WatchListRow(selected = current == item.id && selectedId != null, onClick = { onPick(item.id) }) {
                Text(
                    "${item.name} · ${if (item.kind == PlaylistKind.XTREAM) "Xtream" else "M3U"}",
                    color = watchInk(WatchPalette.Text),
                )
            }
        }
    }
}

@Composable
private fun PlaylistEditorDialog(
    initial: SavedPlaylist?,
    onDismiss: () -> Unit,
    onSave: (SavedPlaylist) -> Unit,
) {
    var kind by remember { mutableStateOf(initial?.kind ?: PlaylistKind.XTREAM) }
    var name by remember { mutableStateOf(initial?.name ?: "") }
    var server by remember { mutableStateOf(initial?.server ?: "") }
    var username by remember { mutableStateOf(initial?.username ?: "") }
    var password by remember { mutableStateOf(initial?.password ?: "") }
    var m3u by remember { mutableStateOf(initial?.m3uUrl ?: "") }
    var epg by remember { mutableStateOf(initial?.epgUrl ?: "") }
    val colors = OutlinedTextFieldDefaults.colors(
        focusedBorderColor = WatchPalette.Up,
        unfocusedBorderColor = WatchPalette.Line,
        focusedLabelColor = WatchPalette.Muted,
        unfocusedLabelColor = WatchPalette.Muted,
        cursorColor = WatchPalette.Up,
        focusedTextColor = WatchPalette.Text,
        unfocusedTextColor = WatchPalette.Text,
    )

    AlertDialog(
        onDismissRequest = onDismiss,
        containerColor = WatchPalette.Panel,
        title = {
            Text(if (initial == null) "Add playlist" else "Edit playlist", color = WatchPalette.Text)
        },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Row {
                    KindRadio("Xtream", kind == PlaylistKind.XTREAM) { kind = PlaylistKind.XTREAM }
                    KindRadio("M3U", kind == PlaylistKind.M3U) { kind = PlaylistKind.M3U }
                }
                OutlinedTextField(name, { name = it }, label = { Text("Name") }, singleLine = true, colors = colors)
                if (kind == PlaylistKind.XTREAM) {
                    OutlinedTextField(server, { server = it }, label = { Text("Server URL") }, singleLine = true, colors = colors)
                    OutlinedTextField(username, { username = it }, label = { Text("Username") }, singleLine = true, colors = colors)
                    OutlinedTextField(
                        password,
                        { password = it },
                        label = { Text("Password") },
                        singleLine = true,
                        visualTransformation = PasswordVisualTransformation(),
                        colors = colors,
                    )
                } else {
                    OutlinedTextField(m3u, { m3u = it }, label = { Text("M3U URL") }, singleLine = true, colors = colors)
                    OutlinedTextField(epg, { epg = it }, label = { Text("EPG URL (optional)") }, singleLine = true, colors = colors)
                }
            }
        },
        confirmButton = {
            Button(
                onClick = {
                    onSave(
                        SavedPlaylist(
                            id = initial?.id ?: java.util.UUID.randomUUID().toString(),
                            name = name.trim().ifBlank { if (kind == PlaylistKind.XTREAM) username else "M3U" },
                            kind = kind,
                            server = server.trim(),
                            username = username.trim(),
                            password = password,
                            m3uUrl = m3u.trim(),
                            epgUrl = epg.trim(),
                            hiddenLiveCategories = initial?.hiddenLiveCategories.orEmpty(),
                            hiddenMovieCategories = initial?.hiddenMovieCategories.orEmpty(),
                            hiddenSeriesCategories = initial?.hiddenSeriesCategories.orEmpty(),
                            lastPlaylistSyncAt = initial?.lastPlaylistSyncAt ?: 0L,
                            lastEpgSyncAt = initial?.lastEpgSyncAt ?: 0L,
                        ),
                    )
                },
                colors = ButtonDefaults.buttonColors(containerColor = WatchPalette.Up, contentColor = WatchPalette.Bg),
            ) { Text("Save") }
        },
        dismissButton = {
            TextButton(onClick = onDismiss) { Text("Cancel", color = WatchPalette.Muted) }
        },
    )
}

@Composable
private fun GroupEditorDialog(
    viewModel: PortalViewModel,
    playlist: SavedPlaylist,
    onDismiss: () -> Unit,
) {
    var hiddenLive by remember(playlist.id, viewModel.groupEditorLive) {
        mutableStateOf(playlist.hiddenLiveCategories.toSet())
    }
    var hiddenMovies by remember(playlist.id, viewModel.groupEditorMovies) {
        mutableStateOf(playlist.hiddenMovieCategories.toSet())
    }
    var hiddenShows by remember(playlist.id, viewModel.groupEditorShows) {
        mutableStateOf(playlist.hiddenSeriesCategories.toSet())
    }
    AlertDialog(
        onDismissRequest = onDismiss,
        containerColor = WatchPalette.Panel,
        title = { Text("Channel groups", color = WatchPalette.Text) },
        text = {
            if (viewModel.groupEditorLoading) {
                CircularProgressIndicator(color = WatchPalette.Up)
            } else {
                LazyColumn(
                    Modifier.heightIn(max = 420.dp),
                    verticalArrangement = Arrangement.spacedBy(6.dp),
                ) {
                    item {
                        Text(
                            "Green groups are shown. Tap to hide (US packs, etc.).",
                            color = WatchPalette.Muted,
                            style = MaterialTheme.typography.bodySmall,
                        )
                    }
                    groupSection("Live", viewModel.groupEditorLive, hiddenLive) { hiddenLive = it }
                    groupSection("Movies", viewModel.groupEditorMovies, hiddenMovies) { hiddenMovies = it }
                    groupSection("Shows", viewModel.groupEditorShows, hiddenShows) { hiddenShows = it }
                }
            }
        },
        confirmButton = {
            Button(
                onClick = {
                    viewModel.saveHiddenGroups(
                        playlist,
                        hiddenLive.toList(),
                        hiddenMovies.toList(),
                        hiddenShows.toList(),
                    )
                },
                colors = ButtonDefaults.buttonColors(containerColor = WatchPalette.Up, contentColor = WatchPalette.Bg),
            ) { Text("Save") }
        },
        dismissButton = {
            TextButton(onClick = onDismiss) { Text("Cancel", color = WatchPalette.Muted) }
        },
    )
}

private fun androidx.compose.foundation.lazy.LazyListScope.groupSection(
    title: String,
    categories: List<Category>,
    hidden: Set<String>,
    onChange: (Set<String>) -> Unit,
) {
    if (categories.isEmpty()) return
    item { Text(title, color = WatchPalette.Up, modifier = Modifier.padding(top = 10.dp)) }
    items(categories, key = { "$title-${it.id}" }) { cat ->
        val shown = cat.id !in hidden
        WatchListRow(
            selected = shown,
            onClick = {
                onChange(if (shown) hidden + cat.id else hidden - cat.id)
            },
            modifier = Modifier.fillMaxWidth(),
        ) {
            Text(
                if (shown) cat.name else "${cat.name}  · hidden",
                color = if (watchHot()) WatchPalette.Up else if (shown) WatchPalette.Text else WatchPalette.Muted,
            )
        }
    }
}

private fun syncAge(ms: Long): String {
    if (ms <= 0L) return "never"
    val min = (System.currentTimeMillis() - ms) / 60_000L
    return when {
        min < 1L -> "just now"
        min < 60L -> "${min}m ago"
        min < 1_440L -> "${min / 60L}h ago"
        else -> "${min / 1_440L}d ago"
    }
}

@Composable
private fun KindRadio(label: String, selected: Boolean, onClick: () -> Unit) {
    Row(
        Modifier.selectable(selected, onClick = onClick).padding(end = 16.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        RadioButton(selected, onClick, colors = RadioButtonDefaults.colors(selectedColor = WatchPalette.Up))
        Text(label, color = WatchPalette.Text)
    }
}

@Composable
fun WatchAction(label: String, onClick: () -> Unit) {
    WatchHotBox(selected = false, onClick = onClick, chrome = WatchChrome.Ghost) { hot ->
        Text(
            label.uppercase(),
            color = if (hot) WatchPalette.Text else WatchPalette.Muted,
            letterSpacing = 1.sp,
            fontSize = 13.sp,
        )
    }
}

@Composable
fun BoxChip(label: String, selected: Boolean, onClick: () -> Unit) {
    WatchHotBox(selected = selected, onClick = onClick, chrome = WatchChrome.Chip) { hot ->
        Text(label, color = if (hot) WatchPalette.Text else WatchPalette.Muted, fontSize = 11.sp)
    }
}
