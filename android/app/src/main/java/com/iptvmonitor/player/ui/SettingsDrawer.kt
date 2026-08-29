package com.iptvmonitor.player.ui

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.focusGroup
import androidx.compose.foundation.focusable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
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
import androidx.compose.ui.draw.clip
import androidx.compose.ui.focus.FocusDirection
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusProperties
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.platform.LocalFocusManager
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.iptvmonitor.player.BuildConfig
import com.iptvmonitor.player.data.PlaylistKind
import com.iptvmonitor.player.data.STREAM_USER_AGENT
import com.iptvmonitor.player.data.SavedPlaylist
import com.iptvmonitor.player.player.BufferProfile
import kotlinx.coroutines.delay

@Composable
fun SettingsDrawer(viewModel: PortalViewModel) {
    val rev = viewModel.settingsRev
    val prefs = viewModel.prefs()
    val panel = remember { FocusRequester() }
    val focus = LocalFocusManager.current
    val eatClicks = remember { MutableInteractionSource() }
    val nested = viewModel.choicePrompt != null || viewModel.textPrompt != null
    BackHandler { viewModel.popSettings() }
    LaunchedEffect(viewModel.settingsPage) {
        delay(200)
        if (viewModel.choicePrompt != null || viewModel.textPrompt != null) return@LaunchedEffect
        runCatching {
            panel.requestFocus()
            if (viewModel.settingsPage != SettingsPage.ROOT) {
                focus.moveFocus(FocusDirection.Down)
            }
        }
    }
    Box(
        Modifier
            .fillMaxSize()
            .background(WatchPalette.Bg.copy(alpha = 0.55f))
            .clickable(interactionSource = eatClicks, indication = null) {}
            .focusProperties { canFocus = !nested },
    ) {
        Column(
            Modifier
                .align(Alignment.CenterEnd)
                .fillMaxHeight()
                .widthIn(min = 380.dp, max = 520.dp)
                .fillMaxWidth(0.42f)
                .background(WatchPalette.Panel)
                .border(1.dp, WatchPalette.Line)
                .then(
                    if (viewModel.settingsPage == SettingsPage.ROOT) {
                        Modifier
                    } else {
                        Modifier.focusRequester(panel).focusable()
                    },
                )
                .focusGroup()
                .verticalScroll(rememberScrollState())
                .padding(bottom = 28.dp),
        ) {
                when (viewModel.settingsPage) {
                    SettingsPage.ROOT -> RootPage(viewModel, panel)
                    SettingsPage.GENERAL -> GeneralPage(viewModel, prefs)
                    SettingsPage.PLAYLISTS -> PlaylistsPage(viewModel)
                    SettingsPage.PLAYLIST -> PlaylistDetailPage(viewModel, prefs)
                    SettingsPage.GROUPS -> GroupsPage(viewModel)
                    SettingsPage.EPG -> EpgPage(viewModel, prefs)
                    SettingsPage.EPG_SOURCES -> EpgSourcesPage(viewModel, prefs)
                    SettingsPage.APPEARANCE -> AppearancePage(viewModel, prefs)
                    SettingsPage.PLAYBACK -> PlaybackPage(viewModel, prefs)
                    SettingsPage.AFR -> AfrPage(viewModel, prefs)
                    SettingsPage.VOD -> VodPage(viewModel, prefs)
                    SettingsPage.REMOTE -> RemotePage(viewModel, prefs)
                    SettingsPage.PARENTAL -> ParentalPage(viewModel, prefs)
                    SettingsPage.OTHER -> OtherPage(viewModel, prefs)
                    SettingsPage.ABOUT -> AboutPage()
                }
        }
    }
}

@Composable
private fun DrawerTitle(text: String) {
    Text(
        text,
        color = WatchPalette.Text,
        style = MaterialTheme.typography.headlineMedium,
        modifier = Modifier.padding(start = 22.dp, end = 22.dp, top = 22.dp, bottom = 12.dp),
    )
}

@Composable
private fun DrawerHint(text: String) {
    Text(
        text,
        color = WatchPalette.Muted,
        style = MaterialTheme.typography.bodySmall,
        modifier = Modifier.padding(horizontal = 22.dp, vertical = 8.dp),
    )
}

