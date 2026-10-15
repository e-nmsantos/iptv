package pt.iptvplayer.tv.data

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test
import pt.iptvplayer.tv.model.Channel
import pt.iptvplayer.tv.model.StreamType

class ChannelCodecTest {
    @Test
    fun roundTripsEveryReplayField() {
        val channel = Channel(
            id = 42,
            name = "S01 E03 — Piloto",
            url = "http://server/series/user/pass/123.mkv",
            group = "Temporada 1",
            logo = "http://img/ep.jpg",
            tvgId = "xtream-episode:123",
            userAgent = "UA",
            referer = "http://ref/",
            type = StreamType.SERIES,
            quality = "FHD",
            customHeaders = mapOf("Authorization" to "Bearer x"),
        )
        assertEquals(channel, ChannelCodec.decode(ChannelCodec.encode(channel)))
    }

    @Test
    fun rejectsCorruptOrIncompleteRows() {
        assertNull(ChannelCodec.decode("not json"))
        assertNull(ChannelCodec.decode("""{"name":"","url":"http://x"}"""))
    }
}
