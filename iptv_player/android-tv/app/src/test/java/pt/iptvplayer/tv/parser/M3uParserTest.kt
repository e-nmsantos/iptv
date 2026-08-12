package pt.iptvplayer.tv.parser

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import pt.iptvplayer.tv.model.StreamType

class M3uParserTest {
    private val parser = M3uParser()

    @Test
    fun `separates live vod and series`() {
        val playlist = parser.parse(
            """#EXTM3U x-tvg-url="https://guide.example/epg.xml"
            #EXTINF:-1 tvg-id="news" group-title="Portugal",Notícias HD
            https://provider.example/live/user/pass/1.ts
            #EXTINF:-1 group-title="Filmes",Um Filme
            https://provider.example/movie/user/pass/2.mp4
            #EXTINF:-1 group-title="Séries",Uma Série S02E03
            https://provider.example/series/user/pass/3.mkv
            """.trimIndent(),
            "Teste",
        )

        assertEquals(listOf(StreamType.LIVE, StreamType.VOD, StreamType.SERIES), playlist.channels.map { it.type })
        assertEquals("https://guide.example/epg.xml", playlist.epgUrl)
        assertEquals("HD", playlist.channels.first().quality)
    }

    @Test
    fun `explicit metadata wins over extension`() {
        val type = parser.inferStreamType(
            url = "https://provider.example/content/video.mp4",
            explicitType = "live",
        )
        assertEquals(StreamType.LIVE, type)
    }

    @Test
    fun `reads playback headers without exposing them in the title`() {
        val playlist = parser.parse(
            """#EXTM3U
            #EXTINF:-1 user-agent="LivingRoom" referer="https://portal.example/",Canal
            https://stream.example/live
            """.trimIndent(),
        )
        val channel = playlist.channels.single()
        assertEquals("LivingRoom", channel.userAgent)
        assertEquals("https://portal.example/", channel.referer)
        assertTrue(channel.requestHeaders.containsKey("Referer"))
    }

    @Test
    fun `streams one hundred thousand channels without retaining a catalog list`() {
        val content = buildString(9_000_000) {
            appendLine("#EXTM3U x-tvg-url=\"https://guide.example/epg.xml\"")
            repeat(100_000) { index ->
                appendLine("#EXTINF:-1 tvg-id=\"channel-$index\",Canal $index")
                appendLine("https://provider.example/live/$index.ts")
            }
        }
        var received = 0
        val result = parser.parse(content.reader()) { received++ }

        assertEquals(100_000, received)
        assertEquals(100_000, result.channelCount)
        assertEquals("https://guide.example/epg.xml", result.epgUrl)
    }

    @Test(expected = IllegalArgumentException::class)
    fun `rejects non m3u content`() {
        parser.parse("not a playlist")
    }
}
