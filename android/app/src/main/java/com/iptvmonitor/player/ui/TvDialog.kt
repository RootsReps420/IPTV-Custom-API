package com.iptvmonitor.player.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.focusGroup
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxScope
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.focus.FocusRequester
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
            delay(80)
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