@Composable
private fun DrawerHeader(text: String) {
    Text(
        text,
        color = WatchPalette.Up,
        fontSize = 13.sp,
        modifier = Modifier.padding(start = 22.dp, end = 22.dp, top = 16.dp, bottom = 6.dp),
    )
}

@Composable
private fun DrawerRow(
    title: String,
    subtitle: String? = null,
    toggle: Boolean? = null,
    danger: Boolean = false,
    modifier: Modifier = Modifier,
    onClick: () -> Unit,
) {
    WatchHotBox(
        selected = false,
        onClick = onClick,
        modifier = modifier.fillMaxWidth().padding(horizontal = 10.dp, vertical = 2.dp),
        chrome = WatchChrome.Drawer,
    ) { hot ->
        Row(
            Modifier.fillMaxWidth(),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(3.dp)) {
                Text(
                    title,
                    color = when {
                        danger -> WatchPalette.Down
                        hot -> WatchPalette.Up
                        else -> WatchPalette.Text
                    },
                    fontSize = 16.sp,
                )
                if (subtitle != null) {
                    Text(subtitle, color = if (hot) WatchPalette.Up else WatchPalette.Muted, fontSize = 13.sp)
                }
            }
            if (toggle != null) {
                DrawerSwitch(toggle, hot)
            }
        }
    }
}

@Composable
private fun DrawerSwitch(on: Boolean, hot: Boolean) {
    Box(
        Modifier
            .width(42.dp)
            .height(24.dp)
            .clip(RoundedCornerShape(12.dp))
            .background(if (on) WatchPalette.Up else WatchPalette.Line),
        contentAlignment = if (on) Alignment.CenterEnd else Alignment.CenterStart,
    ) {
        Box(
            Modifier
                .padding(2.dp)
                .size(20.dp)
                .clip(CircleShape)
                .background(if (on) WatchPalette.Bg else if (hot) WatchPalette.Text else WatchPalette.Muted),
        )
    }
}

@Composable
private fun RootPage(viewModel: PortalViewModel, first: FocusRequester) {
    DrawerTitle("Settings")
    DrawerRow("General", modifier = Modifier.focusRequester(first)) {
        viewModel.openSettingsPage(SettingsPage.GENERAL)
    }
    DrawerRow("Playlists") { viewModel.openSettingsPage(SettingsPage.PLAYLISTS) }
    DrawerRow("EPG") { viewModel.openSettingsPage(SettingsPage.EPG) }
    DrawerRow("Appearance") { viewModel.openSettingsPage(SettingsPage.APPEARANCE) }
    DrawerRow("Playback") { viewModel.openSettingsPage(SettingsPage.PLAYBACK) }
    DrawerRow("Remote control") { viewModel.openSettingsPage(SettingsPage.REMOTE) }
    DrawerRow("Parental controls") { viewModel.openSettingsPage(SettingsPage.PARENTAL) }
    DrawerRow("Other") { viewModel.openSettingsPage(SettingsPage.OTHER) }
    DrawerRow("About") { viewModel.openSettingsPage(SettingsPage.ABOUT) }
}

@Composable
private fun GeneralPage(viewModel: PortalViewModel, prefs: com.iptvmonitor.player.data.AppSettings) {
    DrawerTitle("General")
    DrawerRow("Auto start app on boot", toggle = prefs.autoStartBoot) {
        viewModel.setPref { it.autoStartBoot = !it.autoStartBoot }
    }
    DrawerRow(
        "Auto start app on wake up from sleep mode",
        subtitle = "May not work on all devices.",
        toggle = prefs.autoStartWake,
    ) {
        viewModel.setPref { it.autoStartWake = !it.autoStartWake }
    }
    DrawerRow("Turn on last library on app start", toggle = prefs.autoOpenLast) {
        viewModel.applyAutoOpenLast(!prefs.autoOpenLast)
    }
    DrawerRow(
        "Switch to full screen on OK",
        subtitle = "On TV, OK currently keeps the preview. Turn this on to go cinema.",
        toggle = prefs.okOpensCinema,
    ) {
        viewModel.setPref { it.okOpensCinema = !it.okOpensCinema }
    }
    DrawerRow("Confirm exit by second press Back", toggle = prefs.confirmExit) {
        viewModel.setPref { it.confirmExit = !it.confirmExit }
    }
    DrawerRow(
        "User-Agent",
        subtitle = prefs.userAgent.ifBlank { "Not set · $STREAM_USER_AGENT" },
    ) {
        viewModel.openTextPrompt(
            title = "User-Agent",
            value = prefs.userAgent,
            hint = STREAM_USER_AGENT,
        ) { ua ->
            viewModel.setPref { it.userAgent = ua }
        }
    }
}

