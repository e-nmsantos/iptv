package pt.iptvplayer.tv.pairing

import java.net.HttpURLConnection
import java.net.InetAddress
import java.net.URLEncoder
import java.net.URL
import java.nio.charset.StandardCharsets
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class PairingServerTest {
    @Test
    fun `serves form and accepts one playlist url`() {
        val received = mutableListOf<PairingPayload>()
        val latch = CountDownLatch(1)
        val server = PairingServer(InetAddress.getLoopbackAddress())
        try {
            val session = server.start(onPayloadReceived = { payload ->
                received += payload
                latch.countDown()
            })

            val get = URL(session.url).openConnection() as HttpURLConnection
            assertEquals(200, get.responseCode)
            val page = get.inputStream.bufferedReader().readText()
            assertTrue(page.contains("Enviar ligação para a TV"))
            assertTrue(page.contains("Xtream Codes"))
            assertTrue(page.contains("Stalker Portal"))

            val playlistUrl = "https://provider.example/list.m3u?token=secret"
            val body = "source_type=m3u&url=" + URLEncoder.encode(playlistUrl, StandardCharsets.UTF_8.name())
            val post = URL(session.url).openConnection() as HttpURLConnection
            post.requestMethod = "POST"
            post.doOutput = true
            post.setRequestProperty("Content-Type", "application/x-www-form-urlencoded")
            post.outputStream.use { it.write(body.toByteArray()) }
            assertEquals(200, post.responseCode)
            assertTrue(post.inputStream.bufferedReader().readText().contains("Lista enviada"))

            assertTrue(latch.await(2, TimeUnit.SECONDS))
            assertEquals(listOf(PairingPayload(PairingSourceType.M3U, playlistUrl)), received)
        } finally {
            server.close()
        }
    }

    @Test
    fun `accepts credential free desktop sync state`() {
        val received = mutableListOf<PairingPayload>()
        val latch = CountDownLatch(1)
        val server = PairingServer(InetAddress.getLoopbackAddress())
        try {
            val session = server.start(onPayloadReceived = { payload ->
                received += payload
                latch.countDown()
            })
            val sync = """{"schema_version":1,"favorites":["media:abc"],"progress":{}}"""
            val body = "source_type=sync&sync_data=" +
                URLEncoder.encode(sync, StandardCharsets.UTF_8.name())
            val post = URL(session.url).openConnection() as HttpURLConnection
            post.requestMethod = "POST"
            post.doOutput = true
            post.outputStream.use { it.write(body.toByteArray()) }

            assertEquals(200, post.responseCode)
            assertTrue(latch.await(2, TimeUnit.SECONDS))
            assertEquals(PairingSourceType.SYNC, received.single().type)
            assertEquals(sync, received.single().syncData)
        } finally {
            server.close()
        }
    }

    @Test
    fun `exports escaped credential free tv state on local page`() {
        val state = """{"schema_version":1,"favorites":["media:<safe>"],"progress":{}}"""
        val server = PairingServer(InetAddress.getLoopbackAddress(), exportData = state)
        try {
            val session = server.start(onPayloadReceived = {})
            val get = URL(session.url).openConnection() as HttpURLConnection
            val page = get.inputStream.bufferedReader().readText()

            assertEquals(200, get.responseCode)
            assertTrue(page.contains("Enviar estado da TV"))
            assertTrue(page.contains("media:&lt;safe&gt;"))
            assertTrue(!page.contains("media:<safe>"))
        } finally {
            server.close()
        }
    }

    @Test
    fun `desktop syncs with the pin and wrong pins end the session`() {
        val state = """{"schema_version":1,"favorites":["media:tv"],"progress":{}}"""
        val received = mutableListOf<PairingPayload>()
        val latch = CountDownLatch(1)
        val server = PairingServer(InetAddress.getLoopbackAddress(), exportData = state)
        try {
            val session = server.start(onPayloadReceived = { received += it; latch.countDown() })
            assertEquals(6, session.pin.length)
            val base = "http://127.0.0.1:${session.port}/sync/"

            val get = URL(base + session.pin).openConnection() as HttpURLConnection
            assertEquals(200, get.responseCode)
            assertEquals(state, get.inputStream.bufferedReader().readText())

            val sync = """{"schema_version":1,"favorites":["media:pc"],"progress":{}}"""
            val post = URL(base + session.pin).openConnection() as HttpURLConnection
            post.requestMethod = "POST"
            post.doOutput = true
            post.outputStream.use {
                it.write(("source_type=sync&sync_data=" + URLEncoder.encode(sync, StandardCharsets.UTF_8.name())).toByteArray())
            }
            assertEquals(200, post.responseCode)
            assertTrue(latch.await(2, TimeUnit.SECONDS))
            assertEquals(sync, received.single().syncData)
        } finally {
            server.close()
        }
    }

    @Test
    fun `five wrong pins close the pairing session`() {
        val server = PairingServer(InetAddress.getLoopbackAddress())
        try {
            val session = server.start(onPayloadReceived = {})
            val wrong = if (session.pin == "111111") "222222" else "111111"
            repeat(5) {
                val get = URL("http://127.0.0.1:${session.port}/sync/$wrong").openConnection() as HttpURLConnection
                assertEquals(403, get.responseCode)
            }
            Thread.sleep(1_500)
            val after = runCatching {
                (URL("http://127.0.0.1:${session.port}/sync/${session.pin}").openConnection() as HttpURLConnection)
                    .apply { connectTimeout = 1_000; readTimeout = 1_000 }.responseCode
            }.getOrNull()
            assertTrue("session should be closed, got $after", after == null)
        } finally {
            server.close()
        }
    }
}
