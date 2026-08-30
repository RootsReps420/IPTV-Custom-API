package com.iptvmonitor.player.ui

import androidx.compose.foundation.border
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.clickable
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.interaction.collectIsFocusedAsState
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxScope
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.compositionLocalOf
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.focus.focusProperties
import androidx.compose.ui.focus.onFocusChanged
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.RectangleShape
import androidx.compose.ui.graphics.Shape
import androidx.compose.ui.input.key.KeyEventType
import androidx.compose.ui.input.key.onPreviewKeyEvent
import androidx.compose.ui.input.key.type
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import android.view.KeyEvent as AndroidKeyEvent
import kotlin.math.max

val LocalWatchHot = compositionLocalOf { false }

/** True while an overlay has just opened so leftover OK/KeyUp does not click the first row. */
val LocalInputGated = compositionLocalOf { false }

/** False on the library/home tree while a modal is open so D-pad cannot land behind it. */
val LocalShellFocusable = compositionLocalOf { true }

@Composable
fun watchHot(): Boolean = LocalWatchHot.current

@Composable
fun watchInk(rest: Color = WatchPalette.Muted): Color =
    if (LocalWatchHot.current) WatchPalette.Up else rest

@Composable
fun watchWeight(rest: FontWeight = FontWeight.Normal): FontWeight =
    if (LocalWatchHot.current) FontWeight.Bold else rest

enum class WatchChrome {
    Item,
    Cat,
    Rail,
    Chip,
    Ghost,
    Accent,
    Danger,
    Drawer,
    Prog,
    EpgCh,
}

private fun WatchChrome.shape(): Shape = when (this) {
    WatchChrome.Item, WatchChrome.Cat, WatchChrome.Prog -> RoundedCornerShape(6.dp)
    WatchChrome.Ghost -> RoundedCornerShape(4.dp)
    WatchChrome.Drawer -> RoundedCornerShape(10.dp)
    else -> RectangleShape
}

private fun WatchChrome.pad(): PaddingValues = when (this) {
    WatchChrome.Item, WatchChrome.Cat -> PaddingValues(horizontal = 12.dp, vertical = 12.dp)
    WatchChrome.Rail -> PaddingValues(horizontal = 12.dp, vertical = 14.dp)
    WatchChrome.Chip -> PaddingValues(horizontal = 8.dp, vertical = 3.dp)
    WatchChrome.Ghost -> PaddingValues(horizontal = 10.dp, vertical = 8.dp)
    WatchChrome.Accent, WatchChrome.Danger -> PaddingValues(horizontal = 10.dp, vertical = 6.dp)
    WatchChrome.Drawer -> PaddingValues(horizontal = 16.dp, vertical = 14.dp)
    WatchChrome.Prog -> PaddingValues(horizontal = 8.dp, vertical = 4.dp)
    WatchChrome.EpgCh -> PaddingValues(start = 8.dp, end = 10.dp, top = 6.dp, bottom = 6.dp)
}

/** Outline for text fields and leftover controls. Lists use [WatchHotBox]. */
@Composable
fun Modifier.tvFocusBorder(): Modifier {
    var focused by remember { mutableStateOf(false) }
    return this
        .onFocusChanged { focused = it.isFocused }
        .border(
            width = if (focused) 1.dp else 0.dp,
            color = if (focused) WatchPalette.Up else Color.Transparent,
            shape = RoundedCornerShape(6.dp),
        )
}

@Composable
fun WatchBackdrop(content: @Composable () -> Unit) {
    Box(
        Modifier
            .fillMaxSize()
            .drawBehind {
                drawRect(WatchPalette.Bg)
                val step = 48.dp.toPx()
                val line = WatchPalette.Up.copy(alpha = 0.045f)
                var x = 0f
                while (x < size.width) {
                    drawLine(line, Offset(x, 0f), Offset(x, size.height), strokeWidth = 1f)
                    x += step
                }
                var y = 0f
                while (y < size.height) {
                    drawLine(line, Offset(0f, y), Offset(size.width, y), strokeWidth = 1f)
                    y += step
                }
                drawRect(
                    Brush.radialGradient(
                        colorStops = arrayOf(
                            0.22f to Color.Transparent,
                            0.75f to WatchPalette.Bg,
                        ),
                        center = Offset(size.width / 2f, 0f),
                        radius = max(size.width, size.height) * 0.9f,
                    ),
                )
            },
    ) {
        content()
    }
}

