package com.iptvmonitor.player.data

import android.util.Xml
import java.io.InputStream
import java.time.LocalDateTime
import java.time.ZoneOffset
import java.util.Locale

object XmltvParser {
    const val HORIZON_DAYS = 7
    const val MAX_EVENTS_PER_CHANNEL = 600

    fun parseNowNext(input: InputStream, maxChannels: Int = 50_000): Map<String, List<EpgEvent>> {
        return parse(input, maxChannels)
    }

    fun parse(
        input: InputStream,
        maxChannels: Int = 50_000,
        horizonDays: Int = HORIZON_DAYS,
        pastDays: Int = 1,
        storeDescriptions: Boolean = true,
    ): Map<String, List<EpgEvent>> {
        val parser = Xml.newPullParser()
        parser.setInput(input, null)
        val now = System.currentTimeMillis()
        val keepFrom = now - pastDays.coerceIn(0, 14) * 86_400_000L
        val horizon = now + horizonDays.coerceIn(1, 14) * 86_400_000L
        val byChannel = HashMap<String, MutableList<EpgEvent>>(4096)
        val aliases = HashMap<String, MutableSet<String>>(4096)
        var event = parser.eventType
        var channel = ""
        var channelId = ""
        var start = 0L
        var stop = 0L
        var inTitle = false
        var inDisplay = false
        var inDesc = false
        val title = StringBuilder(64)
        val display = StringBuilder(64)
        val desc = StringBuilder()
        while (event != org.xmlpull.v1.XmlPullParser.END_DOCUMENT) {
            when (event) {
                org.xmlpull.v1.XmlPullParser.START_TAG -> {
                    when (parser.name) {
                        "channel" -> {
                            channelId = parser.getAttributeValue(null, "id").orEmpty()
                            display.setLength(0)
                        }
                        "display-name" -> inDisplay = true
                        "programme" -> {
                            channel = parser.getAttributeValue(null, "channel").orEmpty()
                            start = parseXmltvTime(parser.getAttributeValue(null, "start"))
                            stop = parseXmltvTime(parser.getAttributeValue(null, "stop"))
                            title.setLength(0)
                            desc.setLength(0)
                        }
                        "title" -> inTitle = true
                        "desc" -> inDesc = storeDescriptions
                    }
                }
                org.xmlpull.v1.XmlPullParser.TEXT -> {
                    when {
                        inTitle -> title.append(parser.text)
                        inDisplay -> display.append(parser.text)
                        inDesc -> desc.append(parser.text)
                    }
                }
                org.xmlpull.v1.XmlPullParser.END_TAG -> {
                    when (parser.name) {
                        "display-name" -> {
                            inDisplay = false
                            val name = display.toString().trim()
                            if (channelId.isNotBlank() && name.isNotBlank()) {
                                aliases.getOrPut(channelId) { mutableSetOf() }.add(name)
                            }
                            display.setLength(0)
                        }
                        "channel" -> channelId = ""
                        "title" -> inTitle = false
                        "desc" -> inDesc = false
                        "programme" -> {
                            if (channel.isNotBlank() && start > 0L && stop > start &&
                                stop >= keepFrom && start <= horizon
                            ) {
                                val list = byChannel.getOrPut(channel) { ArrayList(32) }
                                if (list.size < MAX_EVENTS_PER_CHANNEL &&
                                    (byChannel.size <= maxChannels || list.isNotEmpty())
                                ) {
                                    list += EpgEvent(
                                        title = title.toString().trim().ifBlank { "Programme" },
                                        startMs = start,
                                        endMs = stop,
                                        channelId = channel,
                                        plot = desc.toString().trim(),
                                    )
                                }
                            }
                            channel = ""
                            inTitle = false
                            inDesc = false
                        }
                    }
                }
            }
            event = parser.next()
        }
        return indexLookups(byChannel, aliases)
    }

    /**
     * Store each programme once, then point tvg-id / display-name / normalised
     * name keys at the same list so matching is cheap and does not inflate RAM.
     */
    private fun indexLookups(
        byChannel: Map<String, MutableList<EpgEvent>>,
        aliases: Map<String, Set<String>>,
    ): Map<String, List<EpgEvent>> {
        val out = HashMap<String, List<EpgEvent>>(byChannel.size * 4)
        byChannel.forEach { (id, events) ->
            val sorted = events.sortedBy { it.startMs }.distinctBy { it.startMs to it.title }
            putKeys(out, id, sorted)
            aliases[id]?.forEach { putKeys(out, it, sorted) }
        }
        return out
    }

    private fun putKeys(out: HashMap<String, List<EpgEvent>>, raw: String, events: List<EpgEvent>) {
        val trimmed = raw.trim()
        if (trimmed.isEmpty()) return
        out[trimmed] = events
        val lower = trimmed.lowercase(Locale.US)
        out[lower] = events
        val compact = epgKey(trimmed)
        if (compact.isNotEmpty() && compact != lower) {
            out.putIfAbsent(compact, events)
        }
    }

    /** Strip quality tags so "BBC One HD" matches XMLTV "BBC One". */
    fun epgKey(raw: String): String {
        var s = raw.lowercase(Locale.US)
        s = s.replace(Regex("\\[.*?]|\\(.*?\\)"), " ")
        s = s.replace('|', ' ')
        s = s.replace(Regex("\\b(uhd|fhd|hd|sd|4k|8k|hevc|hdr)\\b"), " ")
        return s.replace(Regex("[^a-z0-9]+"), "")
    }

    /**
     * XMLTV `yyyyMMddHHmmss[ offset]`. Offset is subtracted from the wall clock
     * so `180000 +0100` becomes 17:00 UTC. Bare 14-digit stamps are UTC.
     */
    fun parseXmltvTime(raw: String?): Long {
        val value = raw?.trim().orEmpty()
        if (value.length < 14) return 0L
        val digits = value
        return try {
            val year = digits.substring(0, 4).toInt()
            val month = digits.substring(4, 6).toInt()
            val day = digits.substring(6, 8).toInt()
            val hour = digits.substring(8, 10).toInt()
            val minute = digits.substring(10, 12).toInt()
            val second = digits.substring(12, 14).toInt()
            var offsetSec = 0
            val tail = if (digits.length > 14) digits.substring(14).trim() else ""
            if (tail.length >= 3 && (tail[0] == '+' || tail[0] == '-')) {
                val sign = if (tail[0] == '-') -1 else 1
                val num = tail.filter { it.isDigit() }
                if (num.length >= 2) {
                    val hh = num.substring(0, 2).toInt()
                    val mm = if (num.length >= 4) num.substring(2, 4).toInt() else 0
                    offsetSec = sign * (hh * 3600 + mm * 60)
                }
            }
            utcMillis(year, month, day, hour, minute, second) - offsetSec * 1000L
        } catch (_: Exception) {
            0L
        }
    }

    private fun utcMillis(year: Int, month: Int, day: Int, hour: Int, minute: Int, second: Int): Long {
        return LocalDateTime.of(year, month, day, hour, minute, second)
            .toInstant(ZoneOffset.UTC)
            .toEpochMilli()
    }
}
