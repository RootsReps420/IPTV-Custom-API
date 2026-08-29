package com.iptvmonitor.player.data

import android.util.Xml
import java.io.InputStream
import java.text.SimpleDateFormat
import java.util.Locale
import java.util.TimeZone

object XmltvParser {
    private val formats = arrayOf(
        "yyyyMMddHHmmss Z",
        "yyyyMMddHHmmssZ",
        "yyyyMMddHHmmss",
        "yyyy-MM-dd HH:mm:ss Z",
        "yyyy-MM-dd'T'HH:mm:ssZ",
    )

    const val HORIZON_DAYS = 7
    const val MAX_EVENTS_PER_CHANNEL = 400

    fun parseNowNext(input: InputStream, maxChannels: Int = 12_000): Map<String, List<EpgEvent>> {
        return parse(input, maxChannels)
    }

    fun parse(
        input: InputStream,
        maxChannels: Int = 12_000,
        horizonDays: Int = HORIZON_DAYS,
        pastDays: Int = 1,
        storeDescriptions: Boolean = true,
    ): Map<String, List<EpgEvent>> {
        val parser = Xml.newPullParser()
        parser.setInput(input, null)
        val now = System.currentTimeMillis()
        val keepFrom = now - pastDays.coerceIn(0, 14) * 86_400_000L
        val horizon = now + horizonDays.coerceIn(1, 14) * 86_400_000L
        val byChannel = HashMap<String, MutableList<EpgEvent>>()
        val aliases = HashMap<String, MutableSet<String>>()
        var event = parser.eventType
        var channel = ""
        var channelId = ""
        var start = 0L
        var stop = 0L
        var inTitle = false
        var inDisplay = false
        var inDesc = false
        val title = StringBuilder()
        val display = StringBuilder()
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
                            if (channel.isNotBlank() && start > 0 && stop > start &&
                                stop >= keepFrom && start <= horizon
                            ) {
                                val plot = desc.toString().trim()
                                val item = EpgEvent(
                                    title = title.toString().trim().ifBlank { "Programme" },
                                    startMs = start,
                                    endMs = stop,
                                    channelId = channel,
                                    plot = plot,
                                )
                                indexEvent(byChannel, aliases, channel, item, maxChannels)
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
        return byChannel.mapValues { (_, events) ->
            events.sortedBy { it.startMs }.distinctBy { it.startMs to it.title }
        }
    }

    private fun indexEvent(
        byChannel: HashMap<String, MutableList<EpgEvent>>,
        aliases: Map<String, Set<String>>,
        channel: String,
        item: EpgEvent,
        maxChannels: Int,
    ) {
        val keys = LinkedHashSet<String>()
        keys += channel
        keys += channel.lowercase(Locale.US)
        aliases[channel]?.forEach { name ->
            keys += name
            keys += name.lowercase(Locale.US)
        }
        keys.forEach { key ->
            if (key.isBlank()) return@forEach
            val list = byChannel.getOrPut(key) { mutableListOf() }
            if ((byChannel.size <= maxChannels || list.isNotEmpty()) &&
                list.size < MAX_EVENTS_PER_CHANNEL
            ) {
                list += item
            }
        }
    }

    private fun parseXmltvTime(raw: String?): Long {
        val value = raw?.trim().orEmpty()
        if (value.isEmpty()) return 0L
        val normalized = value
            .replace(Regex("(?<=\\d)(?=[+-]\\d{4}$)"), " ")
            .replace(Regex("([+-]\\d{2}):(\\d{2})$"), "$1$2")
        for (pattern in formats) {
            try {
                val fmt = SimpleDateFormat(pattern, Locale.US)
                fmt.timeZone = TimeZone.getTimeZone("UTC")
                val parsed = fmt.parse(normalized)
                if (parsed != null) return parsed.time
            } catch (_: Exception) {
                /* try next */
            }
        }
        return 0L
    }
}
