package pt.iptvplayer.tv.data

import android.util.Xml
import java.io.FilterInputStream
import java.io.InputStream
import java.net.HttpURLConnection
import java.net.URI
import java.text.SimpleDateFormat
import java.util.Locale
import java.util.TimeZone
import java.util.zip.GZIPInputStream
import org.xmlpull.v1.XmlPullParser
import pt.iptvplayer.tv.model.EpgProgram

/** Bounded streaming XMLTV reader retaining the useful current/future window. */
internal class EpgClient {
    fun loadSchedule(
        url: String,
        channelIds: Set<String>,
        nowMillis: Long = System.currentTimeMillis(),
        horizonMillis: Long = 48 * 60 * 60 * 1000L,
    ): List<EpgProgram> {
        if (url.isBlank() || channelIds.isEmpty()) return emptyList()
        val uri = runCatching { URI(url) }.getOrNull()
        require(uri?.scheme in setOf("http", "https") && !uri?.host.isNullOrBlank()) {
            "O endereço EPG tem de usar HTTP ou HTTPS."
        }
        val connection = uri!!.toURL().openConnection() as HttpURLConnection
        try {
            connection.connectTimeout = 15_000
            connection.readTimeout = 35_000
            connection.instanceFollowRedirects = true
            connection.setRequestProperty("User-Agent", "IPTVPlayerTV/0.9")
            connection.setRequestProperty("Accept-Encoding", "gzip")
            connection.connect()
            require(connection.responseCode in 200..299) { "O servidor EPG respondeu com HTTP ${connection.responseCode}." }
            val declared = connection.getHeaderField("Content-Length")?.toLongOrNull() ?: -1L
            require(declared < 0 || declared <= MAX_SOURCE_BYTES) { "A fonte EPG excede 100 MB." }
            val boundedSource = LimitedInputStream(connection.inputStream, MAX_SOURCE_BYTES)
            val source = if (
                connection.contentEncoding.equals("gzip", true) || url.lowercase().endsWith(".gz")
            ) {
                LimitedInputStream(GZIPInputStream(boundedSource), MAX_XML_BYTES)
            } else {
                boundedSource
            }
            return source.use { parseSchedule(it, channelIds, nowMillis, nowMillis + horizonMillis) }
        } finally {
            connection.disconnect()
        }
    }

    private fun parseSchedule(
        input: InputStream,
        channelIds: Set<String>,
        windowStart: Long,
        windowStop: Long,
    ): List<EpgProgram> {
        val parser = Xml.newPullParser().apply {
            setFeature(XmlPullParser.FEATURE_PROCESS_NAMESPACES, false)
            setInput(input, null)
        }
        val result = mutableListOf<EpgProgram>()
        var channelId = ""
        var start = 0L
        var stop = 0L
        var title = ""
        var description = ""
        var category = ""
        while (parser.eventType != XmlPullParser.END_DOCUMENT) {
            when (parser.eventType) {
                XmlPullParser.START_TAG -> when (parser.name) {
                    "programme" -> {
                        channelId = parser.getAttributeValue(null, "channel").orEmpty()
                        if (channelId in channelIds) {
                            start = parseTime(parser.getAttributeValue(null, "start").orEmpty())
                            stop = parseTime(parser.getAttributeValue(null, "stop").orEmpty())
                        } else {
                            start = 0L
                            stop = 0L
                        }
                        title = ""
                        description = ""
                        category = ""
                    }
                    "title" -> if (start > 0) title = parser.nextText().trim()
                    "desc" -> if (start > 0) description = parser.nextText().trim()
                    "category" -> if (start > 0) category = parser.nextText().trim()
                }
                XmlPullParser.END_TAG -> if (
                    parser.name == "programme" &&
                    channelId.isNotBlank() &&
                    stop > windowStart && start < windowStop
                ) {
                    result += EpgProgram(
                        channelId = channelId,
                        title = title.ifBlank { "Programa sem título" },
                        startMillis = start,
                        stopMillis = stop,
                        description = description,
                        category = category,
                    )
                }
            }
            parser.next()
        }
        return result
    }

    private fun parseTime(value: String): Long {
        val trimmed = value.trim()
        if (trimmed.length < 14) return 0L
        val hasZone = trimmed.length >= 20
        val format = SimpleDateFormat(if (hasZone) "yyyyMMddHHmmss Z" else "yyyyMMddHHmmss", Locale.US)
        if (!hasZone) format.timeZone = TimeZone.getTimeZone("UTC")
        return runCatching { format.parse(trimmed.take(if (hasZone) 20 else 14))?.time ?: 0L }.getOrDefault(0L)
    }

    private class LimitedInputStream(input: InputStream, private val limit: Long) : FilterInputStream(input) {
        private var total = 0L

        override fun read(): Int {
            val value = super.read()
            if (value >= 0) account(1)
            return value
        }

        override fun read(buffer: ByteArray, offset: Int, length: Int): Int {
            val count = super.read(buffer, offset, length)
            if (count > 0) account(count)
            return count
        }

        private fun account(count: Int) {
            total += count
            require(total <= limit) { "A fonte EPG excede o limite permitido." }
        }
    }

    companion object {
        private const val MAX_SOURCE_BYTES = 100L * 1024 * 1024
        private const val MAX_XML_BYTES = 256L * 1024 * 1024
    }
}
