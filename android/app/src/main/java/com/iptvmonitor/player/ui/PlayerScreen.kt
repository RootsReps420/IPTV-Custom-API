package com.iptvmonitor.player.ui

import android.app.Activity
import android.view.WindowManager
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalView
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.media3.ui.PlayerView
import com.iptvmonitor.player.data.EpgEvent

@Composable
fun PlayerScreen(viewModel: PortalViewModel) {
    val target = viewModel.playing ?: return
    val view = LocalView.current
    val ui = viewModel.liveUi
    DisposableEffect(Unit) {
        val window = (view.context as? Activity)?.window
        window?.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        onDispose { window?.clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON) }
    }
    Box(Modifier.fillMaxSize().background(Color.Black)) {
        AndroidView(
            factory = { ctx ->
                PlayerView(ctx).apply {
                    player = viewModel.session.player
                    useController = !target.live
                    setShowNextButton(false)
                    setShowPreviousButton(false)
                    setShowRewindButton(!target.live)
                    setShowFastForwardButton(!target.live)
                    controllerAutoShow = true
                    controllerHideOnTouch = true
                    setShowBuffering(PlayerView.SHOW_BUFFERING_NEVER)
                }
            },
            update = { playerView ->
                playerView.player = viewModel.session.player
                playerView.useController = !target.live
            },
            modifier = Modifier.fillMaxSize(),
        )
        Column(
            Modifier
                .align(Alignment.TopStart)
                .fillMaxWidth()
                .background(Color(0x99000000))
                .padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(4.dp),
        ) {
            Row(
                Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text(target.title, color = Color.White, style = androidx.compose.material3.MaterialTheme.typography.titleMedium)
                Row(verticalAlignment = Alignment.CenterVertically) {
                    if (target.live && ui.badge.isNotBlank()) {
                        Text(
                            ui.badge,
                            color = if (ui.buffering || ui.reconnecting || ui.gaveUp) WatchPalette.Warn else WatchPalette.Up,
                            modifier = Modifier.padding(end = 12.dp),
                        )
                    }
                    BoxChip("Back", selected = false) { viewModel.showCinema(false) }
                }
            }
            if (target.live) {
                CinemaEpg(viewModel.liveEpg)
            }
            if (ui.message.isNotBlank()) {
                Text(ui.message, color = WatchPalette.Down)
            }
            if (ui.gaveUp) {
                BoxChip("Retry", selected = false) { viewModel.session.retry() }
            }
        }
    }
}

@Composable
private fun CinemaEpg(events: List<EpgEvent>) {
    val now = events.firstOrNull { it.isNow } ?: events.firstOrNull() ?: return
    val next = events.firstOrNull { it.startMs >= now.endMs }
    val text = buildString {
        append(formatEpgTime(now))
        append("  ")
        append(now.title)
        if (next != null) {
            append("   · next ")
            append(next.title)
        }
    }
    Text(text, color = WatchPalette.Muted)
}
