package pt.iptvplayer.tv.playback

import org.junit.Assert.assertEquals
import org.junit.Test

class PlaybackMetricsTest {
    @Test
    fun recordsStartupBufferingRetriesAndFailureWithoutUrls() {
        var now = 100L
        val metrics = PlaybackMetrics { now }
        metrics.buffering()
        metrics.retry()
        now = 350L
        val value = metrics.snapshot("HTTP 503")

        assertEquals(250L, value.startupMillis)
        assertEquals(1, value.bufferingEvents)
        assertEquals(1, value.retries)
        assertEquals("HTTP 503", value.failure)
    }
}
