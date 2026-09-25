package pt.iptvplayer.tv.model

data class CatalogProjection(
    val groups: List<String>,
    val visibleChannels: List<Channel>,
)

/** Compute catalog projection efficiently in a single pass. */
fun projectCatalog(
    channels: List<Channel>,
    seriesEpisodes: List<Channel>,
    seriesOpen: Boolean,
    selectedType: StreamType,
    selectedGroup: String,
    query: String,
): CatalogProjection {
    val active = if (selectedType == StreamType.SERIES && seriesOpen) seriesEpisodes else channels
    val normalizedQuery = query.trim()
    val isSeriesEpisodes = selectedType == StreamType.SERIES && seriesOpen
    val isAll = selectedGroup == "Todos" || selectedGroup.isBlank()
    val hasQuery = normalizedQuery.isNotBlank()

    val groupSet = sortedSetOf(String.CASE_INSENSITIVE_ORDER)
    val visible = ArrayList<Channel>()

    for (channel in active) {
        if (!isSeriesEpisodes && channel.type != selectedType) continue

        if (channel.group.isNotBlank()) {
            groupSet.add(channel.group)
        }

        val matchesGroup = isAll || channel.group.equals(selectedGroup, ignoreCase = true)
        if (!matchesGroup) continue

        val matchesQuery = !hasQuery ||
            channel.name.contains(normalizedQuery, ignoreCase = true) ||
            channel.group.contains(normalizedQuery, ignoreCase = true)

        if (matchesQuery) {
            visible.add(channel)
        }
    }

    val groups = listOf("Todos") + groupSet.toList()
    return CatalogProjection(groups, visible)
}
