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
        assertEquals(PlayerKeyAction.DELEGATE, playerKeyAction(KeyEvent.KEYCODE_DPAD_RIGHT, true))
    }
}
