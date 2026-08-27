package com.iptvmonitor.player

import android.content.res.Configuration
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
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.ui.Modifier
import com.iptvmonitor.player.ui.AppScreen
import com.iptvmonitor.player.ui.HomeScreen
import com.iptvmonitor.player.ui.PlayerScreen
import com.iptvmonitor.player.ui.PortalTheme
import com.iptvmonitor.player.ui.PortalViewModel
import com.iptvmonitor.player.ui.SettingsScreen
import com.iptvmonitor.player.ui.WatchShell

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
    LaunchedEffect(viewModel.playing?.url, viewModel.playing?.live) {
        val target = viewModel.playing
        if (target != null) {
            viewModel.session.play(target.url, target.live)
        }
    }

    BackHandler(enabled = viewModel.cinema) {
        viewModel.showCinema(false)
    }
    BackHandler(enabled = !viewModel.cinema && viewModel.seriesDetail != null) {
        viewModel.seriesDetail = null
    }
    BackHandler(enabled = !viewModel.cinema && viewModel.seriesDetail == null && viewModel.screen == AppScreen.SETTINGS) {
        viewModel.backFromSettings()
    }
    BackHandler(enabled = !viewModel.cinema && viewModel.seriesDetail == null && viewModel.screen == AppScreen.LIBRARY) {
        viewModel.closeLibrary()
    }

    when {
        viewModel.screen == AppScreen.HOME -> HomeScreen(viewModel)
        viewModel.screen == AppScreen.SETTINGS && viewModel.selectedPlaylist == null -> SettingsScreen(viewModel)
        else -> {
            Box(Modifier.fillMaxSize()) {
                WatchShell(viewModel, showPlayer = !viewModel.cinema)
                if (viewModel.screen == AppScreen.SETTINGS) {
                    SettingsScreen(viewModel)
                }
                if (viewModel.cinema && viewModel.playing != null) {
                    PlayerScreen(viewModel)
                }
            }
        }
    }
}
