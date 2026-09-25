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
            PlayerKeyAction.DELEGATE,
            playerKeyAction(KeyEvent.KEYCODE_MEDIA_FAST_FORWARD, guideVisible = false, isLive = true),
        )
        assertEquals(
            PlayerKeyAction.TOGGLE_SUBTITLES,
            playerKeyAction(KeyEvent.KEYCODE_CAPTIONS, guideVisible = false, isLive = false),
        )
    }
}
