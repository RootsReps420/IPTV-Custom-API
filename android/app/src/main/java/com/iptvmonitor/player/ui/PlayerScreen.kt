package com.iptvmonitor.player.ui

import android.app.Activity
import android.view.View
import android.view.WindowManager
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.gestures.detectTapGestures
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
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.key
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusProperties
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.LocalView
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.media3.ui.PlayerView
import com.iptvmonitor.player.data.EpgEvent
import kotlinx.coroutines.delay

@Composable
fun PlayerScreen(viewModel: PortalViewModel) {
    val target = viewModel.playing ?: return
    val view = LocalView.current
    val ui = viewModel.liveUi
    val live = target.live
    var chrome by remember(target.url) { mutableStateOf(true) }
    val backFocus = remember { FocusRequester() }
    val catcher = remember { FocusRequester() }
    DisposableEffect(Unit) {
        val window = (view.context as? Activity)?.window
        window?.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        onDispose { window?.clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON) }
    }
    LaunchedEffect(chrome, target.url, target.title) {
        if (!chrome) return@LaunchedEffect
        delay(3_500)
        chrome = false
    }
    LaunchedEffect(chrome, target.url) {
        delay(80)
        runCatching {
            if (chrome) backFocus.requestFocus() else catcher.requestFocus()
        }
    }
    Box(
        Modifier
            .fillMaxSize()
            .background(Color.Black)
            .then(
                if (chrome) {
                    Modifier.pointerInput(Unit) { detectTapGestures { chrome = false } }
                } else {
                    Modifier
                        .focusRequester(catcher)
                        .clickable { chrome = true }
                },
            ),
    ) {
        key(target.url, live) {
        AndroidView(
            factory = { ctx ->
                PlayerView(ctx).apply {
                    player = viewModel.session.player
                    useController = !live
                    setShowNextButton(false)
                    setShowPreviousButton(false)
                    setShowRewindButton(!live)
                    setShowFastForwardButton(!live)
                    controllerAutoShow = !live
                    controllerHideOnTouch = true
                    setShowBuffering(PlayerView.SHOW_BUFFERING_NEVER)
                    if (live) {
                        hideController()
                        blockDpad()
                        addOnAttachStateChangeListener(
                            object : View.OnAttachStateChangeListener {
                                override fun onViewAttachedToWindow(v: View) {
                                    (v as? PlayerView)?.blockDpad()
                                }
                                override fun onViewDetachedFromWindow(v: View) = Unit
                            },
                        )
                    }
                }
            },
            update = { playerView ->
                playerView.player = viewModel.session.player
                playerView.useController = !live
                if (live) {
                    playerView.hideController()
                    playerView.blockDpad()
                }
            },
            modifier = Modifier
                .fillMaxSize()
                .then(if (live) Modifier.focusProperties { canFocus = false } else Modifier),
        )
        }
        if (chrome) {
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
                    Text(
                        target.title,
                        color = Color.White,
                        style = androidx.compose.material3.MaterialTheme.typography.titleMedium,
                    )
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        if (live && ui.badge.isNotBlank()) {
                            Text(
                                ui.badge,
                                color = if (ui.buffering || ui.reconnecting || ui.gaveUp) {
                                    WatchPalette.Warn
                                } else {
                                    WatchPalette.Up
                                },
                                modifier = Modifier.padding(end = 12.dp),
                            )
                        }
                        BoxChip("Back", selected = false, modifier = Modifier.focusRequester(backFocus)) {
                            viewModel.showCinema(false)
                        }
                    }
                }
                if (live) {
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
