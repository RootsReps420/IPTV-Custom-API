package com.iptvmonitor.player.ui

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.focusGroup
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clipToBounds
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.focus.focusProperties
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.zIndex
import coil.compose.AsyncImage
import com.iptvmonitor.player.data.CatalogItem
import com.iptvmonitor.player.data.EpgEvent
import java.text.SimpleDateFormat
import java.util.Calendar
import java.util.Date
import java.util.Locale
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

private val ChannelCol = 220.dp
private val HourWidth = 210.dp
private val RowHeight = 52.dp
private val TickHeight = 36.dp
private const val DayMs = 86_400_000L
private const val HourMs = 3_600_000L
private const val SnapMs = 1_800_000L
private const val TodayHours = 8
private const val MinBlockDp = 36f

fun startOfLocalDay(now: Long = System.currentTimeMillis()): Long {
    val cal = Calendar.getInstance()
    cal.timeInMillis = now
    cal.set(Calendar.HOUR_OF_DAY, 0)
    cal.set(Calendar.MINUTE, 0)
    cal.set(Calendar.SECOND, 0)
    cal.set(Calendar.MILLISECOND, 0)
    return cal.timeInMillis
}

private fun snapWindowStart(now: Long): Long = (now / SnapMs) * SnapMs

private fun windowStart(now: Long, dayOffset: Int): Long {
    return if (dayOffset == 0) snapWindowStart(now) else startOfLocalDay(now) + dayOffset * DayMs
}

private fun windowLength(dayOffset: Int): Long {
    return if (dayOffset == 0) TodayHours * HourMs else DayMs
}

private fun epgX(ts: Long, winStart: Long): Dp {
    return HourWidth * ((ts - winStart).toFloat() / HourMs)
}

@Composable
fun LiveEpgGuide(viewModel: PortalViewModel, items: List<CatalogItem>, modifier: Modifier) {
    if (items.isEmpty()) {
        Text("Nothing in this group.", color = WatchPalette.Muted, modifier = modifier)
        return
    }
    var nowMs by remember { mutableLongStateOf(System.currentTimeMillis()) }
    LaunchedEffect(Unit) {
        while (true) {
            nowMs = System.currentTimeMillis()
            delay(5_000)
        }
    }
    val snapKey = nowMs / SnapMs
    val winStart = remember(snapKey) { windowStart(nowMs, 0) }
    val winLen = windowLength(0)
    val winEnd = winStart + winLen
    val gridWidth = HourWidth * (winLen.toFloat() / HourMs)
    val scroll = rememberScrollState()
    LaunchedEffect(snapKey) { scroll.scrollTo(0) }
    val showNeedle = nowMs in winStart until winEnd
    val needleX = epgX(nowMs, winStart).coerceIn(0.dp, gridWidth)
    val clock = remember(nowMs) {
        SimpleDateFormat("EEE HH:mm", Locale.getDefault()).format(Date(nowMs))
    }
    val nowBucket = nowMs / 15_000L
    val dpadGuide = viewModel.isTelevision

    Column(modifier) {
        if (viewModel.epgLoading) {
            Text(
                "Syncing EPG…",
                color = WatchPalette.Muted,
                fontSize = 11.sp,
                modifier = Modifier.padding(bottom = 6.dp),
            )
        }
        Row(
            Modifier
                .fillMaxWidth()
                .height(TickHeight)
                .background(WatchPalette.Rail),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text(
                clock,
                color = WatchPalette.Up,
                fontSize = 11.sp,
                modifier = Modifier.width(ChannelCol).padding(horizontal = 10.dp),
            )
            Box(
                Modifier
                    .weight(1f)
                    .fillMaxHeight()
                    .horizontalScroll(scroll, enabled = !dpadGuide)
                    .clipToBounds()
                    .focusProperties { canFocus = false },
            ) {
                Box(Modifier.width(gridWidth).fillMaxHeight().drawEpgTicks()) {
                    var tick = winStart
                    while (tick < winEnd) {
                        val x = epgX(tick, winStart)
                        Text(
                            formatTick(tick),
                            color = WatchPalette.Muted,
                            fontSize = 11.sp,
                            modifier = Modifier
                                .offset(x = x)
                                .padding(start = 8.dp, top = 10.dp),
                        )
                        tick += SnapMs
                    }
                    if (showNeedle) {
                        EpgNowNeedle(needleX)
                    }
                }
            }
        }
        LazyColumn(Modifier.fillMaxSize()) {
            itemsIndexed(items, key = { _, item -> item.id + item.playbackUrl }) { index, item ->
                val here = viewModel.playing?.channelId == item.id
                EpgChannelRow(
                    item = item,
                    index = index,
                    selected = here,
                    events = viewModel.epgFor(item),
                    winStart = winStart,
                    winEnd = winEnd,
                    gridWidth = gridWidth,
                    scroll = scroll,
                    showNeedle = showNeedle,
                    needleX = needleX,
                    nowBucket = nowBucket,
                    scrollEnabled = !dpadGuide,
                    onPlay = { event -> viewModel.playItem(item, event) },
                    onRecord = { event -> viewModel.openItemMenu(item = item, event = event) },
                )
            }
        }
    }
}