@Composable
private fun PlaylistsPage(viewModel: PortalViewModel) {
    DrawerTitle("Playlists")
    viewModel.playlists.forEach { item ->
        val live = if (item.id == viewModel.liveSourceId() || (viewModel.liveSourceId() == null && item.id == viewModel.selectedPlaylist?.id)) {
            " · live source"
        } else {
            ""
        }
        DrawerRow(
            item.name,
            subtitle = playlistCounts(viewModel, item) + live,
        ) {
            viewModel.openPlaylistSettings(item)
        }
    }
    DrawerRow("Add playlist") { viewModel.startAddPlaylist() }
    DrawerRow("Update all playlists") { viewModel.syncAllPlaylists() }
    DrawerRow(
        "Live source",
        subtitle = viewModel.playlists.firstOrNull { it.id == viewModel.liveSourceId() }?.name ?: "Same as the playlist you open",
    ) {
        viewModel.cycleLiveSource()
    }
    DrawerRow(
        "Movies & shows source",
        subtitle = viewModel.playlists.firstOrNull { it.id == viewModel.vodSourceId() }?.name ?: "Same as the playlist you open",
    ) {
        viewModel.cycleVodSource()
    }
}

@Composable
private fun PlaylistDetailPage(viewModel: PortalViewModel, prefs: com.iptvmonitor.player.data.AppSettings) {
    val item = viewModel.settingsPlaylist ?: return
    DrawerTitle(item.name)
    DrawerRow("Catch-up", subtitle = if (item.kind == PlaylistKind.XTREAM) "Timeshift from the EPG (past programmes)" else "Not available on M3U") {
        if (item.kind == PlaylistKind.XTREAM) {
            viewModel.error = "Open a past programme in the guide to play catch-up."
        }
    }
    DrawerRow("User-Agent", subtitle = prefs.userAgent.ifBlank { "Not set" }) {
        viewModel.openTextPrompt("User-Agent", prefs.userAgent, STREAM_USER_AGENT) { ua ->
            viewModel.setPref { it.userAgent = ua }
        }
    }
    DrawerRow("Manage groups") {
        viewModel.openGroupEditor(item)
        viewModel.openSettingsPage(SettingsPage.GROUPS)
    }
    DrawerHeader("Update options")
    DrawerRow("Update interval, hours", subtitle = hourLabel(prefs.playlistUpdateHours)) {
        viewModel.openChoice(
            "Update interval, hours",
            HOUR_CHOICES,
            prefs.playlistUpdateHours.toString(),
        ) { key ->
            viewModel.setPref { it.playlistUpdateHours = key.toInt() }
        }
    }
    DrawerRow("Update on app start", toggle = prefs.playlistUpdateOnStart) {
        viewModel.setPref { it.playlistUpdateOnStart = !it.playlistUpdateOnStart }
    }
    DrawerRow("Update playlist") { viewModel.syncPlaylist(item) }
    DrawerRow("Edit playlist") { viewModel.startEditPlaylist(item) }
    DrawerRow("Delete playlist", danger = true) {
        viewModel.deletePlaylist(item.id)
        viewModel.openSettingsPage(SettingsPage.PLAYLISTS)
    }
}

