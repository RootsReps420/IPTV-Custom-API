package com.iptvmonitor.player.ui

import androidx.annotation.OptIn
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import android.app.Activity
import android.view.WindowManager
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalView
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.media3.common.util.UnstableApi
import androidx.media3.ui.PlayerView
import com.iptvmonitor.player.data.EpgEvent
import com.iptvmonitor.player.player.LiveSession

@OptIn(UnstableApi::class)
@Composable
fun PlayerScreen(viewModel: PortalViewModel) {
    val target = viewModel.playing ?: return
    val context = LocalContext.current
    val view = LocalView.current
    DisposableEffect(Unit) {
        val window = (view.context as? Activity)?.window
        window?.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        onDispose { window?.clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON) }
    }
    var ui by remember { mutableStateOf(LiveSession.LiveUiState()) }
    val session = remember {
        LiveSession(context) { ui = it }
    }
    DisposableEffect(target.url, target.live) {
        session.play(target.url, target.live)
        onDispose { session.stop() }
    }
    DisposableEffect(Unit) {
        onDispose { session.release() }
    }

    Box(Modifier.fillMaxSize().background(Color.Black)) {
        AndroidView(
            factory = { ctx ->
                PlayerView(ctx).apply {
                    player = session.player
                    useController = !target.live
                    setShowNextButton(false)
                    setShowPreviousButton(false)
                    setShowRewindButton(!target.live)
                    setShowFastForwardButton(!target.live)
                    controllerAutoShow = true
                    controllerHideOnTouch = true
                }
            },
            update = { view ->
                view.player = session.player
                view.useController = !target.live
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
                Text(target.title, color = Color.White, style = MaterialTheme.typography.titleMedium)
                Row(verticalAlignment = Alignment.CenterVertically) {
                    if (target.live && ui.badge.isNotBlank()) {
                        Text(
                            ui.badge,
                            color = if (ui.buffering || ui.reconnecting || ui.gaveUp) Color(0xFFFFC107) else Color(0xFF7AB8C8),
                            modifier = Modifier.padding(end = 12.dp),
                            style = MaterialTheme.typography.labelLarge,
                        )
                    }
                    TextButton(onClick = { viewModel.stopPlayback() }) {
                        Text("Back", color = Color.White)
                    }
                }
            }
            if (target.live) {
                EpgLine(viewModel.liveEpg)
            }
            if (ui.message.isNotBlank()) {
                Text(ui.message, color = Color(0xFFFFCDD2), style = MaterialTheme.typography.bodySmall)
            }
            if (ui.gaveUp) {
                TextButton(onClick = { session.play(target.url, target.live) }) {
                    Text("Retry", color = Color.White)
                }
            }
        }
    }
}

@Composable
private fun EpgLine(events: List<EpgEvent>) {
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
    Text(text, color = Color(0xFFB0BEC5), style = MaterialTheme.typography.bodySmall)
}