@Composable
private fun EpgChannelRow(
    item: CatalogItem,
    index: Int,
    selected: Boolean,
    events: List<EpgEvent>,
    winStart: Long,
    winEnd: Long,
    gridWidth: Dp,
    scroll: androidx.compose.foundation.ScrollState,
    showNeedle: Boolean,
    needleX: Dp,
    nowBucket: Long,
    scrollEnabled: Boolean,
    onPlay: (EpgEvent?) -> Unit,
    onRecord: (EpgEvent?) -> Unit,
) {
    val slots = events.filter { it.endMs > winStart && it.startMs < winEnd }
    val nowMs = nowBucket * 15_000L
    val scope = rememberCoroutineScope()
    val density = LocalDensity.current
    Row(
        Modifier
            .fillMaxWidth()
            .height(RowHeight)
            .focusGroup()
            .background(if (selected) WatchPalette.Hover04 else WatchPalette.Stage)
            .drawBehind {
                drawLine(
                    WatchPalette.Line.copy(alpha = 0.55f),
                    Offset(0f, size.height),
                    Offset(size.width, size.height),
                    strokeWidth = 1f,
                )
            },
        verticalAlignment = Alignment.CenterVertically,
    ) {
        WatchHotBox(
            selected = selected,
            onClick = { onPlay(null) },
            onLongClick = { onRecord(null) },
            chrome = WatchChrome.EpgCh,
            modifier = Modifier
                .width(ChannelCol)
                .fillMaxHeight()
                .background(WatchPalette.Rail),
        ) { hot ->
            Row(
                Modifier.fillMaxWidth(),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(6.dp),
            ) {
                Text(
                    item.id.filter { it.isDigit() }.takeLast(4).ifBlank { (index + 1).toString() },
                    color = if (hot) WatchPalette.Up else WatchPalette.Muted,
                    fontSize = 11.sp,
                    modifier = Modifier.width(28.dp),
                )
                AsyncImage(
                    model = item.logo.ifBlank { null },
                    contentDescription = null,
                    modifier = Modifier.width(32.dp).height(32.dp).background(WatchPalette.Panel2),
                    contentScale = ContentScale.Fit,
                )
                Text(
                    item.name,
                    color = if (hot) WatchPalette.Up else WatchPalette.Text,
                    fontWeight = if (hot) FontWeight.Bold else FontWeight.Medium,
                    maxLines = 2,
                    overflow = TextOverflow.Ellipsis,
                    fontSize = 12.sp,
                    modifier = Modifier.weight(1f),
                )
                if (selected) {
                    WatchEpgCaret()
                }
            }
        }
        Box(
            Modifier
                .weight(1f)
                .fillMaxHeight()
                .horizontalScroll(scroll, enabled = scrollEnabled)
                .clipToBounds(),
        ) {
            Box(
                Modifier
                    .width(gridWidth)
                    .fillMaxHeight()
                    .background(WatchPalette.Stage)
                    .drawEpgTicks(),
            ) {
                if (slots.isEmpty()) {
                    WatchHotBox(
                        selected = false,
                        onClick = { onPlay(null) },
                        onLongClick = { onRecord(null) },
                        chrome = WatchChrome.Prog,
                        modifier = Modifier
                            .align(Alignment.CenterStart)
                            .padding(start = 8.dp, top = 6.dp, bottom = 6.dp, end = 8.dp)
                            .width(180.dp)
                            .fillMaxHeight(),
                    ) {
                        Text("No programme info", color = WatchPalette.Muted, fontSize = 11.sp)
                    }
                } else {
                    slots.forEach { event ->
                        val left = epgX(event.startMs, winStart).coerceAtLeast(0.dp)
                        val right = epgX(event.endMs, winStart).coerceAtMost(gridWidth)
                        val width = (right - left - 3.dp).coerceAtLeast(MinBlockDp.dp)
                        val onNow = nowMs in event.startMs until event.endMs
                        val span = (event.endMs - event.startMs).coerceAtLeast(1L)
                        val progress = if (onNow) {
                            ((nowMs - event.startMs).toFloat() / span).coerceIn(0f, 1f)
                        } else {
                            0f
                        }
                        WatchHotBox(
                            selected = selected && onNow,
                            onClick = { onPlay(event) },
                            onLongClick = { onRecord(event) },
                            chrome = WatchChrome.Prog,
                            isNow = onNow,
                            onFocused = {
                                val x = with(density) { left.toPx() }.toInt()
                                val target = (x - 48).coerceAtLeast(0)
                                if (kotlin.math.abs(scroll.value - target) > 24) {
                                    scope.launch { scroll.scrollTo(target) }
                                }
                            },
                            modifier = Modifier
                                .align(Alignment.CenterStart)
                                .offset(x = left + 1.dp)
                                .width(width)
                                .fillMaxHeight()
                                .padding(vertical = 6.dp),
                        ) { hot ->
                            if (progress > 0f) {
                                Box(
                                    Modifier
                                        .align(Alignment.CenterStart)
                                        .fillMaxHeight()
                                        .fillMaxWidth(progress)
                                        .background(WatchPalette.Up.copy(alpha = 0.22f)),
                                )
                            }
                            Text(
                                event.title,
                                color = if (hot) WatchPalette.Up else WatchPalette.Text,
                                fontSize = 12.sp,
                                maxLines = 1,
                                overflow = TextOverflow.Ellipsis,
                            )
                        }
                    }
                }
                if (showNeedle) {
                    Box(
                        Modifier
                            .align(Alignment.TopStart)
                            .padding(start = (needleX - 1.dp).coerceAtLeast(0.dp))
                            .width(2.dp)
                            .fillMaxHeight()
                            .zIndex(2f)
                            .background(WatchPalette.Up.copy(alpha = 0.9f)),
                    )
                }
            }
        }
    }
}

