package com.iptvmonitor.player.ui

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.focusGroup
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxScope
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusProperties
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import kotlinx.coroutines.delay

@Composable
fun FocusDialog(
    onDismiss: () -> Unit,
    content: @Composable BoxScope.(FocusRequester) -> Unit,
) {
    val requester = remember { FocusRequester() }
    Dialog(
        onDismissRequest = onDismiss,
        properties = DialogProperties(
            usePlatformDefaultWidth = false,
            dismissOnClickOutside = false,
            dismissOnBackPress = true,
        ),
    ) {
        LaunchedEffect(Unit) {
            delay(200)
            runCatching { requester.requestFocus() }
        }
        Box(
            Modifier
                .fillMaxSize()
                .background(WatchPalette.Bg.copy(alpha = 0.72f))
                .focusGroup(),
            contentAlignment = Alignment.Center,
        ) {
            content(requester)
        }
    }
}

/** In-tree overlay so the library underneath can be un-focused. */
@Composable
fun OverlayHost(
    onDismiss: () -> Unit,
    alignment: Alignment = Alignment.Center,
    dismissOnScrim: Boolean = true,
    content: @Composable BoxScope.(FocusRequester) -> Unit,
) {
    val requester = remember { FocusRequester() }
    val scrimClicks = remember { MutableInteractionSource() }
    val panelClicks = remember { MutableInteractionSource() }
    BackHandler(onBack = onDismiss)
    LaunchedEffect(Unit) {
        delay(200)
        runCatching { requester.requestFocus() }
    }
    Box(
        Modifier
            .fillMaxSize()
            .background(WatchPalette.Bg.copy(alpha = 0.62f))
            .clickable(
                interactionSource = scrimClicks,
                indication = null,
                onClick = { if (dismissOnScrim) onDismiss() },
            )
            .focusGroup(),
        contentAlignment = alignment,
    ) {
        Box(
            Modifier
                .clickable(
                    interactionSource = panelClicks,
                    indication = null,
                    onClick = {},
                )
                .focusProperties { canFocus = false },
        ) {
            content(requester)
        }
    }
}
