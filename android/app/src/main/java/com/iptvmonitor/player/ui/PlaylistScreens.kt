package com.iptvmonitor.player.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.selection.selectable
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.RadioButton
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
import com.iptvmonitor.player.data.PlaylistKind
import com.iptvmonitor.player.data.SavedPlaylist

@Composable
fun PlaylistListScreen(
    viewModel: PortalViewModel,
    onOpen: (SavedPlaylist) -> Unit,
) {
    var editor by remember { mutableStateOf<SavedPlaylist?>(null) }
    var creating by remember { mutableStateOf(false) }

    Column(
        Modifier
            .fillMaxSize()
            .padding(24.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp),
    ) {
        Text("Portal Player", style = MaterialTheme.typography.headlineMedium)
        Text(
            "Add an Xtream login or an M3U URL. Nothing is baked into the app — each device stores its own playlists.",
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            Button(onClick = { creating = true }) { Text("Add playlist") }
        }
        if (viewModel.loading) {
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                CircularProgressIndicator()
                Text(viewModel.loadingLabel.ifBlank { "Working…" })
            }
        }
        viewModel.error?.let { Text(it, color = MaterialTheme.colorScheme.error) }
        if (viewModel.playlists.isEmpty() && !viewModel.loading) {
            Text("No playlists yet.", color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
        LazyColumn(verticalArrangement = Arrangement.spacedBy(10.dp), modifier = Modifier.weight(1f)) {
            items(viewModel.playlists, key = { it.id }) { item ->
                Card(
                    onClick = { onOpen(item) },
                    colors = CardDefaults.cardColors(),
                    modifier = Modifier.fillMaxWidth().tvFocusBorder(),
                ) {
                    Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                        Text(item.name, style = MaterialTheme.typography.titleMedium)
                        Text(
                            if (item.kind == PlaylistKind.XTREAM) "Xtream · ${item.username}" else "M3U",
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                            TextButton(onClick = { editor = item }) { Text("Edit") }
                            TextButton(onClick = { viewModel.deletePlaylist(item.id) }) { Text("Delete") }
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

    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(if (initial == null) "Add playlist" else "Edit playlist") },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Row {
                    KindRadio("Xtream", kind == PlaylistKind.XTREAM) { kind = PlaylistKind.XTREAM }
                    KindRadio("M3U", kind == PlaylistKind.M3U) { kind = PlaylistKind.M3U }
                }
                OutlinedTextField(name, { name = it }, label = { Text("Name") }, singleLine = true)
                if (kind == PlaylistKind.XTREAM) {
                    OutlinedTextField(server, { server = it }, label = { Text("Server URL") }, singleLine = true)
                    OutlinedTextField(username, { username = it }, label = { Text("Username") }, singleLine = true)
                    OutlinedTextField(
                        password,
                        { password = it },
                        label = { Text("Password") },
                        singleLine = true,
                        visualTransformation = PasswordVisualTransformation(),
                    )
                } else {
                    OutlinedTextField(m3u, { m3u = it }, label = { Text("M3U URL") }, singleLine = true)
                    OutlinedTextField(epg, { epg = it }, label = { Text("EPG URL (optional)") }, singleLine = true)
                }
            }
        },
        confirmButton = {
            Button(
                onClick = {
                    val playlist = SavedPlaylist(
                        id = initial?.id ?: java.util.UUID.randomUUID().toString(),
                        name = name.trim().ifBlank { if (kind == PlaylistKind.XTREAM) username else "M3U" },
                        kind = kind,
                        server = server.trim(),
                        username = username.trim(),
                        password = password,
                        m3uUrl = m3u.trim(),
                        epgUrl = epg.trim(),
                    )
                    onSave(playlist)
                },
            ) { Text("Save") }
        },
        dismissButton = { OutlinedButton(onClick = onDismiss) { Text("Cancel") } },
    )
}

@Composable
private fun KindRadio(label: String, selected: Boolean, onClick: () -> Unit) {
    Row(
        Modifier.selectable(selected, onClick = onClick).padding(end = 16.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        RadioButton(selected, onClick)
        Text(label)
    }
}
