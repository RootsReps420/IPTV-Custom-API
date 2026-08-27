package com.iptvmonitor.player.data

import android.util.Xml
import java.io.InputStream
import java.text.SimpleDateFormat
import java.util.Locale
import java.util.TimeZone

object XmltvParser {
    private val formats = arrayOf(
        "yyyyMMddHHmmss Z",
        "yyyyMMddHHmmss",
        "yyyyMMddHHmmssZ",
    )

    fun parseNowNext(input: InputStream, maxChannels: Int = 8000): Map<String, List<EpgEvent>> {
        val parser = Xml.newPullParser()
        parser.setInput(input, null)
        val now = System.currentTimeMillis()
        val horizon = now + 12 * 60 * 60 * 1000L
        val byChannel = HashMap<String, MutableList<EpgEvent>>()
        var event = parser.eventType
        var channel = ""
        var start = 0L
        var stop = 0L
        var inTitle = false
        val title = StringBuilder()
        while (event != org.xmlpull.v1.XmlPullParser.END_DOCUMENT) {
            when (event) {
                org.xmlpull.v1.XmlPullParser.START_TAG -> {
                    when (parser.name) {
                        "programme" -> {
                            channel = parser.getAttributeValue(null, "channel").orEmpty()
                            start = parseXmltvTime(parser.getAttributeValue(null, "start"))
                            stop = parseXmltvTime(parser.getAttributeValue(null, "stop"))
                            title.setLength(0)
                        }
                        "title" -> inTitle = parser.depth > 0
                    }
                }
                org.xmlpull.v1.XmlPullParser.TEXT -> if (inTitle) title.append(parser.text)
                org.xmlpull.v1.XmlPullParser.END_TAG -> {
                    when (parser.name) {
                        "title" -> inTitle = false
                        "programme" -> {
                            if (channel.isNotBlank() && start > 0 && stop > start &&
                                stop >= now && start <= horizon
                            ) {
                                val list = byChannel.getOrPut(channel) { mutableListOf() }
                                if (byChannel.size <= maxChannels || list.isNotEmpty()) {
                                    if (list.size < 4) {
                                        list += EpgEvent(
                                            title = title.toString().trim().ifBlank { "Programme" },
                                            startMs = start,
                                            endMs = stop,
                                            channelId = channel,
                                        )
                                    }
                                }
                            }
                            channel = ""
                            inTitle = false
                        }
                    }
                }
            }
            event = parser.next()
        }
        return byChannel.mapValues { (_, events) ->
            events.sortedBy { it.startMs }.take(4)
        }
    }

    private fun parseXmltvTime(raw: String?): Long {
        val value = raw?.trim().orEmpty()
        if (value.isEmpty()) return 0L
        for (pattern in formats) {
            try {
                val fmt = SimpleDateFormat(pattern, Locale.US)
                fmt.timeZone = TimeZone.getTimeZone("UTC")
                val parsed = fmt.parse(value.replace(Regex("(?<=\\d)(?=[+-]\\d{4}$)"), " "))
                if (parsed != null) return parsed.time
            } catch (_: Exception) {
                /* try next */
            }
        }
        return 0L
    }
}
