package com.iptvmonitor.player.ui

import androidx.compose.foundation.border
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.focus.onFocusChanged
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp

/** Visible D-pad focus ring for Shield / Leanback. */
@Composable
fun Modifier.tvFocusBorder(): Modifier {
    var focused by remember { mutableStateOf(false) }
    return this
        .onFocusChanged { focused = it.isFocused }
        .border(
            width = if (focused) 3.dp else 0.dp,
            color = if (focused) Color(0xFF7AB8C8) else Color.Transparent,
            shape = RoundedCornerShape(12.dp),
        )
}
