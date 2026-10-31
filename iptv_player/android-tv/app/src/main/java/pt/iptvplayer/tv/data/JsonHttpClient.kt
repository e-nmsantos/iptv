package pt.iptvplayer.tv.data

import java.io.ByteArrayOutputStream
import java.net.HttpURLConnection
import java.net.URI
import java.net.URLEncoder
import java.nio.charset.StandardCharsets
import java.util.zip.GZIPInputStream

internal class JsonHttpClient(
    private val userAgent: String,
    private val defaultHeaders: Map<String, String> = emptyMap(),
) {
    fun get(url: String, params: Map<String, String> = emptyMap()): String =
        request(urlWithParams(url, params), "GET", null)

    fun post(url: String, fields: Map<String, String>): String {
        val body = fields.entries.joinToString("&") { (key, value) ->
            "${encode(key)}=${encode(value)}"
        }
        return request(url, "POST", body)
    }

    private fun request(url: String, method: String, body: String?): String {
        var currentUrl = url
        var currentMethod = method
        var currentBody = body
        var redirects = 0
        var connection: HttpURLConnection? = null
        try {
            while (redirects < 5) {
                val uri = URI(currentUrl)
                require(uri.scheme in setOf("http", "https") && !uri.host.isNullOrBlank()) { "Endereço de servidor inválido." }
                val conn = uri.toURL().openConnection() as HttpURLConnection
                conn.requestMethod = currentMethod
                conn.connectTimeout = 15_000
                conn.readTimeout = 35_000
                conn.instanceFollowRedirects = false
                conn.setRequestProperty("User-Agent", userAgent)
                conn.setRequestProperty("Accept", "application/json, text/plain, */*")
                conn.setRequestProperty("Accept-Encoding", "gzip")
                for ((key, value) in defaultHeaders) conn.setRequestProperty(key, value)
                if (currentBody != null) {
                    conn.doOutput = true
                    conn.setRequestProperty("Content-Type", "application/x-www-form-urlencoded; charset=utf-8")
                    conn.outputStream.use { it.write(currentBody.toByteArray(StandardCharsets.UTF_8)) }
                }
                val code = conn.responseCode
                if (code in setOf(HttpURLConnection.HTTP_MOVED_PERM, HttpURLConnection.HTTP_MOVED_TEMP, HttpURLConnection.HTTP_SEE_OTHER, 307, 308)) {
                    val location = conn.getHeaderField("Location")
                    conn.disconnect()
                    if (!location.isNullOrBlank()) {
                        currentUrl = uri.resolve(location).toString()
                        if (code == HttpURLConnection.HTTP_SEE_OTHER) {
                            currentMethod = "GET"
                            currentBody = null
                        }
                        redirects++
                        continue
                    }
                }
                connection = conn
                break
            }
            val finalConn = connection ?: error("Não foi possível estabelecer ligação.")
            val status = finalConn.responseCode
            val raw = if (status in 200..299) finalConn.inputStream else finalConn.errorStream
            val stream = if (raw != null && finalConn.contentEncoding.equals("gzip", true)) GZIPInputStream(raw) else raw
            val response = stream?.use(::readBounded).orEmpty()
            require(status in 200..299) { "O servidor respondeu com HTTP $status." }
            return response
        } finally {
            connection?.disconnect()
        }
    }

    private fun readBounded(input: java.io.InputStream): String {
        val output = ByteArrayOutputStream()
        val buffer = ByteArray(32 * 1024)
        var total = 0
        while (true) {
            val count = input.read(buffer)
            if (count < 0) break
            total += count
            require(total <= MAX_RESPONSE_BYTES) { "A resposta do servidor é demasiado grande." }
            output.write(buffer, 0, count)
        }
        return output.toString(StandardCharsets.UTF_8.name())
    }

    companion object {
        private const val MAX_RESPONSE_BYTES = 100 * 1024 * 1024
        fun encode(value: String): String = URLEncoder.encode(value, StandardCharsets.UTF_8.name())
        fun urlWithParams(url: String, params: Map<String, String>): String {
            if (params.isEmpty()) return url
            return url + (if ('?' in url) "&" else "?") + params.entries.joinToString("&") {
                "${encode(it.key)}=${encode(it.value)}"
            }
        }
    }
}
