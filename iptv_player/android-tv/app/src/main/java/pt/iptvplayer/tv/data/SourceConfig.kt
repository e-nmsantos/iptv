package pt.iptvplayer.tv.data

enum class SourceType { M3U, XTREAM, STALKER }

data class SourceConfig(
    val type: SourceType,
    val serverUrl: String,
    val username: String = "",
    val password: String = "",
    val macAddress: String = "",
)
