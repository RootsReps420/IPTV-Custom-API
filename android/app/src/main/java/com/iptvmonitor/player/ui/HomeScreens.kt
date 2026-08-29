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
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.iptvmonitor.player.data.Category
import com.iptvmonitor.player.data.MediaKind
import com.iptvmonitor.player.data.PlaylistKind
import com.iptvmonitor.player.data.SavedPlaylist
import com.iptvmonitor.player.data.SeriesShow
import kotlinx.coroutines.delay

@Composable
fun HomeScreen(viewModel: PortalViewModel, modifier: Modifier = Modifier) {
    Column(
        modifier
            .fillMaxSize()
            .background(WatchPalette.Bg)
            .padding(horizontal = 36.dp, vertical = 28.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp),
    ) {
        Row(
            Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            BrandMark(size = 22.sp)
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                SwitchBtn("Add playlist") { viewModel.startAddPlaylist() }
                GhostBtn("Settings") { viewModel.openSettings() }
            }
        }
        Text("Playlists", style = MaterialTheme.typography.headlineLarge)
        Text(
            "Add an Xtream login or an M3U URL. Saving a source checks it and syncs the channel list.",
            color = WatchPalette.Muted,
            style = MaterialTheme.typography.bodyMedium,
        )
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
        LazyColumn(
            Modifier.weight(1f).fillMaxWidth(),
            verticalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            items(viewModel.playlists, key = { it.id }) { item ->
                PlaylistCard(
                    item = item,
                    stamp = viewModel::formatSyncStamp,
                    onOpen = { viewModel.openLibrary(item) },
                    onGroups = { viewModel.openGroupEditor(item) },
                    onEdit = { viewModel.startEditPlaylist(item) },
                    onDelete = { viewModel.deletePlaylist(item.id) },
                )
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
    stamp: (Long) -> String,
    onOpen: () -> Unit,
    onGroups: () -> Unit,
    onEdit: () -> Unit,
    onDelete: () -> Unit,
) {
    Column(
        Modifier
            .fillMaxWidth()
            .background(WatchPalette.Panel2)
            .border(1.dp, WatchPalette.Line)
            .padding(horizontal = 18.dp, vertical = 16.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        Text(item.name, color = WatchPalette.Text, style = MaterialTheme.typography.titleMedium)
        Text(
            buildString {
                append(if (item.kind == PlaylistKind.XTREAM) "Xtream" else "M3U")
                if (item.kind == PlaylistKind.XTREAM && item.username.isNotBlank()) {
                    append(" · ")
                    append(item.username)
                }
                if (item.lastLiveCount > 0) {
                    append(" · ")
                    append(item.lastLiveCount)
                    append(" channels")
                }
            },
            color = WatchPalette.Muted,
            style = MaterialTheme.typography.bodySmall,
        )
        Text(
            "Playlist ${stamp(item.lastPlaylistSyncAt)}" +
                if (item.lastEpgSyncAt > 0L) {
                    "  ·  EPG ${stamp(item.lastEpgSyncAt)}" +
                        if (item.lastEpgCount > 0) " (${item.lastEpgCount})" else ""
                } else {
                    ""
                },
            color = WatchPalette.Muted,
            style = MaterialTheme.typography.bodySmall,
        )
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            GhostBtn("Open", tint = WatchPalette.Up, onClick = onOpen)
            GhostBtn("Groups", onClick = onGroups)
            GhostBtn("Edit", onClick = onEdit)
            GhostBtn("Delete", tint = WatchPalette.Down, onClick = onDelete)
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
    viewModel: PortalViewModel,
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
    var autoEpg by remember { mutableStateOf(initial?.epgUrl.orEmpty()) }
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
    LaunchedEffect(m3u, kind) {
        if (kind != PlaylistKind.M3U) return@LaunchedEffect
        delay(700)
        val found = viewModel.peekM3uEpg(m3u)
        if (found.isNotBlank() && (epg.isBlank() || epg == autoEpg)) {
            epg = found
            autoEpg = found
        }
    }
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
            BrandMark(size = 14.sp)
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
                OutlinedTextField(epg, { epg = it }, label = { Text("EPG URL · filled from the M3U header") }, singleLine = true, colors = colors, modifier = Modifier.fillMaxWidth())
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
                            lastLiveCount = initial?.lastLiveCount ?: 0,
                            lastEpgCount = initial?.lastEpgCount ?: 0,
                            updateIntervalHours = initial?.updateIntervalHours ?: 4,
                            updateOnStart = initial?.updateOnStart ?: true,
                            favouriteLiveIds = initial?.favouriteLiveIds.orEmpty(),
                            favouriteMovieIds = initial?.favouriteMovieIds.orEmpty(),
                            favouriteShowIds = initial?.favouriteShowIds.orEmpty(),
                            liveGroupOrder = initial?.liveGroupOrder.orEmpty(),
                            movieGroupOrder = initial?.movieGroupOrder.orEmpty(),
                            showGroupOrder = initial?.showGroupOrder.orEmpty(),
                            liveGroupNames = initial?.liveGroupNames.orEmpty(),
                            movieGroupNames = initial?.movieGroupNames.orEmpty(),
                            showGroupNames = initial?.showGroupNames.orEmpty(),
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
            BrandMark(size = 14.sp)
            Text("Channel groups", style = MaterialTheme.typography.headlineMedium)
            Text(
                "Changes save as you click. Green groups are shown.",
                color = WatchPalette.Muted,
                style = MaterialTheme.typography.bodySmall,
            )
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                GhostBtn("Deselect all") { viewModel.setAllGroupsHidden(true) }
                GhostBtn("Select all") { viewModel.setAllGroupsHidden(false) }
            }
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
fun GhostBtn(
    label: String,
    tint: Color? = null,
    onClick: () -> Unit,
) {
    WatchHotBox(selected = false, onClick = onClick, chrome = WatchChrome.Ghost) { hot ->
        val color = tint ?: if (hot) WatchPalette.Text else WatchPalette.Muted
        Text(
            label.uppercase(),
            color = color,
            letterSpacing = 1.sp,
            fontSize = 11.sp,
        )
    }
}

@Composable
fun WatchAction(label: String, onClick: () -> Unit) {
    GhostBtn(label, onClick = onClick)
}

@Composable
fun BoxChip(label: String, selected: Boolean, allowFocus: Boolean = true, onClick: () -> Unit) {
    WatchHotBox(selected = selected, onClick = onClick, chrome = WatchChrome.Chip, allowFocus = allowFocus) { hot ->
        Text(label, color = if (hot) WatchPalette.Text else WatchPalette.Muted, fontSize = 11.sp)
    }
}

@Composable
fun ItemMenuOverlay(viewModel: PortalViewModel) {
    val menu = viewModel.itemMenu ?: return
    val item = menu.item
    val show = menu.show
    val favourite = when {
        item != null -> viewModel.isFavourite(item)
        show != null -> viewModel.isFavouriteShow(show)
        else -> false
    }
    val title = item?.name ?: show?.name ?: "Options"
    val canRecord = item != null && item.kind == MediaKind.LIVE
    OverlayHost(onDismiss = { viewModel.closeItemMenu() }) { requester ->
        Column(
            Modifier
                .widthIn(max = 480.dp)
                .fillMaxWidth()
                .background(WatchPalette.Panel)
                .border(1.dp, WatchPalette.Line)
                .padding(24.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            BrandMark(size = 14.sp)
            Text(title, color = WatchPalette.Text, style = MaterialTheme.typography.headlineSmall)
            if (item != null) {
                SwitchBtn(
                    if (favourite) "Remove from favourites" else "Add to favourites",
                    modifier = Modifier.focusRequester(requester),
                ) { viewModel.toggleFavourite(item) }
            } else if (show != null) {
                SwitchBtn(
                    if (favourite) "Remove from favourites" else "Add to favourites",
                    modifier = Modifier.focusRequester(requester),
                ) { viewModel.toggleFavouriteShow(show) }
            }
            if (canRecord && item != null) {
                GhostBtn(if (menu.event != null) "Record programme" else "Record channel") {
                    viewModel.startRecording(item, menu.event)
                    viewModel.closeItemMenu()
                }
            }
            GhostBtn("Cancel") { viewModel.closeItemMenu() }
        }
    }
}

@Composable
fun GroupMenuOverlay(viewModel: PortalViewModel) {
    val menu = viewModel.groupMenu ?: return
    val cat = menu.category
    OverlayHost(onDismiss = { viewModel.closeGroupMenu() }) { requester ->
        Column(
            Modifier
                .widthIn(max = 480.dp)
                .fillMaxWidth()
                .background(WatchPalette.Panel)
                .border(1.dp, WatchPalette.Line)
                .padding(24.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            BrandMark(size = 14.sp)
            Text(cat.name, color = WatchPalette.Text, style = MaterialTheme.typography.headlineSmall)
            SwitchBtn(
                "Move up",
                modifier = Modifier.focusRequester(requester),
            ) {
                viewModel.moveGroup(cat.id, -1)
            }
            SwitchBtn("Move down") {
                viewModel.moveGroup(cat.id, 1)
            }
            SwitchBtn("Rename") {
                viewModel.closeGroupMenu()
                viewModel.openTextPrompt("Rename group", cat.name, "Group name") { name ->
                    viewModel.renameGroup(cat.id, name)
                }
            }
            GhostBtn("Cancel") { viewModel.closeGroupMenu() }
        }
    }
}
