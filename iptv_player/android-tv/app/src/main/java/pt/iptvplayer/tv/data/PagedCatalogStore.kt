package pt.iptvplayer.tv.data

import pt.iptvplayer.tv.model.Channel
import pt.iptvplayer.tv.model.StreamType

data class CatalogPage(
    val channels: List<Channel>,
    val groups: List<String>,
    val total: Int,
    val offset: Int,
) {
    val hasMore: Boolean get() = offset + channels.size < total
}

/** Persistence seam implemented by SQLite today and by a Room DAO later. */
interface PagedCatalogStore {
    fun catalogPage(
        playlistId: Long,
        type: StreamType,
        group: String = "Todos",
        query: String = "",
        offset: Int = 0,
        limit: Int = 240,
    ): CatalogPage
}
