package pt.iptvplayer.tv.model

data class EpgProgram(
    val channelId: String,
    val title: String,
    val startMillis: Long,
    val stopMillis: Long,
    val description: String = "",
    val category: String = "",
    val catchupUrl: String = "",
)
