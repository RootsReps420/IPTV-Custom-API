package com.iptvmonitor.player.ui

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
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
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import coil.compose.AsyncImage
import com.iptvmonitor.player.data.CatalogItem
import com.iptvmonitor.player.data.EpgEvent
import java.text.SimpleDateFormat
import java.util.Calendar
import java.util.Date
import java.util.Locale

private val ChannelCol = 168.dp
private val HourWidth = 132.dp
private val RowHeight = 54.dp
private const val DayMs = 86_400_000L
private const val HourMs = 3_600_000L

fun startOfLocalDay(now: Long = System.currentTimeMillis()): Long {
    val cal = Calendar.getInstance()
    cal.timeInMillis = now
    cal.set(Calendar.HOUR_OF_DAY, 0)
    cal.set(Calendar.MINUTE, 0)
    cal.set(Calendar.SECOND, 0)
    cal.set(Calendar.MILLISECOND, 0)
    return cal.timeInMillis
}

@Composable
fun LiveEpgGuide(viewModel: PortalViewModel, items: List<CatalogItem>, modifier: Modifier) {
    if (items.isEmpty()) {
        Text("Nothing in this group.", color = WatchPalette.Muted, modifier = modifier)
        return
    }
    val days = viewModel.epgHorizonDays()
    val dayStart = startOfLocalDay() + viewModel.epgDayOffset * DayMs
    val scroll = rememberScrollState()
    LaunchedEffect(viewModel.epgDayOffset) { scroll.scrollTo(0) }
    val gridWidth = HourWidth * 24
    val now = System.currentTimeMillis()
    val showNeedle = viewModel.epgDayOffset == 0 && now in dayStart until (dayStart + DayMs)
    val needleX = ((now - dayStart).toFloat() / HourMs) * HourWidth.value

    Column(modifier) {
        Row(
            Modifier.fillMaxWidth().padding(bottom = 8.dp),
            horizontalArrangement = Arrangement.spacedBy(6.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text("Guide", color = WatchPalette.Up, fontSize = 12.sp)
            for (day in 0 until days) {
                val label = dayChipLabel(day)
                BoxChip(label, viewModel.epgDayOffset == day) { viewModel.epgDayOffset = day }
            }
            if (viewModel.epgLoading) {
                Text("Syncing EPG…", color = WatchPalette.Muted, fontSize = 11.sp)
            }
        }
        Row(
            Modifier
                .fillMaxWidth()
                .height(36.dp)
                .background(WatchPalette.Rail),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text(
                SimpleDateFormat("EEE HH:mm", Locale.getDefault()).format(Date()),
                color = WatchPalette.Up,
                fontSize = 11.sp,
                modifier = Modifier.width(ChannelCol).padding(horizontal = 10.dp),
            )
            Box(Modifier.weight(1f).fillMaxHeight().horizontalScroll(scroll)) {
                Box(Modifier.width(gridWidth).fillMaxHeight()) {
                    for (hour in 0 until 24) {
                        Text(
                            String.format(Locale.getDefault(), "%02d:00", hour),
                            color = WatchPalette.Muted,
                            fontSize = 11.sp,
                            modifier = Modifier
                                .offset(x = HourWidth * hour)
                                .padding(start = 6.dp, top = 10.dp),
                        )
                    }
                    if (showNeedle) {
                        Box(
                            Modifier
                                .offset(x = needleX.dp)
                                .width(2.dp)
                                .fillMaxHeight()
                                .background(WatchPalette.Up),
                        )
                    }
                }
            }
        }
        LazyColumn(Modifier.fillMaxSize()) {
            itemsIndexed(items, key = { _, item -> item.id + item.playbackUrl }) { index, item ->
                val here = viewModel.playing?.channelId == item.id
                val events = viewModel.epgFor(item)
                EpgChannelRow(
                    item = item,
                    index = index,
                    selected = here,
                    events = events,
                    dayStart = dayStart,
                    gridWidth = gridWidth,
                    scroll = scroll,
                    showNeedle = showNeedle,
                    needleX = needleX.dp,
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
    dayStart: Long,
    gridWidth: Dp,
    scroll: androidx.compose.foundation.ScrollState,
    showNeedle: Boolean,
    needleX: Dp,
    onPlay: (EpgEvent?) -> Unit,
    onRecord: (EpgEvent?) -> Unit,
) {
    val dayEnd = dayStart + DayMs
    val slots = events.filter { it.endMs > dayStart && it.startMs < dayEnd }
    Row(
        Modifier
            .fillMaxWidth()
            .height(RowHeight)
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
        Box(Modifier.weight(1f).fillMaxHeight().horizontalScroll(scroll)) {
            Box(Modifier.width(gridWidth).fillMaxHeight().background(WatchPalette.Stage)) {
                if (slots.isEmpty()) {
                    Text(
                        "No programme info",
                        color = WatchPalette.Muted,
                        fontSize = 11.sp,
                        modifier = Modifier.padding(start = 10.dp, top = 18.dp),
                    )
                } else {
                    slots.forEach { event ->
                        val leftHours = ((event.startMs - dayStart).coerceAtLeast(0L).toFloat() / HourMs)
                        val rightHours = ((event.endMs - dayStart).coerceAtMost(DayMs).toFloat() / HourMs)
                        val widthHours = (rightHours - leftHours).coerceAtLeast(0.25f)
                        WatchHotBox(
                            selected = selected && event.isNow,
                            onClick = { onPlay(event) },
                            onLongClick = { onRecord(event) },
                            chrome = WatchChrome.Prog,
                            isNow = event.isNow,
                            modifier = Modifier
                                .offset(x = HourWidth * leftHours)
                                .width(HourWidth * widthHours - 3.dp)
                                .fillMaxHeight()
                                .padding(vertical = 6.dp),
                        ) { hot ->
                            Column {
                                Text(
                                    formatEpgTime(event),
                                    color = if (hot) WatchPalette.Up else WatchPalette.Muted,
                                    fontSize = 10.sp,
                                    maxLines = 1,
                                )
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
                }
                if (showNeedle) {
                    Box(
                        Modifier
                            .offset(x = needleX)
                            .width(2.dp)
                            .fillMaxHeight()
                            .background(WatchPalette.Up.copy(alpha = 0.85f)),
                    )
                }
            }
        }
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

private fun dayChipLabel(offset: Int): String {
    val fmt = SimpleDateFormat("EEE d", Locale.getDefault())
    return when (offset) {
        0 -> "Today"
        1 -> "Tomorrow"
        else -> fmt.format(Date(startOfLocalDay() + offset * DayMs))
    }
}

fun upcomingEpg(events: List<EpgEvent>, limit: Int = 8): List<EpgEvent> {
    val now = System.currentTimeMillis()
    return events.filter { it.endMs > now }.sortedBy { it.startMs }.take(limit)
}
