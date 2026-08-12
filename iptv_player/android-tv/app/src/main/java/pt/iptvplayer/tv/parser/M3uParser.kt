package pt.iptvplayer.tv.parser

import java.net.URI
import java.net.URLDecoder
import java.nio.charset.StandardCharsets
import java.text.Normalizer
import java.io.Reader
import pt.iptvplayer.tv.model.Channel
import pt.iptvplayer.tv.model.Playlist
import pt.iptvplayer.tv.model.StreamType

data class M3uParseResult(val epgUrl: String, val channelCount: Int)

class M3uParser {
    fun parse(content: String, name: String = "Lista IPTV"): Playlist {
        val result = mutableListOf<Channel>()
        val parsed = parse(content.reader(), result::add)
        return Playlist(name = name, channels = result, epgUrl = parsed.epgUrl)
    }

    fun parse(reader: Reader, onChannel: (Channel) -> Unit): M3uParseResult {
        val lines = reader.buffered()
        val header = generateSequence(lines::readLine)
            .map { it.trim().removePrefix("\uFEFF") }
            .firstOrNull(String::isNotBlank)
            .orEmpty()
        require(header.startsWith("#EXTM3U", ignoreCase = true)) {
            "O conteúdo não é uma lista M3U válida."
        }
        val epgUrl = attribute(header, "x-tvg-url")
            .ifBlank { attribute(header, "url-tvg") }
        var extInf: String? = null
        var userAgent = ""
        var referer = ""
        var count = 0
        lines.forEachLine { rawLine ->
            val line = rawLine.trim()
            when {
                line.startsWith("#EXTINF:", ignoreCase = true) -> {
                    extInf = line
                    val attributes = parseAttributes(line)
                    userAgent = attributes["user-agent"].orEmpty()
                    referer = attributes["referer"].orEmpty()
                }
                extInf != null && line.startsWith("#EXTVLCOPT:", ignoreCase = true) -> {
                    val option = line.substringAfter(':')
                    val key = option.substringBefore('=').trim().lowercase()
                    val value = option.substringAfter('=', "").trim()
                    when (key) {
                        "http-user-agent" -> userAgent = value
                        "http-referrer", "http-referer" -> referer = value
                    }
                }
                extInf != null && line.isNotBlank() && !line.startsWith('#') -> {
                    onChannel(buildChannel(extInf!!, line, userAgent, referer))
                    count++
                    extInf = null
                    userAgent = ""
                    referer = ""
                }
            }
        }
        return M3uParseResult(epgUrl, count)
    }

    private fun buildChannel(
        extInf: String,
        url: String,
        userAgent: String,
        referer: String,
    ): Channel {
        val attributes = parseAttributes(extInf)
        val displayName = extInf.substringAfterLast(',', "Canal").trim().ifBlank { "Canal" }
        val group = attributes["group-title"].orEmpty().ifBlank { "Geral" }
        val explicitType = attributes["stream-type"]
            ?: attributes["media-type"]
            ?: attributes["tvg-type"]
            ?: attributes["type"]
            ?: ""
        val duration = Regex("^#EXTINF:([-+]?\\d+(?:\\.\\d+)?)", RegexOption.IGNORE_CASE)
            .find(extInf)?.groupValues?.get(1)?.toDoubleOrNull()
        return Channel(
            name = displayName,
            url = url,
            group = group,
            logo = attributes["tvg-logo"].orEmpty(),
            tvgId = attributes["tvg-id"].orEmpty(),
            userAgent = userAgent,
            referer = referer,
            type = inferStreamType(url, group, displayName, explicitType, duration),
            quality = inferQuality(displayName),
        )
    }

    fun inferStreamType(
        url: String,
        group: String = "",
        name: String = "",
        explicitType: String = "",
        duration: Double? = null,
    ): StreamType {
        when (plain(explicitType).trim()) {
            "movie", "movies", "vod", "film", "video" -> return StreamType.VOD
            "series", "serie", "episode", "episodes", "show" -> return StreamType.SERIES
            "live", "tv", "channel", "radio" -> return StreamType.LIVE
        }

        val pathParts = runCatching {
            URLDecoder.decode(URI(url).path.orEmpty(), StandardCharsets.UTF_8.name())
        }.getOrDefault(url).let(::plain).split('/').filter(String::isNotBlank).toSet()
        if (pathParts.any { it in setOf("movie", "movies", "vod", "film", "films") }) return StreamType.VOD
        if (pathParts.any { it in setOf("series", "serie", "episodes") }) return StreamType.SERIES
        if ("live" in pathParts) return StreamType.LIVE

        val groupText = plain(group)
        val boundary = "(?:^|[\\s|:;/_\\-])"
        val ending = "(?:$|[\\s|:;/_\\-])"
        if (Regex("$boundary(?:series?|tv\\s*shows?|episodes?)$ending").containsMatchIn(groupText)) {
            return StreamType.SERIES
        }
        if (Regex("$boundary(?:vod|movies?|films?|filmes?|peliculas?)$ending").containsMatchIn(groupText)) {
            return StreamType.VOD
        }
        if (Regex("\\bs\\d{1,2}\\s*e\\d{1,3}\\b").containsMatchIn(plain(name))) return StreamType.SERIES
        if (duration != null && duration > 0) return StreamType.VOD
        return StreamType.LIVE
    }

    private fun parseAttributes(line: String): Map<String, String> =
        Regex("([A-Za-z][A-Za-z0-9_-]*)\\s*=\\s*[\"']([^\"']*)[\"']")
            .findAll(line)
            .associate { it.groupValues[1].lowercase() to it.groupValues[2].trim() }

    private fun attribute(line: String, key: String): String =
        parseAttributes(line)[key].orEmpty()

    private fun plain(value: String): String = Normalizer.normalize(value, Normalizer.Form.NFKD)
        .replace(Regex("\\p{M}+"), "")
        .lowercase()

    private fun inferQuality(name: String): String {
        val value = plain(name)
        return when {
            listOf("2160", "4k", "uhd").any(value::contains) -> "4K"
            listOf("1080", "fhd", "full hd").any(value::contains) -> "FHD"
            listOf("720", " hd").any(value::contains) -> "HD"
            listOf("576", "480", " sd").any(value::contains) -> "SD"
            else -> ""
        }
    }
}
