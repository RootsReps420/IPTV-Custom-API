package com.iptvmonitor.player.ui

import androidx.compose.material3.ColorScheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color

private val Bg = Color(0xFF12141A)
private val Surface = Color(0xFF1A1D26)
private val Accent = Color(0xFF7AB8C8)
private val Text = Color(0xFFE8EAED)
private val Muted = Color(0xFF9AA0A6)

val PortalDarkColors: ColorScheme = darkColorScheme(
    primary = Accent,
    onPrimary = Color(0xFF0B0D12),
    background = Bg,
    onBackground = Text,
    surface = Surface,
    onSurface = Text,
    surfaceVariant = Color(0xFF242833),
    onSurfaceVariant = Muted,
    error = Color(0xFFE57373),
)

@Composable
fun PortalTheme(content: @Composable () -> Unit) {
    MaterialTheme(colorScheme = PortalDarkColors, content = content)
}
