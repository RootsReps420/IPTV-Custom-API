package com.iptvmonitor.player.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
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
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.iptvmonitor.player.data.Category
import com.iptvmonitor.player.data.PlaylistKind
import com.iptvmonitor.player.data.SavedPlaylist

@Composable
fun HomeScreen(viewModel: PortalViewModel) {
    WatchBackdrop {
        HubScaffold {
            WatchPanel {
                Text("ROOTSIPTV", color = WatchPalette.Up, style = MaterialTheme.typography.labelLarge)
                Text("Playlists", style = MaterialTheme.typography.headlineLarge)
                Text(
                    "Add an Xtream login and/or an M3U URL. Settings is the panel on the right — Playlists, EPG, and Playback live there.",
                    color = WatchPalette.Muted,
                    style = MaterialTheme.typography.bodyMedium,
                )
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    SwitchBtn("Add playlist") { viewModel.startAddPlaylist() }
                    SwitchBtn("Settings") { viewModel.openSettings() }
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
                viewModel.error?.let { Text(it, color = WatchPalette.Down, style = MaterialTheme.typography.bodyMedium) }
                if (viewModel.playlists.isEmpty() && !viewModel.loading) {
                    Text("No playlists yet.", color = WatchPalette.Muted)
                }
                viewModel.playlists.forEach { item ->
                    PlaylistCard(
                        item = item,
                        onOpen = { viewModel.openLibrary(item) },
                        onSyncList = { viewModel.syncPlaylist(item) },
                        onSyncEpg = { viewModel.syncEpg(item) },
                        onGroups = { viewModel.openGroupEditor(item) },
                        onEdit = { viewModel.startEditPlaylist(item) },
                        onDelete = { viewModel.deletePlaylist(item.id) },
                    )
                }
            }
        }
    }
}

@Composable
fun SettingsScreen(viewModel: PortalViewModel) {
    SettingsDrawer(viewModel)
}

@Composable
private fun HubScaffold(content: @Composable ColumnScope.() -> Unit) {
    Box(Modifier.fillMaxSize(), contentAlignment = Alignment.TopCenter) {
        Column(
            Modifier
                .widthIn(max = 880.dp)
                .fillMaxWidth()
                .verticalScroll(rememberScrollState())
                .padding(horizontal = 32.dp, vertical = 40.dp),
            verticalArrangement = Arrangement.spacedBy(0.dp),
            content = content,
        )
    }
}

@Composable
private fun WatchPanel(content: @Composable ColumnScope.() -> Unit) {
    Column(
        Modifier
            .fillMaxWidth()
            .background(WatchPalette.Panel)
            .border(1.dp, WatchPalette.Line)
            .padding(horizontal = 28.dp, vertical = 24.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp),
        content = content,
    )
}

@Composable
private fun WatchSection(
    title: String,
    note: String? = null,
    content: @Composable ColumnScope.() -> Unit,
) {
    Column(verticalArrangement = Arrangement.spacedBy(10.dp), modifier = Modifier.fillMaxWidth()) {
        Text(
            title.uppercase(),
            color = WatchPalette.Muted,
            fontSize = 11.sp,
            letterSpacing = 1.4.sp,
        )
        if (note != null) {
            Text(note, color = WatchPalette.Muted, style = MaterialTheme.typography.bodySmall)
        }
        content()
    }
}

@Composable
private fun HubRule() {
    Box(Modifier.fillMaxWidth().height(1.dp).background(WatchPalette.Line))
}