@Composable
private fun EpgNowNeedle(x: Dp) {
    Box(
        Modifier
            .offset(x = x - 4.dp)
            .zIndex(3f)
            .padding(top = 14.dp),
    ) {
        Box(
            Modifier
                .size(8.dp)
                .background(WatchPalette.Up, CircleShape),
        )
        Box(
            Modifier
                .align(Alignment.TopCenter)
                .padding(top = 8.dp)
                .width(2.dp)
                .height(14.dp)
                .background(WatchPalette.Up),
        )
    }
}

private fun Modifier.drawEpgTicks(): Modifier = drawBehind {
    val step = (HourWidth / 2).toPx()
    val line = WatchPalette.Line.copy(alpha = 0.7f)
    var x = 0f
    while (x <= size.width + 0.5f) {
        drawLine(line, Offset(x, 0f), Offset(x, size.height), strokeWidth = 1f)
        x += step
    }
}

@Composable
private fun WatchEpgCaret() {
    Canvas(Modifier.size(width = 6.dp, height = 12.dp)) {
        val caret = Path().apply {
            moveTo(0f, 0f)
            lineTo(size.width, size.height / 2f)
            lineTo(0f, size.height)
            close()
        }
        drawPath(caret, WatchPalette.Up)
    }
}

private fun formatTick(ms: Long): String {
    return SimpleDateFormat("HH:mm", Locale.getDefault()).format(Date(ms))
}

fun upcomingEpg(events: List<EpgEvent>, limit: Int = 8): List<EpgEvent> {
    val now = System.currentTimeMillis()
    return events.filter { it.endMs > now }.sortedBy { it.startMs }.take(limit)
}
