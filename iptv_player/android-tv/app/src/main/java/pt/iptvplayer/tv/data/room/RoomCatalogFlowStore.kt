package pt.iptvplayer.tv.data.room

import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.map
import pt.iptvplayer.tv.data.CatalogPage
import pt.iptvplayer.tv.model.Channel
import pt.iptvplayer.tv.model.StreamType
import pt.iptvplayer.tv.model.EpgProgram

/** Read-only Flow adapter used during the gradual SQLiteOpenHelper-to-Room migration. */
class RoomCatalogFlowStore(private val dao: RoomCatalogDao) {
    private fun RoomCatalogRow.toChannel() = Channel(
        id = id,
        name = name,
        url = "secure-channel://$id",
        group = groupName,
        logo = logo,
        tvgId = tvgId,
        type = runCatching { StreamType.valueOf(streamType) }.getOrDefault(StreamType.LIVE),
        quality = quality,
        favorite = favorite == 1,
    )

    fun observePage(
        playlistId: Long,
        type: StreamType,
        group: String = "Todos",
        query: String = "",
        offset: Int = 0,
        limit: Int = 240,
    ): Flow<CatalogPage> = combine(
        dao.observePage(playlistId, type.name, group, query.trim(), offset, limit),
        dao.observeCount(playlistId, type.name, group, query.trim()),
        dao.observeGroups(playlistId, type.name),
    ) { rows, total, groups ->
        CatalogPage(
            channels = rows.map { it.toChannel() },
            groups = listOf("Todos") + groups,
            total = total,
            offset = offset,
        )
    }

    fun observeFavorites(playlistId: Long): Flow<List<Channel>> =
        dao.observeFavorites(playlistId).map { rows -> rows.map { it.toChannel() } }

    fun observeEpg(
        playlistId: Long,
        fromMillis: Long,
        toMillis: Long,
    ): Flow<Map<String, List<EpgProgram>>> = dao.observeEpg(playlistId, fromMillis, toMillis)
        .map { rows ->
            rows.groupBy(RoomEpgProgrammeEntity::channelId).mapValues { (_, items) ->
                items.map { item ->
                    EpgProgram(
                        item.channelId,
                        item.title,
                        item.startMillis,
                        item.stopMillis,
                        item.description,
                        item.category,
                        item.catchupUrl,
                    )
                }
            }
        }
}