@Composable
private fun PlaylistCard(
    item: SavedPlaylist,
    onOpen: () -> Unit,
    onSyncList: () -> Unit,
    onSyncEpg: () -> Unit,
    onGroups: () -> Unit,
    onEdit: () -> Unit,
    onDelete: () -> Unit,
) {
    Column(
        Modifier
            .fillMaxWidth()
            .background(WatchPalette.Panel2)
            .border(1.dp, WatchPalette.Line)
            .padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        Text(item.name, color = WatchPalette.Text, style = MaterialTheme.typography.titleMedium)
        Text(
            if (item.kind == PlaylistKind.XTREAM) "Xtream · ${item.username}" else "M3U",
            color = WatchPalette.Muted,
            style = MaterialTheme.typography.bodySmall,
        )
        Text(
            "List ${syncAge(item.lastPlaylistSyncAt)} · EPG ${syncAge(item.lastEpgSyncAt)}",
            color = WatchPalette.Muted,
            style = MaterialTheme.typography.bodySmall,
        )
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            SwitchBtn("Open") { onOpen() }
            GhostBtn("Sync list") { onSyncList() }
            GhostBtn("Sync EPG") { onSyncEpg() }
        }
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            GhostBtn("Groups") { onGroups() }
            GhostBtn("Edit") { onEdit() }
            SwitchBtn("Delete", danger = true) { onDelete() }
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
        modifier = Modifier.fillMaxWidth(),
    ) {
        Text(title, color = WatchPalette.Text, style = MaterialTheme.typography.bodyMedium)
        WatchListRow(selected = selectedId == null, onClick = { onPick(null) }, modifier = Modifier.fillMaxWidth()) {
            Text("Same as the playlist you open", color = watchInk(WatchPalette.Muted))
        }
        playlists.forEach { item ->
            WatchListRow(
                selected = current == item.id && selectedId != null,
                onClick = { onPick(item.id) },
                modifier = Modifier.fillMaxWidth(),
            ) {
                Text(
                    "${item.name} · ${if (item.kind == PlaylistKind.XTREAM) "Xtream" else "M3U"}",
                    color = watchInk(WatchPalette.Text),
                )
            }
        }
    }
}

@Composable
fun PlaylistEditorOverlay(
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
        focusedContainerColor = WatchPalette.Panel2,
        unfocusedContainerColor = WatchPalette.Panel2,
    )
    FocusDialog(onDismiss = onDismiss) { requester ->
        Column(
            Modifier
                .widthIn(max = 560.dp)
                .fillMaxWidth()
                .heightIn(max = 720.dp)
                .verticalScroll(rememberScrollState())
                .background(WatchPalette.Panel)
                .border(1.dp, WatchPalette.Line)
                .padding(28.dp),
            verticalArrangement = Arrangement.spacedBy(14.dp),
        ) {
            Text("ROOTSIPTV", color = WatchPalette.Up, style = MaterialTheme.typography.labelLarge)
            Text(
                if (initial == null) "Add playlist" else "Edit playlist",
                style = MaterialTheme.typography.headlineMedium,
            )
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                SwitchBtn(
                    "Xtream",
                    selected = kind == PlaylistKind.XTREAM,
                    modifier = Modifier.focusRequester(requester),
                ) { kind = PlaylistKind.XTREAM }
                SwitchBtn("M3U", selected = kind == PlaylistKind.M3U) { kind = PlaylistKind.M3U }
            }
            OutlinedTextField(name, { name = it }, label = { Text("Name") }, singleLine = true, colors = colors, modifier = Modifier.fillMaxWidth())
            if (kind == PlaylistKind.XTREAM) {
                OutlinedTextField(server, { server = it }, label = { Text("Server URL") }, singleLine = true, colors = colors, modifier = Modifier.fillMaxWidth())
                OutlinedTextField(username, { username = it }, label = { Text("Username") }, singleLine = true, colors = colors, modifier = Modifier.fillMaxWidth())
                OutlinedTextField(
                    password,
                    { password = it },
                    label = { Text("Password") },
                    singleLine = true,
                    visualTransformation = PasswordVisualTransformation(),
                    colors = colors,
                    modifier = Modifier.fillMaxWidth(),
                )
            } else {
                OutlinedTextField(m3u, { m3u = it }, label = { Text("M3U URL") }, singleLine = true, colors = colors, modifier = Modifier.fillMaxWidth())
                OutlinedTextField(epg, { epg = it }, label = { Text("EPG URL (optional)") }, singleLine = true, colors = colors, modifier = Modifier.fillMaxWidth())
            }
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                SwitchBtn("Save") {
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
                            updateIntervalHours = initial?.updateIntervalHours ?: 4,
                            updateOnStart = initial?.updateOnStart ?: true,
                        ),
                    )
                }
                GhostBtn("Cancel") { onDismiss() }
            }
        }
    }
}

