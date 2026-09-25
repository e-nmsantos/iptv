package pt.iptvplayer.tv.data

import java.io.BufferedInputStream
import java.io.ByteArrayOutputStream
import java.io.Closeable
import java.net.InetAddress
import java.net.ServerSocket
import java.net.SocketException
import java.net.URLDecoder
import java.nio.charset.StandardCharsets
import kotlin.concurrent.thread
import org.junit.Assert.assertEquals
import org.junit.Test
import pt.iptvplayer.tv.model.StreamType

class StalkerClientTest {
    @Test
    fun `loadCatalog authenticates and maps live channels`() {
        val server = FakeStalkerServer()
        try {
            val client = StalkerClient(
                SourceConfig(
                    type = SourceType.STALKER,
                    serverUrl = "http://127.0.0.1:${server.port}",
                    macAddress = "00:1A:79:12:34:56",
                ),
            )

            val playlist = client.loadCatalog()

            assertEquals("Stalker - 00:1A:79:12:34:56", playlist.name)
            assertEquals(1, playlist.channels.size)
            val channel = playlist.channels.single()
            assertEquals("Canal A", channel.name)
            assertEquals("Desporto", channel.group)
            assertEquals(StreamType.LIVE, channel.type)
            assertEquals("stalker-live://101", channel.url)
            assertEquals("http://127.0.0.1:${server.port}/c/", channel.referer)
        } finally {
            server.close()
        }
    }
}

private class FakeStalkerServer : Closeable {
    private val socket = ServerSocket(0, 8, InetAddress.getLoopbackAddress())
    val port: Int = socket.localPort
    @Volatile private var running = true
    private val worker = thread(name = "fake-stalker", isDaemon = true) {
        while (running) {
            try {
                socket.accept().use { client ->
                    val input = BufferedInputStream(client.getInputStream())
                    // Read the header block from the same buffered stream that
                    // will read the body, otherwise the reader's look-ahead can
                    // swallow the POST body and deadlock the request.
                    val header = ByteArrayOutputStream()
                    var match = 0
                    while (match < 4) {
                        val b = input.read()
                        if (b < 0) break
                        header.write(b)
                        match = when (match) {
                            0 -> if (b == '\r'.code) 1 else 0
                            1 -> if (b == '\n'.code) 2 else if (b == '\r'.code) 1 else 0
                            2 -> if (b == '\r'.code) 3 else 0
                            else -> if (b == '\n'.code) 4 else 0
                        }
                    }
                    val headerText = header.toString(StandardCharsets.US_ASCII.name())
                    val contentLength = Regex("(?i)content-length:\\s*(\\d+)")
                        .find(headerText)?.groupValues?.get(1)?.toIntOrNull() ?: 0
                    val bodyBytes = ByteArray(contentLength)
                    var read = 0
                    while (read < contentLength) {
                        val count = input.read(bodyBytes, read, contentLength - read)
                        if (count < 0) break
                        read += count
                    }
                    val body = String(bodyBytes, 0, read, StandardCharsets.UTF_8)
                    val params = body.split('&').associate {
                        val parts = it.split('=', limit = 2)
                        val key = URLDecoder.decode(parts.getOrElse(0) { "" }, StandardCharsets.UTF_8.name())
                        val value = URLDecoder.decode(parts.getOrElse(1) { "" }, StandardCharsets.UTF_8.name())
                        key to value
                    }
                    val payload = responseFor(params["action"].orEmpty())
                        .toByteArray(StandardCharsets.UTF_8)
                    client.getOutputStream().use { output ->
                        output.write(
                            ("HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n" +
                                "Content-Length: ${payload.size}\r\nConnection: close\r\n\r\n")
                                .toByteArray(StandardCharsets.US_ASCII),
                        )
                        output.write(payload)
                    }
                }
            } catch (error: SocketException) {
                if (running) throw error
            }
        }
    }

    private fun responseFor(action: String): String = when (action) {
        "handshake" -> """{"token":"tok123"}"""
        "get_profile" -> """{}"""
        "get_genres" -> """{"js":{"data":[{"id":"1","title":"Desporto"}]}}"""
        "get_all_channels" ->
            """{"js":{"data":[{"id":"1","name":"Canal A","cmd":"101","tv_genre_id":"1"}]}}"""
        else -> """{}"""
    }

    override fun close() {
        running = false
        socket.close()
        worker.join(1_000)
    }
}
