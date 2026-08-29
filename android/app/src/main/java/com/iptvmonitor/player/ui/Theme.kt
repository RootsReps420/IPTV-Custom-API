package com.iptvmonitor.player.ui

import androidx.compose.material3.ColorScheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Typography
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.sp

/** Watch (styles.css :root) + TiviMate-like Roboto (platform SansSerif). */
object WatchPalette {
    val Bg = Color(0xFF07090D)
    val Panel = Color(0xFF10141C)
    val Panel2 = Color(0xFF161C27)
    val Line = Color(0xFF2A3A4D)
    val Text = Color(0xFFEEF3F8)
    val Muted = Color(0xFFA9B6C7)
    val Up = Color(0xFF7DFFC3)
    val Down = Color(0xFFFF6B6B)
    val Warn = Color(0xFFF0C14A)
    val Preview = Color(0xFF05070B)
    val Rail = Color(0xFF0B0E14)
    val Stage = Color(0xFF080A0F)
    val LiveRed = Color(0xFFC81E1E)
    val NowLine = Color(0xFF3D5368)
    val Hover10 = Color(0x1A7DFFC3)
    val Hover12 = Color(0x1F7DFFC3)
    val Hover16 = Color(0x297DFFC3)
    val Hover22 = Color(0x387DFFC3)
    val Hover04 = Color(0x0A7DFFC3)
    val Selected = Hover12
}

val PortalDarkColors: ColorScheme = darkColorScheme(
    primary = WatchPalette.Up,
    onPrimary = Color(0xFF07090D),
    background = WatchPalette.Bg,
    onBackground = WatchPalette.Text,
    surface = WatchPalette.Panel,
    onSurface = WatchPalette.Text,
    surfaceVariant = WatchPalette.Panel2,
    onSurfaceVariant = WatchPalette.Muted,
    outline = WatchPalette.Line,
    error = WatchPalette.Down,
)

private val TvSans = FontFamily.SansSerif

private val WatchTypography = Typography(
    headlineLarge = TextStyle(
        fontFamily = TvSans,
        fontWeight = FontWeight.Bold,
        fontSize = 28.sp,
        color = WatchPalette.Text,
    ),
    headlineMedium = TextStyle(
        fontFamily = TvSans,
        fontWeight = FontWeight.Bold,
        fontSize = 22.sp,
        color = WatchPalette.Text,
    ),
    headlineSmall = TextStyle(
        fontFamily = TvSans,
        fontWeight = FontWeight.SemiBold,
        fontSize = 18.sp,
        color = WatchPalette.Text,
    ),
    titleMedium = TextStyle(
        fontFamily = TvSans,
        fontWeight = FontWeight.Medium,
        fontSize = 16.sp,
        color = WatchPalette.Text,
    ),
    bodyLarge = TextStyle(
        fontFamily = TvSans,
        fontWeight = FontWeight.Normal,
        fontSize = 15.sp,
        color = WatchPalette.Text,
    ),
    bodyMedium = TextStyle(
        fontFamily = TvSans,
        fontWeight = FontWeight.Normal,
        fontSize = 14.sp,
        color = WatchPalette.Text,
    ),
    bodySmall = TextStyle(
        fontFamily = TvSans,
        fontWeight = FontWeight.Normal,
        fontSize = 12.sp,
        color = WatchPalette.Muted,
    ),
    labelLarge = TextStyle(
        fontFamily = TvSans,
        fontWeight = FontWeight.Medium,
        fontSize = 12.sp,
        letterSpacing = 0.8.sp,
        color = WatchPalette.Muted,
    ),
    labelSmall = TextStyle(
        fontFamily = TvSans,
        fontWeight = FontWeight.Normal,
        fontSize = 11.sp,
        letterSpacing = 0.4.sp,
        color = WatchPalette.Muted,
    ),
)

@Composable
fun PortalTheme(content: @Composable () -> Unit) {
    MaterialTheme(
        colorScheme = PortalDarkColors,
        typography = WatchTypography,
        content = content,
    )
}