@Composable
private fun GroupsPage(viewModel: PortalViewModel) {
    DrawerTitle("Manage groups")
    DrawerRow("Deselect all") { viewModel.setAllGroupsHidden(true) }
    DrawerRow("Select all") { viewModel.setAllGroupsHidden(false) }
    DrawerRow(
        "Show newly added groups",
        subtitle = "Hidden groups stay hidden after a sync.",
        toggle = true,
    ) {}
    if (viewModel.groupEditorLoading) {
        DrawerHint("Loading groups…")
    } else {
        DrawerHeader("Groups")
        groupToggles("Live", viewModel.groupEditorLive, viewModel.hiddenLiveDraft) {
            viewModel.hiddenLiveDraft = it
            persistGroups(viewModel)
        }
        groupToggles("Movies", viewModel.groupEditorMovies, viewModel.hiddenMovieDraft) {
            viewModel.hiddenMovieDraft = it
            persistGroups(viewModel)
        }
        groupToggles("Shows", viewModel.groupEditorShows, viewModel.hiddenShowDraft) {
            viewModel.hiddenShowDraft = it
            persistGroups(viewModel)
        }
    }
}

@Composable
private fun groupToggles(
    title: String,
    categories: List<com.iptvmonitor.player.data.Category>,
    hidden: Set<String>,
    onChange: (Set<String>) -> Unit,
) {
    if (categories.isEmpty()) return
    DrawerHeader(title)
    categories.forEach { cat ->
        val shown = cat.id !in hidden
        DrawerRow(cat.name, toggle = shown) {
            onChange(if (shown) hidden + cat.id else hidden - cat.id)
        }
    }
}

@Composable
private fun EpgPage(viewModel: PortalViewModel, prefs: com.iptvmonitor.player.data.AppSettings) {
    DrawerTitle("EPG")
    DrawerRow("EPG sources") { viewModel.openSettingsPage(SettingsPage.EPG_SOURCES) }
    DrawerRow("Past days to keep EPG", subtitle = "${prefs.epgPastDays} day${if (prefs.epgPastDays == 1) "" else "s"}") {
        viewModel.openChoice(
            "Past days to keep EPG",
            DAY_CHOICES,
            prefs.epgPastDays.toString(),
        ) { key ->
            viewModel.setPref { it.epgPastDays = key.toInt() }
        }
    }
    DrawerRow("Store program descriptions", toggle = prefs.storeEpgDescriptions) {
        viewModel.setPref { it.storeEpgDescriptions = !it.storeEpgDescriptions }
    }
    DrawerHeader("Update options")
    DrawerRow("Update interval, hours", subtitle = hourLabel(prefs.epgUpdateHours)) {
        viewModel.openChoice(
            "Update interval, hours",
            HOUR_CHOICES,
            prefs.epgUpdateHours.toString(),
        ) { key ->
            viewModel.setPref { it.epgUpdateHours = key.toInt() }
        }
    }
    DrawerRow("Update on app start", toggle = prefs.epgUpdateOnStart) {
        viewModel.setPref { it.epgUpdateOnStart = !it.epgUpdateOnStart }
    }
    DrawerRow("Update on playlists change", toggle = prefs.epgUpdateOnPlaylistChange) {
        viewModel.setPref { it.epgUpdateOnPlaylistChange = !it.epgUpdateOnPlaylistChange }
    }
    DrawerRow("Update EPG") { viewModel.requestEpgUpdate() }
    if (viewModel.guideSync.running && viewModel.guideSync.kind == "epg") {
        DrawerRow("Cancel EPG sync") { viewModel.cancelEpg() }
        DrawerRow("Restart EPG sync") { viewModel.restartEpg() }
    } else {
        DrawerRow("Restart EPG sync") { viewModel.restartEpg() }
    }
    DrawerRow("Clear EPG") { viewModel.clearEpg() }
    DrawerHeader("Latest update status")
    DrawerHint(prefs.lastEpgStatus.ifBlank { "EPG has not been updated yet." })
}

