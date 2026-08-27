package com.iptvmonitor.player.data

import java.net.URI
import java.security.MessageDigest
import java.util.Locale
import java.util.regex.Pattern

object M3uParser {
    private val attr = Pattern.compile("([A-Za-z0-9-]+)=\"([^\"]*)\"")
    private val headerTvg = Pattern.compile(
        "(?:url-tvg|x-tvg-url|tvg-url)\\s*=\\s*(?:\"([^\"]+)\"|(\\S+))",
        Pattern.CASE_INSENSITIVE,
    )
    private val xtreamId = Pattern.compile("/(\\d+)\\.(ts|m3u8|mp4)$", Pattern.CASE_INSENSITIVE)
    private val vodPath = Pattern.compile("/(movie|series)/", Pattern.CASE_INSENSITIVE)

    data class Parsed(
        val epgUrl: String,
        val live: List<CatalogItem>,
        val movies: List<CatalogItem>,
        val series: List<CatalogItem>,
        val liveCategories: List<Category>,
        val movieCategories: List<Category>,
        val seriesCategories: List<Category>,
    )

    fun parse(text: String): Parsed {
        var epgUrl = ""
        var pending: MutableMap<String, String>? = null
        val liveCats = LinkedHashMap<String, String>()
        val movieCats = LinkedHashMap<String, String>()
        val seriesCats = LinkedHashMap<String, String>()
        val live = mutableListOf<CatalogItem>()
        val movies = mutableListOf<CatalogItem>()
        val series = mutableListOf<CatalogItem>()
        val usedIds = HashSet<String>()
        var index = 0

        for (raw in text.lineSequence()) {
            val line = raw.trim()
            if (line.isEmpty()) continue
            if (line.startsWith("#EXTM3U")) {
                epgUrl = parseHeaderEpg(line).ifBlank { epgUrl }
                continue
            }
            if (line.startsWith("#EXTINF")) {
                pending = parseExtinf(line)
                continue
            }
            if (line.startsWith("#")) continue
            val meta = pending ?: continue
            pending = null
            if (!line.startsWith("http://") && !line.startsWith("https://")) continue
            index += 1
            val group = meta["group-title"].orEmpty().ifBlank { "Live" }
            val name = meta["name"].orEmpty().ifBlank { "Channel $index" }
            val id = streamId(line, usedIds)
            val vod = vodPath.matcher(URI(line).path ?: "").find()
            val kind = when {
                line.contains("/series/", ignoreCase = true) -> MediaKind.SERIES
                line.contains("/movie/", ignoreCase = true) -> MediaKind.MOVIE
                vod -> MediaKind.MOVIE
                else -> MediaKind.LIVE
            }
            val catMap = when (kind) {
                MediaKind.LIVE -> liveCats
                MediaKind.MOVIE -> movieCats
                MediaKind.SERIES -> seriesCats
            }
            val cid = categoryId(group, catMap)
            val item = CatalogItem(
                id = id,
                name = name,
                categoryId = cid,
                logo = meta["tvg-logo"].orEmpty(),
                playbackUrl = line,
                kind = kind,
                tvgId = meta["tvg-id"].orEmpty(),
            )
            when (kind) {
                MediaKind.LIVE -> live += item
                MediaKind.MOVIE -> movies += item
                MediaKind.SERIES -> series += item
            }
        }
        return Parsed(
            epgUrl = epgUrl,
            live = live,
            movies = movies,
            series = series,
            liveCategories = cats(liveCats),
            movieCategories = cats(movieCats),
            seriesCategories = cats(seriesCats),
        )
    }

    private fun cats(map: Map<String, String>): List<Category> =
        map.entries.map { Category(id = it.value, name = it.key) }

    private fun parseHeaderEpg(line: String): String {
        val matcher = headerTvg.matcher(line)
        if (!matcher.find()) return ""
        return (matcher.group(1) ?: matcher.group(2) ?: "").trim().trim('\'').split(",").first().trim()
    }

    private fun parseExtinf(line: String): MutableMap<String, String> {
        val body = if (line.startsWith("#EXTINF")) line.substring(7).trimStart() else line
        val comma = body.lastIndexOf(',')
        val meta = if (comma >= 0) body.substring(0, comma) else body
        val name = if (comma >= 0) body.substring(comma + 1).trim() else ""
        val attrs = mutableMapOf<String, String>()
        val matcher = attr.matcher(meta)
        while (matcher.find()) {
            attrs[matcher.group(1).lowercase(Locale.US)] = matcher.group(2)
        }
        val display = name.ifBlank { attrs["tvg-name"].orEmpty() }
        attrs["name"] = display
        return attrs
    }

    private fun streamId(url: String, used: MutableSet<String>): String {
        val path = runCatching { URI(url).path }.getOrNull().orEmpty()
        val matcher = xtreamId.matcher(path)
        var sid = if (matcher.find()) matcher.group(1) else sha1(url).take(16)
        if (sid in used) sid = sha1("$sid:$url").take(16)
        used += sid
        return sid
    }

    private fun categoryId(name: String, used: MutableMap<String, String>): String {
        used[name]?.let { return it }
        var slug = name.lowercase(Locale.US).replace(Regex("[^a-z0-9]+"), "-").trim('-').take(60)
        if (slug.isEmpty()) slug = "g-" + sha1(name).take(10)
        val base = slug
        var n = 2
        val taken = used.values.toSet()
        while (slug in taken) {
            slug = "$base-$n"
            n += 1
        }
        used[name] = slug
        return slug
    }

    private fun sha1(value: String): String {
        val digest = MessageDigest.getInstance("SHA-1").digest(value.toByteArray())
        return digest.joinToString("") { "%02x".format(it) }
    }
}
