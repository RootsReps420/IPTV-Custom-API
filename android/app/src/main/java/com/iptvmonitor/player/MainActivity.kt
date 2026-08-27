package com.iptvmonitor.player

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.BackHandler
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.viewModels
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material3.Surface
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import com.iptvmonitor.player.ui.BrowseScreen
import com.iptvmonitor.player.ui.PlayerScreen
import com.iptvmonitor.player.ui.PlaylistListScreen
import com.iptvmonitor.player.ui.PortalTheme
import com.iptvmonitor.player.ui.PortalViewModel

class MainActivity : ComponentActivity() {
    private val viewModel: PortalViewModel by viewModels()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
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
    BackHandler(enabled = viewModel.playing != null) {
        viewModel.stopPlayback()
    }
    BackHandler(enabled = viewModel.playing == null && viewModel.seriesDetail != null) {
        viewModel.seriesDetail = null
    }
    BackHandler(enabled = viewModel.playing == null && viewModel.seriesDetail == null && viewModel.selectedPlaylist != null) {
        viewModel.closePlaylist()
    }

    when {
        viewModel.playing != null -> PlayerScreen(viewModel)
        viewModel.selectedPlaylist != null -> BrowseScreen(viewModel)
        else -> PlaylistListScreen(viewModel, onOpen = { viewModel.openPlaylist(it) })
    }
}