@Composable
private fun EpgSourcesPage(viewModel: PortalViewModel, prefs: com.iptvmonitor.player.data.AppSettings) {
    DrawerTitle("EPG sources")
    viewModel.playlists.forEach { item ->
        val url = viewModel.epgUrlPreview(item)
        DrawerRow(item.name, subtitle = url.ifBlank { "No EPG URL" }) {
            if (item.kind == PlaylistKind.M3U) {
                viewModel.startEditPlaylist(item)
            }
        }
    }
    if (prefs.extraEpgUrl.isNotBlank()) {
        DrawerRow("Extra source", subtitle = prefs.extraEpgUrl) {
            viewModel.openTextPrompt("EPG URL", prefs.extraEpgUrl, "https://…") { url ->
                viewModel.setPref { it.extraEpgUrl = url }
            }
        }
    }
    DrawerRow("Add source") {
        viewModel.openTextPrompt("EPG URL", prefs.extraEpgUrl, "https://example.com/xmltv.xml") { url ->
            viewModel.setPref { it.extraEpgUrl = url }
        }
    }
    DrawerHint("EPG sources should be assigned in the playlist settings.")
}

@Composable
private fun AppearancePage(viewModel: PortalViewModel, prefs: com.iptvmonitor.player.data.AppSettings) {
    DrawerTitle("Appearance")
    DrawerHint("Theme stays RootsIPTV: mint on charcoal. Type uses the system TV sans-serif (Roboto on Shield), same family as TiviMate.")
    DrawerRow("Theme", subtitle = "RootsIPTV / Watch") {}
    DrawerRow("Show sync status at top", toggle = prefs.showSyncBar) {
        viewModel.setPref { it.showSyncBar = !it.showSyncBar }
    }
}

@Composable
private fun PlaybackPage(viewModel: PortalViewModel, prefs: com.iptvmonitor.player.data.AppSettings) {
    DrawerTitle("Playback")
    DrawerRow("Buffer size", subtitle = viewModel.bufferProfile.label) {
        viewModel.openChoice(
            "Buffer size",
            BufferProfile.entries.map { it.key to it.label },
            viewModel.bufferProfile.key,
        ) { key ->
            viewModel.applyBufferProfile(BufferProfile.fromKey(key))
        }
    }
    DrawerRow("Audio decoder", subtitle = if (prefs.hardwareAudio) "Hardware" else "Software") {
        viewModel.openChoice(
            "Audio decoder",
            listOf("hw" to "Hardware", "sw" to "Software"),
            if (prefs.hardwareAudio) "hw" else "sw",
        ) { key ->
            viewModel.setPref { it.hardwareAudio = key == "hw" }
        }
    }
    DrawerRow("Video decoder", subtitle = if (prefs.hardwareVideo) "Hardware" else "Software") {
        viewModel.openChoice(
            "Video decoder",
            listOf("hw" to "Hardware", "sw" to "Software"),
            if (prefs.hardwareVideo) "hw" else "sw",
        ) { key ->
            viewModel.setPref { it.hardwareVideo = key == "hw" }
        }
    }
    DrawerRow("Auto frame rate (AFR)", subtitle = if (prefs.afrEnabled) "On" else "Off") {
        viewModel.openSettingsPage(SettingsPage.AFR)
    }
    DrawerRow("Select surround audio track by default", toggle = prefs.surroundDefault) {
        viewModel.setPref { it.surroundDefault = !it.surroundDefault }
    }
    DrawerRow("Audio passthrough", toggle = prefs.audioPassthrough) {
        viewModel.setPref { it.audioPassthrough = !it.audioPassthrough }
    }
    DrawerRow("Tunneled playback", toggle = prefs.tunneledPlayback) {
        viewModel.setPref { it.tunneledPlayback = !it.tunneledPlayback }
    }
    DrawerRow("VOD") { viewModel.openSettingsPage(SettingsPage.VOD) }
}

