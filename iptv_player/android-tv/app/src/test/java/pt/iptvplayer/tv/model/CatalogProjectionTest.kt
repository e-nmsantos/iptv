package pt.iptvplayer.tv.model

import org.junit.Assert.assertEquals
import org.junit.Test

class CatalogProjectionTest {
    @Test
    fun `filters type group and query in one projection`() {
        val channels = listOf(
            Channel(name = "RTP Notícias", url = "one", group = "Portugal"),
            Channel(name = "Filme", url = "two", group = "Cinema", type = StreamType.VOD),
            Channel(name = "BBC News", url = "three", group = "Internacional"),
        )

        val projection = projectCatalog(
            channels = channels,
            seriesEpisodes = emptyList(),
            seriesOpen = false,
            selectedType = StreamType.LIVE,
            selectedGroup = "Portugal",
            query = "notícias",
        )

        assertEquals(listOf("Todos", "Internacional", "Portugal"), projection.groups)
        assertEquals(listOf("RTP Notícias"), projection.visibleChannels.map(Channel::name))
    }
}
