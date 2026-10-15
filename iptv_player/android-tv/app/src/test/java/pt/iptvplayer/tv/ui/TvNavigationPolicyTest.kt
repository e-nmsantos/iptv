package pt.iptvplayer.tv.ui

import android.view.KeyEvent
import org.junit.Assert.assertEquals
import org.junit.Test

class TvNavigationPolicyTest {
    @Test
    fun playerKeysRemainPredictableForDpadAndRemoteControls() {
        assertEquals(PlayerKeyAction.OPEN_GUIDE, playerKeyAction(KeyEvent.KEYCODE_DPAD_LEFT, false))
        assertEquals(PlayerKeyAction.ZAP_PREVIOUS, playerKeyAction(KeyEvent.KEYCODE_DPAD_UP, false))
        assertEquals(PlayerKeyAction.ZAP_PREVIOUS, playerKeyAction(KeyEvent.KEYCODE_CHANNEL_DOWN, false))
        assertEquals(PlayerKeyAction.TOGGLE_FAVORITE, playerKeyAction(KeyEvent.KEYCODE_PROG_RED, true))
        assertEquals(PlayerKeyAction.RECALL_PREVIOUS, playerKeyAction(KeyEvent.KEYCODE_LAST_CHANNEL, false))
        assertEquals(PlayerKeyAction.DELEGATE, playerKeyAction(KeyEvent.KEYCODE_DPAD_RIGHT, true))
    }

    @Test
    fun vodPlaybackUsesLeftAndRightToSeekInsteadOfOpeningTheGuide() {
        assertEquals(
            PlayerKeyAction.SEEK_BACKWARD,
            playerKeyAction(KeyEvent.KEYCODE_DPAD_LEFT, guideVisible = false, isLive = false),
        )
        assertEquals(
            PlayerKeyAction.SEEK_FORWARD,
            playerKeyAction(KeyEvent.KEYCODE_DPAD_RIGHT, guideVisible = false, isLive = false),
        )
        assertEquals(
            PlayerKeyAction.SEEK_FORWARD,
            playerKeyAction(KeyEvent.KEYCODE_MEDIA_FAST_FORWARD, guideVisible = false, isLive = false),
        )
        assertEquals(
            PlayerKeyAction.LIVE_SEEK_FORWARD,
            playerKeyAction(KeyEvent.KEYCODE_MEDIA_FAST_FORWARD, guideVisible = false, isLive = true),
        )
        assertEquals(
            PlayerKeyAction.TOGGLE_SUBTITLES,
            playerKeyAction(KeyEvent.KEYCODE_CAPTIONS, guideVisible = false, isLive = false),
        )
    }

    @Test
    fun numberKeysZapOnlyOnLiveWithoutOverlays() {
        assertEquals(PlayerKeyAction.DIGIT, playerKeyAction(KeyEvent.KEYCODE_7, guideVisible = false, isLive = true))
        assertEquals(PlayerKeyAction.DIGIT, playerKeyAction(KeyEvent.KEYCODE_NUMPAD_3, guideVisible = false, isLive = true))
        assertEquals(PlayerKeyAction.DELEGATE, playerKeyAction(KeyEvent.KEYCODE_7, guideVisible = true, isLive = true))
        assertEquals(PlayerKeyAction.DELEGATE, playerKeyAction(KeyEvent.KEYCODE_7, guideVisible = false, isLive = false))
        assertEquals(7, digitForKey(KeyEvent.KEYCODE_7))
        assertEquals(3, digitForKey(KeyEvent.KEYCODE_NUMPAD_3))
        assertEquals(null, digitForKey(KeyEvent.KEYCODE_A))
    }

    @Test
    fun liveRightOpensChannelOptionsAndMediaNextDependsOnType() {
        assertEquals(PlayerKeyAction.SHOW_CONTROLS, playerKeyAction(KeyEvent.KEYCODE_DPAD_RIGHT, guideVisible = false, isLive = true))
        assertEquals(PlayerKeyAction.ZAP_NEXT, playerKeyAction(KeyEvent.KEYCODE_MEDIA_NEXT, guideVisible = false, isLive = true))
        assertEquals(PlayerKeyAction.NEXT_EPISODE, playerKeyAction(KeyEvent.KEYCODE_MEDIA_NEXT, guideVisible = false, isLive = false))
        assertEquals(PlayerKeyAction.RECALL_PREVIOUS, playerKeyAction(KeyEvent.KEYCODE_PROG_GREEN, guideVisible = false))
        assertEquals(PlayerKeyAction.TOGGLE_INFO, playerKeyAction(KeyEvent.KEYCODE_INFO, guideVisible = false))
    }

    @Test
    fun channelNumberEntryMapsToOneBasedPositions() {
        val entry = ChannelNumberEntry(maxDigits = 3)
        entry.push(1)
        assertEquals("12", entry.push(2))
        assertEquals(11, entry.commit(channelCount = 50))
        assertEquals("", entry.digits)
        entry.push(9)
        entry.push(9)
        assertEquals(null, entry.commit(channelCount = 50))
        entry.push(0)
        assertEquals(null, entry.commit(channelCount = 50))
        entry.push(1); entry.push(2); entry.push(3)
        assertEquals("4", entry.push(4))
    }
}
