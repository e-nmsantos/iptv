package pt.iptvplayer.tv.data

import java.io.BufferedReader
import java.io.Closeable
import java.io.InputStreamReader
import java.net.InetAddress
import java.net.ServerSocket
import java.net.SocketException
import java.nio.charset.StandardCharsets
import kotlin.concurrent.thread
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import pt.iptvplayer.tv.model.StreamType
import pt.iptvplayer.tv.model.Channel

class ConnectionClientTest {
    @Test
    fun `playback headers include portal authentication headers`() {
        val channel = Channel(
            name = "Canal",
            url = "https://stream.example/live",
            userAgent = "MAG",
            referer = "https://portal.example/c/",
            customHeaders = mapOf("Cookie" to "mac=00:00", "Authorization" to "Bearer token"),
        )
        assertEquals("MAG", channel.requestHeaders["User-Agent"])
        assertEquals("mac=00:00", channel.requestHeaders["Cookie"])
        assertEquals("Bearer token", channel.requestHeaders["Authorization"])
    }

    @Test
    fun `normalizes xtream server without changing explicit protocol`() {
        assertEquals("https://provider.example", XtreamClient.normalizeBaseUrl("provider.example/"))
        assertEquals("http://provider.example:8080", XtreamClient.normalizeBaseUrl("http://provider.example:8080/"))
    }

    @Test
    fun `normalizes stalker portal and mac`() {
        assertEquals("http://portal.example:80", StalkerClient.normalizePortal("portal.example:80/c/"))
        assertEquals("00:1A:79:12:34:56", StalkerClient.normalizeMac("00-1a-79-12-34-56"))
    }

    @Test(expected = IllegalArgumentException::class)
    fun `rejects invalid stalker mac`() {
        StalkerClient.normalizeMac("invalid")
    }

    @Test
    fun `loads xtream catalog and episodes`() {
        val server = FakeXtreamServer { action, port ->
            when (action) {
                    "get_live_categories" -> """[{"category_id":"1","category_name":"TV"}]"""
                    "get_vod_categories" -> """[{"category_id":"2","category_name":"Filmes"}]"""
                    "get_series_categories" -> """[{"category_id":"3","category_name":"Séries"}]"""
                    "get_live_streams" -> """[{"stream_id":10,"name":"Canal","category_id":"1"}]"""
                    "get_vod_streams" -> """[{"stream_id":20,"name":"Filme","category_id":"2","container_extension":"mkv"}]"""
                    "get_series" -> """[{"series_id":30,"name":"Série","category_id":"3"}]"""
                    "get_series_info" -> """{"episodes":{"1":[{"id":31,"title":"Episódio","episode_num":1,"container_extension":"mp4"}]}}"""
                    else -> """{"user_info":{"auth":1},"server_info":{"url":"127.0.0.1","server_protocol":"http","port":"$port"}}"""
            }
        }
        try {
            val source = SourceConfig(
                SourceType.XTREAM,
                "http://127.0.0.1:${server.port}",
                "user",
                "pass",
            )
            val client = XtreamClient(source)
            val catalog = client.loadCatalog()
            assertEquals(listOf(StreamType.LIVE, StreamType.VOD, StreamType.SERIES), catalog.channels.map { it.type })
            assertTrue(catalog.channels[0].url.contains("/live/user/pass/10.ts"))
            assertEquals("Episódio", client.loadEpisodes("30").single().name)
        } finally {
            server.close()
        }
    }
}

private class FakeXtreamServer(
    private val responseFor: (action: String, port: Int) -> String,
) : Closeable {
    private val socket = ServerSocket(0, 8, InetAddress.getLoopbackAddress())
    val port: Int = socket.localPort
    @Volatile private var running = true
    private val worker = thread(name = "fake-xtream", isDaemon = true) {
        while (running) {
            try {
                socket.accept().use { client ->
                    val reader = BufferedReader(InputStreamReader(client.getInputStream(), StandardCharsets.US_ASCII))
                    val requestLine = reader.readLine().orEmpty()
                    while (!reader.readLine().isNullOrEmpty()) Unit
                    val target = requestLine.split(' ').getOrElse(1) { "" }
                    val action = Regex("(?:[?&])action=([^&]*)").find(target)?.groupValues?.get(1).orEmpty()
                    val payload = responseFor(action, port).toByteArray(StandardCharsets.UTF_8)
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

    override fun close() {
        running = false
        socket.close()
        worker.join(1_000)
    }
}
