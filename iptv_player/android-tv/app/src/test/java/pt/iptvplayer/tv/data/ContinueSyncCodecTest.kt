package pt.iptvplayer.tv.data

import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import pt.iptvplayer.tv.model.Channel
import pt.iptvplayer.tv.model.StreamType
import pt.iptvplayer.tv.model.WatchHistoryItem

class ContinueSyncCodecTest {
    private fun item(channel: Channel, parent: Channel?, upNext: Boolean = false) = WatchHistoryItem(
        mediaKey = "k",
        channel = channel,
        parent = parent,
        title = channel.name,
        subtitle = "",
        artwork = "",
        positionMs = 600_000,
        durationMs = 2_400_000,
        upNext = upNext,
        playedAtMillis = 1_700_000_000_000,
    )

    @Test
    fun xtreamEpisodeTravelsWithoutItsCredentialedUrl() {
        val episode = Channel(
            name = "Piloto",
            url = "http://srv:8080/series/user/secret/9.mkv",
            group = "Temporada 1",
            tvgId = "xtream-episode:9",
            type = StreamType.SERIES,
        )
        val show = Channel(name = "Série X", url = "catalog://xtream/series/77", logo = "poster", type = StreamType.SERIES)
        val json = ContinueSyncCodec.encode(item(episode, show)) { null }!!
        assertFalse(json.toString().contains("secret"))

        val decoded = ContinueSyncCodec.decode(JSONObject(json.toString())) as ContinueEntry.XtreamEpisode
        assertEquals("9", decoded.episodeId)
        assertEquals("mkv", decoded.extension)
        assertEquals(1, decoded.season)
        assertEquals("77", decoded.seriesId)
        assertEquals(600_000, decoded.positionMs)
        assertEquals("catalog://xtream/series/77", ContinueSyncCodec.xtreamSeriesReference(decoded).url)

        val url = ContinueSyncCodec.xtreamEpisodeUrl("9", "mkv")
        assertEquals("9" to "mkv", ContinueSyncCodec.parseXtreamEpisodeUrl(url))
    }

    @Test
    fun stalkerEpisodeAndDesktopFormatDecode() {
        val episode = Channel(
            name = "S02 E03",
            url = "stalker-series://x?episode=3",
            group = "Temporada 2",
            tvgId = "stalker-episode:eyJzIjoxfQ==#3",
            type = StreamType.SERIES,
        )
        val show = Channel(name = "Show", url = "catalog://stalker/series/7/44", type = StreamType.SERIES)
        val json = ContinueSyncCodec.encode(item(episode, show, upNext = true)) { null }!!
        val decoded = ContinueSyncCodec.decode(json) as ContinueEntry.StalkerEpisode
        assertEquals("eyJzIjoxfQ==", decoded.cmd)
        assertEquals("3", decoded.episode)
        assertEquals("7", decoded.seriesCategory)
        assertEquals("44", decoded.seriesId)
        assertTrue(decoded.upNext)

        // Shape produced by the desktop app.
        val desktop = JSONObject(
            """{"kind":"episode","source":"xtream","episode_id":"12","ext":"mp4","season":3,
               "series_id":"5","series_name":"S","title":"T","position_ms":1,"duration_ms":2,
               "up_next":false,"played_at":5}""",
        )
        assertEquals("12", (ContinueSyncCodec.decode(desktop) as ContinueEntry.XtreamEpisode).episodeId)
    }

    @Test
    fun catalogItemsUseTheSharedKeyAndJunkIsRejected() {
        val film = Channel(id = 4, name = "Filme", url = "secure-channel://4", group = "Ação", type = StreamType.VOD)
        val json = ContinueSyncCodec.encode(item(film, null)) { "media:abc" }!!
        assertEquals("media:abc", (ContinueSyncCodec.decode(json) as ContinueEntry.Catalog).key)

        assertNull(ContinueSyncCodec.decode(JSONObject("""{"kind":"catalog","key":"nope"}""")))
        assertNull(ContinueSyncCodec.decode(JSONObject("""{"kind":"episode","source":"xtream"}""")))
        assertNull(ContinueSyncCodec.decode(JSONObject("""{"kind":"mystery"}""")))
    }

    @Test
    fun episodeKeysIgnoreSeasonLabels() {
        val tv = Channel(name = "Piloto", url = "a", group = "Temporada 1", tvgId = "xtream-episode:9", type = StreamType.SERIES)
        val desktopShaped = tv.copy(name = "Pilot", group = "Series - S01")
        assertEquals(playbackMediaKey(tv), playbackMediaKey(desktopShaped))
    }
}
