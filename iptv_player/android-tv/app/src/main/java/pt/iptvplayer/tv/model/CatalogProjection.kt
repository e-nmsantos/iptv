package pt.iptvplayer.tv.model

data class CatalogProjection(
    val groups: List<String>,
    val visibleChannels: List<Channel>,
)

/** Compute catalog filters once per state change; Compose remembers the result. */
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
    val groups = active.asSequence()
        .filter { it.type == selectedType }
        .map { it.group }
        .distinct()
        .sortedBy { it.lowercase() }
        .toList()
    val visible = active.filter {
        it.type == selectedType &&
            (selectedGroup == "Todos" || it.group == selectedGroup) &&
            (normalizedQuery.isBlank() || it.name.contains(normalizedQuery, ignoreCase = true) ||
                it.group.contains(normalizedQuery, ignoreCase = true))
    }
    return CatalogProjection(listOf("Todos") + groups, visible)
}
