package pt.iptvplayer.tv.ui

import android.view.KeyEvent

internal enum class PlayerKeyAction {
    TOGGLE_GUIDE, OPEN_GUIDE, ZAP_PREVIOUS, ZAP_NEXT, PLAY_PAUSE, PLAY, PAUSE,
    TOGGLE_FAVORITE, SEEK_FORWARD, SEEK_BACKWARD, TOGGLE_SUBTITLES, SHOW_CONTROLS, RECALL_PREVIOUS, DELEGATE,
}

// `isLive` defaults to true so existing LIVE-focused call sites/tests keep their exact prior
// behavior; VOD/Séries playback passes isLive = false explicitly. `controlsVisible` gates
// D-pad keys to DELEGATE (normal Compose focus navigation) whenever the on-screen control bar
// is open, so its buttons — reachable with nothing but D-pad + OK — work identically on a
// full remote and on a bare D-pad-only one (no colour keys, no captions/media-transport keys).
internal fun playerKeyAction(
    keyCode: Int,
    guideVisible: Boolean,
    isLive: Boolean = true,
    controlsVisible: Boolean = false,
): PlayerKeyAction = when (keyCode) {
    KeyEvent.KEYCODE_LAST_CHANNEL -> PlayerKeyAction.RECALL_PREVIOUS
    KeyEvent.KEYCODE_GUIDE, KeyEvent.KEYCODE_MENU -> PlayerKeyAction.TOGGLE_GUIDE
    KeyEvent.KEYCODE_CAPTIONS -> PlayerKeyAction.TOGGLE_SUBTITLES
    KeyEvent.KEYCODE_MEDIA_FAST_FORWARD -> if (isLive) PlayerKeyAction.DELEGATE else PlayerKeyAction.SEEK_FORWARD
    KeyEvent.KEYCODE_MEDIA_REWIND -> if (isLive) PlayerKeyAction.DELEGATE else PlayerKeyAction.SEEK_BACKWARD
    KeyEvent.KEYCODE_DPAD_CENTER ->
        if (guideVisible || controlsVisible) PlayerKeyAction.DELEGATE
        else if (isLive) PlayerKeyAction.OPEN_GUIDE
        else PlayerKeyAction.SHOW_CONTROLS
    KeyEvent.KEYCODE_DPAD_LEFT -> when {
        guideVisible || controlsVisible -> PlayerKeyAction.DELEGATE
        isLive -> PlayerKeyAction.OPEN_GUIDE
        else -> PlayerKeyAction.SEEK_BACKWARD
    }
    KeyEvent.KEYCODE_DPAD_RIGHT -> when {
        guideVisible || controlsVisible || isLive -> PlayerKeyAction.DELEGATE
        else -> PlayerKeyAction.SEEK_FORWARD
    }
    KeyEvent.KEYCODE_CHANNEL_UP -> PlayerKeyAction.ZAP_NEXT
    KeyEvent.KEYCODE_CHANNEL_DOWN -> PlayerKeyAction.ZAP_PREVIOUS
    KeyEvent.KEYCODE_DPAD_UP -> when {
        guideVisible || controlsVisible -> PlayerKeyAction.DELEGATE
        isLive -> PlayerKeyAction.ZAP_PREVIOUS
        else -> PlayerKeyAction.SHOW_CONTROLS
    }
    KeyEvent.KEYCODE_DPAD_DOWN -> when {
        guideVisible || controlsVisible -> PlayerKeyAction.DELEGATE
        isLive -> PlayerKeyAction.ZAP_NEXT
        else -> PlayerKeyAction.SHOW_CONTROLS
    }
    KeyEvent.KEYCODE_MEDIA_PLAY_PAUSE -> PlayerKeyAction.PLAY_PAUSE
    KeyEvent.KEYCODE_MEDIA_PLAY -> PlayerKeyAction.PLAY
    KeyEvent.KEYCODE_MEDIA_PAUSE -> PlayerKeyAction.PAUSE
    KeyEvent.KEYCODE_PROG_RED, KeyEvent.KEYCODE_BOOKMARK -> PlayerKeyAction.TOGGLE_FAVORITE
    else -> PlayerKeyAction.DELEGATE
}