@Composable
private fun AfrPage(viewModel: PortalViewModel, prefs: com.iptvmonitor.player.data.AppSettings) {
    DrawerTitle("Auto frame rate (AFR)")
    DrawerRow("Enable AFR", toggle = prefs.afrEnabled) {
        viewModel.setPref {
            it.afrEnabled = !it.afrEnabled
            if (it.afrEnabled && !it.afrForTv && !it.afrForVod) it.afrForTv = true
        }
    }
    DrawerRow("Enable for TV", toggle = prefs.afrForTv) {
        viewModel.setPref {
            it.afrForTv = !it.afrForTv
            it.afrEnabled = it.afrForTv || it.afrForVod
        }
    }
    DrawerRow("Enable for VOD", toggle = prefs.afrForVod) {
        viewModel.setPref {
            it.afrForVod = !it.afrForVod
            it.afrEnabled = it.afrForTv || it.afrForVod
        }
    }
    DrawerRow("Switch screen refresh rate", toggle = prefs.afrSwitchRefresh) {
        viewModel.setPref { it.afrSwitchRefresh = !it.afrSwitchRefresh }
    }
    DrawerRow("Switch rate for 50/60 FPS only", toggle = prefs.afrOnly5060) {
        viewModel.setPref { it.afrOnly5060 = !it.afrOnly5060 }
    }
    DrawerRow("Switch screen resolution", toggle = prefs.afrSwitchResolution) {
        viewModel.setPref { it.afrSwitchResolution = !it.afrSwitchResolution }
    }
    DrawerRow("Delay before switching, sec", subtitle = "${prefs.afrDelaySec}s") {
        viewModel.openChoice(
            "Delay before switching",
            (0..5).map { it.toString() to if (it == 0) "0 sec" else "$it sec" },
            prefs.afrDelaySec.toString(),
        ) { key ->
            viewModel.setPref { it.afrDelaySec = key.toInt() }
        }
    }
    DrawerHint("Turn on this setting to switch TV refresh rate to match the video frame rate. This can make playback more smooth. Note that not all devices support auto frame rate.")
}

@Composable
private fun VodPage(viewModel: PortalViewModel, prefs: com.iptvmonitor.player.data.AppSettings) {
    DrawerTitle("VOD")
    DrawerRow("Autoplay next episode", toggle = prefs.autoplayNextEpisode) {
        viewModel.setPref { it.autoplayNextEpisode = !it.autoplayNextEpisode }
    }
}

@Composable
private fun RemotePage(viewModel: PortalViewModel, prefs: com.iptvmonitor.player.data.AppSettings) {
    DrawerTitle("Remote control")
    DrawerRow("OK opens full screen", toggle = prefs.okOpensCinema) {
        viewModel.setPref { it.okOpensCinema = !it.okOpensCinema }
    }
    DrawerHint("D-pad moves focus. Back leaves full screen, then the guide, then playlists. Settings is this right-hand panel.")
}

@Composable
private fun ParentalPage(viewModel: PortalViewModel, prefs: com.iptvmonitor.player.data.AppSettings) {
    DrawerTitle("Parental controls")
    DrawerRow("Lock Settings", toggle = prefs.parentalEnabled) {
        if (prefs.parentalEnabled) {
            viewModel.setPref { it.parentalEnabled = false }
        } else {
            viewModel.openTextPrompt("Set PIN", "", "4–8 digits") { pin ->
                if (pin.filter { ch -> ch.isDigit() }.length >= 4) {
                    viewModel.setPref {
                        it.parentalPin = pin
                        it.parentalEnabled = true
                    }
                }
            }
        }
    }
    DrawerRow("Change PIN", subtitle = if (prefs.parentalPin.isBlank()) "Not set" else "Set") {
        viewModel.openTextPrompt("PIN", "", "4–8 digits") { pin ->
            viewModel.setPref { it.parentalPin = pin }
        }
    }
    DrawerHint("When lock is on, opening Settings asks for the PIN. Channel groups can still be hidden under Playlists.")
}

@Composable
private fun OtherPage(viewModel: PortalViewModel, prefs: com.iptvmonitor.player.data.AppSettings) {
    DrawerTitle("Other")
    DrawerRow("UDP proxy (address:port)", subtitle = prefs.udpProxy.ifBlank { "Not set" }) {
        viewModel.openTextPrompt("UDP proxy", prefs.udpProxy, "192.168.1.10:4022") { value ->
            viewModel.setPref { it.udpProxy = value }
        }
    }
    DrawerRow("Back up data") {
        val path = viewModel.exportBackup()
        viewModel.error = "Backup saved to $path"
    }
    DrawerHint("Playlists stay on this device in encrypted storage. Backup writes a JSON copy under the app Documents folder.")
}