@Composable
fun GroupEditorOverlay(
    viewModel: PortalViewModel,
    playlist: SavedPlaylist,
    onDismiss: () -> Unit,
) {
    FocusDialog(onDismiss = onDismiss) { requester ->
        Column(
            Modifier
                .widthIn(max = 640.dp)
                .fillMaxWidth()
                .heightIn(max = 720.dp)
                .background(WatchPalette.Panel)
                .border(1.dp, WatchPalette.Line)
                .padding(24.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            Text("ROOTSIPTV", color = WatchPalette.Up, style = MaterialTheme.typography.labelLarge)
            Text("Channel groups", style = MaterialTheme.typography.headlineMedium)
            Text(
                "Changes save as you click. Green groups are shown.",
                color = WatchPalette.Muted,
                style = MaterialTheme.typography.bodySmall,
            )
            if (viewModel.groupEditorLoading) {
                CircularProgressIndicator(color = WatchPalette.Up, modifier = Modifier.align(Alignment.CenterHorizontally))
            } else {
                LazyColumn(
                    Modifier.heightIn(max = 480.dp).fillMaxWidth().focusRequester(requester),
                    verticalArrangement = Arrangement.spacedBy(6.dp),
                ) {
                    groupSection("Live", viewModel.groupEditorLive, viewModel.hiddenLiveDraft) {
                        viewModel.hiddenLiveDraft = it
                        viewModel.saveHiddenGroups(
                            playlist,
                            it.toList(),
                            viewModel.hiddenMovieDraft.toList(),
                            viewModel.hiddenShowDraft.toList(),
                            close = false,
                        )
                    }
                    groupSection("Movies", viewModel.groupEditorMovies, viewModel.hiddenMovieDraft) {
                        viewModel.hiddenMovieDraft = it
                        viewModel.saveHiddenGroups(
                            playlist,
                            viewModel.hiddenLiveDraft.toList(),
                            it.toList(),
                            viewModel.hiddenShowDraft.toList(),
                            close = false,
                        )
                    }
                    groupSection("Shows", viewModel.groupEditorShows, viewModel.hiddenShowDraft) {
                        viewModel.hiddenShowDraft = it
                        viewModel.saveHiddenGroups(
                            playlist,
                            viewModel.hiddenLiveDraft.toList(),
                            viewModel.hiddenMovieDraft.toList(),
                            it.toList(),
                            close = false,
                        )
                    }
                }
            }
            GhostBtn("Done") { onDismiss() }
        }
    }
}

private fun androidx.compose.foundation.lazy.LazyListScope.groupSection(
    title: String,
    categories: List<Category>,
    hidden: Set<String>,
    onChange: (Set<String>) -> Unit,
) {
    if (categories.isEmpty()) return
    item { Text(title.uppercase(), color = WatchPalette.Up, fontSize = 11.sp, letterSpacing = 1.2.sp, modifier = Modifier.padding(top = 10.dp)) }
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
fun SwitchBtn(
    label: String,
    selected: Boolean = false,
    danger: Boolean = false,
    modifier: Modifier = Modifier,
    onClick: () -> Unit,
) {
    WatchHotBox(
        selected = selected,
        onClick = onClick,
        modifier = modifier,
        chrome = if (danger) WatchChrome.Danger else WatchChrome.Accent,
    ) {
        Text(
            label.uppercase(),
            color = if (danger) WatchPalette.Down else WatchPalette.Up,
            letterSpacing = 1.4.sp,
            fontSize = 11.sp,
        )
    }
}

@Composable
fun GhostBtn(label: String, onClick: () -> Unit) {
    WatchHotBox(selected = false, onClick = onClick, chrome = WatchChrome.Ghost) { hot ->
        Text(
            label.uppercase(),
            color = if (hot) WatchPalette.Text else WatchPalette.Muted,
            letterSpacing = 1.sp,
            fontSize = 11.sp,
        )
    }
}

@Composable
fun WatchAction(label: String, onClick: () -> Unit) {
    GhostBtn(label, onClick)
}

@Composable
fun BoxChip(label: String, selected: Boolean, onClick: () -> Unit) {
    WatchHotBox(selected = selected, onClick = onClick, chrome = WatchChrome.Chip) { hot ->
        Text(label, color = if (hot) WatchPalette.Text else WatchPalette.Muted, fontSize = 11.sp)
    }
}