@OptIn(ExperimentalFoundationApi::class)
@Composable
fun WatchHotBox(
    selected: Boolean,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    chrome: WatchChrome = WatchChrome.Item,
    isNow: Boolean = false,
    contentPadding: PaddingValues? = null,
    contentAlignment: Alignment = Alignment.CenterStart,
    onLongClick: (() -> Unit)? = null,
    allowFocus: Boolean = true,
    onFocused: (() -> Unit)? = null,
    content: @Composable BoxScope.(hot: Boolean) -> Unit,
) {
    val interaction = remember { MutableInteractionSource() }
    val sourceFocused by interaction.collectIsFocusedAsState()
    var focused by remember { mutableStateOf(false) }
    var longPress by remember { mutableStateOf(false) }
    val gated = LocalInputGated.current
    val shellFocus = LocalShellFocusable.current
    val hot = selected || focused || sourceFocused
    val shape = chrome.shape()
    val fill = chromeFill(chrome, hot, isNow)
    val stroke = chromeStroke(chrome, hot, selected, isNow)
    val bar = when (chrome) {
        WatchChrome.Rail -> hot
        WatchChrome.Item -> selected
        else -> false
    }
    Box(
        modifier
            .onFocusChanged {
                focused = it.isFocused
                if (it.isFocused) onFocused?.invoke()
            }
            .clip(shape)
            .drawBehind {
                if (fill.alpha > 0f) drawRect(fill)
                if (bar) {
                    drawRect(WatchPalette.Up, size = Size(3.dp.toPx(), size.height))
                }
            }
            .then(
                if (stroke != null) {
                    Modifier.border(1.dp, stroke, shape)
                } else {
                    Modifier
                },
            )
            .then(
                if (onLongClick != null) {
                    Modifier.combinedClickable(
                        interactionSource = interaction,
                        indication = null,
                        onClick = { if (!gated) onClick() },
                        onLongClick = onLongClick,
                    )
                } else {
                    Modifier.clickable(
                        interactionSource = interaction,
                        indication = null,
                        onClick = { if (!gated) onClick() },
                    )
                },
            )
            .then(if (allowFocus && shellFocus) Modifier else Modifier.focusProperties { canFocus = false })
            .then(
                if (allowFocus && shellFocus) {
                    Modifier
                        .onPreviewKeyEvent { ev ->
                            if (!isOkKey(ev.nativeKeyEvent.keyCode)) return@onPreviewKeyEvent false
                            if (gated) {
                                longPress = false
                                return@onPreviewKeyEvent true
                            }
                            val repeats = ev.nativeKeyEvent.repeatCount
                            when {
                                ev.type == KeyEventType.KeyDown && repeats == 0 -> {
                                    longPress = false
                                    false
                                }
                                ev.type == KeyEventType.KeyDown &&
                                    repeats > 0 &&
                                    onLongClick != null &&
                                    !longPress -> {
                                    longPress = true
                                    onLongClick()
                                    true
                                }
                                ev.type == KeyEventType.KeyUp -> {
                                    if (longPress) {
                                        longPress = false
                                    } else {
                                        onClick()
                                    }
                                    true
                                }
                                else -> false
                            }
                        }
                } else {
                    Modifier
                },
            )
            .padding(contentPadding ?: chrome.pad()),
        contentAlignment = contentAlignment,
    ) {
        CompositionLocalProvider(LocalWatchHot provides hot) {
            content(hot)
        }
    }
}

@Composable
fun WatchListRow(
    selected: Boolean,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    chrome: WatchChrome = WatchChrome.Item,
    onLongClick: (() -> Unit)? = null,
    onFocused: (() -> Unit)? = null,
    content: @Composable () -> Unit,
) {
    WatchHotBox(
        selected = selected,
        onClick = onClick,
        onLongClick = onLongClick,
        onFocused = onFocused,
        modifier = modifier,
        chrome = chrome,
    ) {
        content()
    }
}

private fun isOkKey(code: Int): Boolean =
    code == AndroidKeyEvent.KEYCODE_DPAD_CENTER ||
        code == AndroidKeyEvent.KEYCODE_ENTER ||
        code == AndroidKeyEvent.KEYCODE_NUMPAD_ENTER ||
        code == AndroidKeyEvent.KEYCODE_BUTTON_A

private fun chromeFill(chrome: WatchChrome, hot: Boolean, isNow: Boolean): Color = when (chrome) {
    WatchChrome.Rail -> if (hot) WatchPalette.Hover12 else Color.Transparent
    WatchChrome.Item -> if (hot) WatchPalette.Hover12 else WatchPalette.Panel
    WatchChrome.Cat -> if (hot) WatchPalette.Hover16 else WatchPalette.Panel
    WatchChrome.Chip -> WatchPalette.Panel2
    WatchChrome.Ghost -> if (hot) WatchPalette.Panel2 else Color.Transparent
    WatchChrome.Accent -> if (hot) WatchPalette.Hover10 else Color.Transparent
    WatchChrome.Danger -> if (hot) Color(0x1FFF6B6B) else Color.Transparent
    WatchChrome.Drawer -> if (hot) WatchPalette.Hover12 else Color.Transparent
    WatchChrome.Prog -> when {
        hot -> WatchPalette.Hover12
        isNow -> WatchPalette.Panel2
        else -> WatchPalette.Panel
    }
    WatchChrome.EpgCh -> if (hot) WatchPalette.Hover12 else Color.Transparent
}

private fun chromeStroke(chrome: WatchChrome, hot: Boolean, selected: Boolean, isNow: Boolean): Color? =
    when (chrome) {
        WatchChrome.Rail, WatchChrome.EpgCh -> null
        WatchChrome.Item, WatchChrome.Cat -> if (hot) WatchPalette.Up else WatchPalette.Line
        WatchChrome.Chip -> if (hot || selected) WatchPalette.Up else WatchPalette.Line
        WatchChrome.Ghost -> WatchPalette.Line
        WatchChrome.Accent -> WatchPalette.Up
        WatchChrome.Danger -> WatchPalette.Down
        WatchChrome.Drawer -> null
        WatchChrome.Prog -> when {
            hot -> WatchPalette.Up
            isNow -> WatchPalette.NowLine
            else -> WatchPalette.Line
        }
    }
