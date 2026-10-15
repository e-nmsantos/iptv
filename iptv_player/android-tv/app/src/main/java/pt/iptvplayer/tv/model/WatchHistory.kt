package pt.iptvplayer.tv.model

/** One "Continuar a ver" entry: something in progress, or the episode queued after one that ended. */
data class WatchHistoryItem(
    val mediaKey: String,
    val channel: Channel,
    /** The series the episode belongs to, so "next episode" still works when resumed from Início. */
    val parent: Channel?,
    val title: String,
    val subtitle: String,
    val artwork: String,
    val positionMs: Long,
    val durationMs: Long,
    val upNext: Boolean,
    val playedAtMillis: Long,
) {
    val progress: Float
        get() = if (durationMs > 0) (positionMs.toFloat() / durationMs).coerceIn(0f, 1f) else 0f
}

/** A programme the user asked to be reminded of; [channel] is the live channel to tune to. */
data class EpgReminder(
    val channel: Channel,
    val tvgId: String,
    val title: String,
    val startMillis: Long,
    val stopMillis: Long,
)

/** Where an episode sits in its series, used to find what to play next. */
data class EpisodeContext(
    val series: Channel,
    val episodes: List<Channel>,
)
