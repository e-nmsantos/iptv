package pt.iptvplayer.tv.model

enum class StreamType { LIVE, VOD, SERIES }

data class Channel(
    val id: Long = 0,
    val name: String,
    val url: String,
    val group: String = "Geral",
    val logo: String = "",
    val tvgId: String = "",
    val userAgent: String = "",
    val referer: String = "",
    val type: StreamType = StreamType.LIVE,
    val quality: String = "",
    val favorite: Boolean = false,
    val resumePositionMs: Long = 0,
    val customHeaders: Map<String, String> = emptyMap(),
) {
    val requestHeaders: Map<String, String>
        get() = buildMap {
            if (userAgent.isNotBlank()) put("User-Agent", userAgent)
            if (referer.isNotBlank()) put("Referer", referer)
            putAll(customHeaders)
        }
}

data class Playlist(
    val name: String,
    val channels: List<Channel>,
    val epgUrl: String = "",
)

data class PlaylistSummary(
    val id: Long,
    val name: String,
    val sourceLabel: String,
    val channelCount: Int,
    val updatedAtMillis: Long,
    val active: Boolean,
)
