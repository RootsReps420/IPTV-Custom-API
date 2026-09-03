package com.iptvmonitor.player

import android.app.Activity
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.content.res.Configuration
import android.os.Build
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.BackHandler
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.viewModels
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material3.Surface
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.input.key.KeyEventType
import androidx.compose.ui.input.key.onPreviewKeyEvent
import androidx.compose.ui.input.key.type
import androidx.compose.ui.platform.LocalContext
import com.iptvmonitor.player.player.AfrController
import com.iptvmonitor.player.player.RecordService
import com.iptvmonitor.player.ui.AppScreen
import com.iptvmonitor.player.ui.GroupEditorOverlay
import com.iptvmonitor.player.ui.GroupMenuOverlay
import com.iptvmonitor.player.ui.HomeScreen
import com.iptvmonitor.player.ui.ItemMenuOverlay
import com.iptvmonitor.player.ui.LocalInputGated
import com.iptvmonitor.player.ui.LocalShellFocusable
import com.iptvmonitor.player.ui.PlayerScreen
import com.iptvmonitor.player.ui.PlaylistEditorOverlay
import com.iptvmonitor.player.ui.PortalTheme
import com.iptvmonitor.player.ui.PortalViewModel
import com.iptvmonitor.player.ui.SettingsChoicePrompt
import com.iptvmonitor.player.ui.SettingsDrawer
import com.iptvmonitor.player.ui.SettingsTextPrompt
import com.iptvmonitor.player.ui.WatchShell
import com.iptvmonitor.player.ui.isConfirmKey
import kotlinx.coroutines.delay

class MainActivity : ComponentActivity() {
    private val viewModel: PortalViewModel by viewModels()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val isTv = resources.configuration.uiMode and Configuration.UI_MODE_TYPE_MASK ==
            Configuration.UI_MODE_TYPE_TELEVISION
        if (!isTv) enableEdgeToEdge()
        setContent {
            PortalTheme {
                Surface(Modifier.fillMaxSize()) {
                    PortalRoot(viewModel)
                }
            }
        }
    }
}