@Composable
private fun AboutPage() {
    DrawerTitle("About")
    DrawerRow("ROOTSIPTV", subtitle = "${BuildConfig.VERSION_NAME} (${BuildConfig.VERSION_CODE})") {}
    DrawerHint("RootsIPTV layout on Shield / Android TV. Streams go straight to your portal.")
}

@Composable
fun SettingsTextPrompt(viewModel: PortalViewModel) {
    val prompt = viewModel.textPrompt ?: return
    var text by remember(prompt.title, prompt.value) { mutableStateOf(prompt.value) }
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
    val pin = prompt.title.contains("PIN", ignoreCase = true)
    OverlayHost(onDismiss = { viewModel.closeTextPrompt() }, dismissOnScrim = false) { requester ->
        Column(
            Modifier
                .widthIn(max = 480.dp)
                .fillMaxWidth()
                .background(WatchPalette.Panel)
                .border(1.dp, WatchPalette.Line)
                .padding(24.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            Text(prompt.title, color = WatchPalette.Text, style = MaterialTheme.typography.headlineSmall)
            OutlinedTextField(
                text,
                { text = it },
                label = { Text(prompt.hint) },
                singleLine = true,
                colors = colors,
                modifier = Modifier.fillMaxWidth().focusRequester(requester),
                visualTransformation = if (pin) PasswordVisualTransformation() else androidx.compose.ui.text.input.VisualTransformation.None,
            )
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                SwitchBtn("Save") {
                    prompt.onSave(text)
                    viewModel.closeTextPrompt()
                }
                GhostBtn("Cancel") { viewModel.closeTextPrompt() }
            }
        }
    }
}

@Composable
fun SettingsChoicePrompt(viewModel: PortalViewModel) {
    val prompt = viewModel.choicePrompt ?: return
    OverlayHost(onDismiss = { viewModel.closeChoice() }) { requester ->
        Column(
            Modifier
                .widthIn(max = 480.dp)
                .fillMaxWidth()
                .background(WatchPalette.Panel)
                .border(1.dp, WatchPalette.Line)
                .padding(20.dp),
            verticalArrangement = Arrangement.spacedBy(6.dp),
        ) {
            Text(
                prompt.title,
                color = WatchPalette.Text,
                style = MaterialTheme.typography.headlineSmall,
                modifier = Modifier.padding(bottom = 8.dp),
            )
            prompt.options.forEachIndexed { index, (key, label) ->
                DrawerRow(
                    title = label,
                    toggle = key == prompt.selectedKey,
                    modifier = if (index == 0) Modifier.focusRequester(requester) else Modifier,
                    onClick = {
                        prompt.onPick(key)
                        viewModel.closeChoice()
                    },
                )
            }
            GhostBtn("Cancel") { viewModel.closeChoice() }
        }
    }
}

private fun persistGroups(viewModel: PortalViewModel) {
    val playlist = viewModel.settingsPlaylist ?: viewModel.groupEditor ?: return
    viewModel.saveHiddenGroups(
        playlist,
        viewModel.hiddenLiveDraft.toList(),
        viewModel.hiddenMovieDraft.toList(),
        viewModel.hiddenShowDraft.toList(),
        close = false,
    )
}

private fun playlistCounts(viewModel: PortalViewModel, item: SavedPlaylist): String {
    if (viewModel.selectedPlaylist?.id == item.id || viewModel.liveSource?.id == item.id || viewModel.vodSource?.id == item.id) {
        val live = viewModel.catalog.live.size
        val movies = viewModel.catalog.movies.size
        val shows = viewModel.catalog.series.size
        return buildString {
            append("Channels: $live")
            if (movies > 0) append(", movies: $movies")
            if (shows > 0) append(", shows: $shows")
        }
    }
    return if (item.kind == PlaylistKind.XTREAM) "Xtream" else "M3U"
}

private val HOUR_CHOICES = listOf(1, 2, 4, 6, 8, 12, 24).map { key ->
    key.toString() to hourLabel(key)
}

private val DAY_CHOICES = (1..7).map { key ->
    key.toString() to if (key == 1) "1 day" else "$key days"
}

private fun hourLabel(hours: Int): String = when (hours) {
    1 -> "1 hour"
    else -> "$hours hours"
}
