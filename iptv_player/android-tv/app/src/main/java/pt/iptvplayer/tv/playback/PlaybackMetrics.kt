package pt.iptvplayer.tv.playback

import android.util.Log

data class PlaybackSessionMetrics(
    val startupMillis: Long,
    val bufferingEvents: Int,
    val retries: Int,
    val failure: String? = null,
)

class PlaybackMetrics(private val clock: () -> Long = System::currentTimeMillis) {
    private val startedAt = clock()
    private var bufferingEvents = 0
    private var retries = 0

    fun buffering() { bufferingEvents++ }
    fun retry() { retries++ }

    fun snapshot(failure: String? = null) = PlaybackSessionMetrics(
        startupMillis = (clock() - startedAt).coerceAtLeast(0),
        bufferingEvents = bufferingEvents,
        retries = retries,
        failure = failure,
    )

    fun log(failure: String? = null) {
        val value = snapshot(failure)
        Log.i("PlaybackMetrics", "startup_ms=${value.startupMillis} buffering=${value.bufferingEvents} retries=${value.retries} failed=${failure != null}")
    }
}