@Composable
private fun PortalRoot(viewModel: PortalViewModel) {
    val activity = LocalContext.current as Activity
    var exitArmed by remember { mutableStateOf(false) }
    val ctx = LocalContext.current

    DisposableEffect(Unit) {
        val receiver = object : BroadcastReceiver() {
            override fun onReceive(context: Context?, intent: Intent?) {
                if (intent?.action != RecordService.ACTION_STATUS) return
                val running = intent.getBooleanExtra(RecordService.EXTRA_RUNNING, false)
                val message = intent.getStringExtra(RecordService.EXTRA_MESSAGE)
                if (!running) {
                    viewModel.onRecordingFinished(message)
                }
            }
        }
        val filter = IntentFilter(RecordService.ACTION_STATUS)
        if (Build.VERSION.SDK_INT >= 33) {
            ctx.registerReceiver(receiver, filter, Context.RECEIVER_NOT_EXPORTED)
        } else {
            ctx.registerReceiver(receiver, filter)
        }
        onDispose { runCatching { ctx.unregisterReceiver(receiver) } }
    }

    LaunchedEffect(viewModel.playing?.url, viewModel.playing?.live, viewModel.playerGen) {
        val target = viewModel.playing
        if (target != null) {
            viewModel.session.play(target.url, target.live)
        }
    }

    LaunchedEffect(
        viewModel.playing?.live,
        viewModel.liveUi.frameRate,
        viewModel.liveUi.width,
        viewModel.settingsRev,
        viewModel.cinema,
    ) {
        val prefs = viewModel.prefs()
        val playing = viewModel.playing
        if (playing == null || !prefs.afrEnabled) {
            AfrController.clear(activity)
            return@LaunchedEffect
        }
        val enabled = (playing.live && prefs.afrForTv) || (!playing.live && prefs.afrForVod)
        val fps = viewModel.liveUi.frameRate
        if (!enabled || !prefs.afrSwitchRefresh || fps <= 1f) {
            AfrController.clear(activity)
            return@LaunchedEffect
        }
        delay(prefs.afrDelaySec * 1000L)
        AfrController.apply(
            activity,
            fps,
            viewModel.liveUi.width,
            viewModel.liveUi.height,
            prefs.afrSwitchRefresh,
            prefs.afrSwitchResolution,
            prefs.afrOnly5060,
        )
    }

    LaunchedEffect(viewModel.screen) {
        if (viewModel.screen != AppScreen.HOME) exitArmed = false
    }

    BackHandler(enabled = viewModel.cinema) {
        viewModel.showCinema(false)
    }
    BackHandler(enabled = !viewModel.cinema && viewModel.seriesDetail != null) {
        viewModel.seriesDetail = null
    }
    BackHandler(
        enabled = !viewModel.cinema &&
            viewModel.seriesDetail == null &&
            viewModel.screen == AppScreen.LIBRARY &&
            viewModel.showPlaylistEditor.not() &&
            viewModel.groupEditor == null &&
            viewModel.textPrompt == null &&
            viewModel.choicePrompt == null &&
            viewModel.itemMenu == null &&
            viewModel.groupMenu == null,
    ) {
        if (!viewModel.popLane()) {
            AfrController.clear(activity)
            viewModel.closeLibrary()
        }
    }
    BackHandler(
        enabled = viewModel.screen == AppScreen.HOME &&
            viewModel.prefs().confirmExit &&
            !viewModel.showPlaylistEditor &&
            viewModel.textPrompt == null &&
            viewModel.choicePrompt == null &&
            viewModel.screen != AppScreen.SETTINGS,
    ) {
        if (!exitArmed) {
            exitArmed = true
            viewModel.error = "Press Back again to exit"
        } else {
            activity.finish()
        }
    }

    val blockBg = viewModel.blocksBackgroundFocus
    val cinema = viewModel.cinema && viewModel.playing != null
    CompositionLocalProvider(LocalInputGated provides viewModel.inputGated) {
        Box(
            Modifier
                .fillMaxSize()
                .then(
                    if (viewModel.inputGated) {
                        Modifier.onPreviewKeyEvent { ev ->
                            if (!isConfirmKey(ev.nativeKeyEvent.keyCode)) return@onPreviewKeyEvent false
                            if (ev.type == KeyEventType.KeyUp) viewModel.releaseInputGate()
                            true
                        }
                    } else {
                        Modifier
                    },
                ),
        ) {
            CompositionLocalProvider(LocalShellFocusable provides (!blockBg && !cinema)) {
                Box(Modifier.fillMaxSize()) {
                    when {
                        viewModel.selectedPlaylist == null -> HomeScreen(viewModel)
                        else -> WatchShell(viewModel, showPlayer = !cinema)
                    }
                }
            }

            if (cinema) {
                CompositionLocalProvider(LocalShellFocusable provides true) {
                    PlayerScreen(viewModel)
                }
            }

            if (viewModel.screen == AppScreen.SETTINGS) {
                val settingsFront = viewModel.choicePrompt == null &&
                    viewModel.textPrompt == null &&
                    viewModel.itemMenu == null &&
                    viewModel.groupMenu == null
                CompositionLocalProvider(LocalShellFocusable provides settingsFront) {
                    SettingsDrawer(viewModel)
                }
            }
            if (viewModel.showPlaylistEditor) {
                PlaylistEditorOverlay(
                    viewModel = viewModel,
                    initial = viewModel.playlistEditorInitial,
                    onDismiss = { viewModel.closePlaylistEditor() },
                    onSave = {
                        viewModel.savePlaylist(it)
                        viewModel.closePlaylistEditor()
                    },
                )
            }
            if (viewModel.groupEditor != null && viewModel.screen != AppScreen.SETTINGS) {
                val playlist = viewModel.groupEditor
                if (playlist != null) {
                    GroupEditorOverlay(
                        viewModel = viewModel,
                        playlist = playlist,
                        onDismiss = { viewModel.closeGroupEditor() },
                    )
                }
            }
            if (viewModel.textPrompt != null) {
                SettingsTextPrompt(viewModel)
            }
            if (viewModel.choicePrompt != null) {
                SettingsChoicePrompt(viewModel)
            }
            if (viewModel.itemMenu != null) {
                ItemMenuOverlay(viewModel)
            }
            if (viewModel.groupMenu != null) {
                GroupMenuOverlay(viewModel)
            }
        }
    }
}
