package pt.iptvplayer.tv.ui

import android.view.KeyEvent

internal enum class PlayerKeyAction {
    TOGGLE_GUIDE, OPEN_GUIDE, ZAP_PREVIOUS, ZAP_NEXT, PLAY_PAUSE, PLAY, PAUSE,
    TOGGLE_FAVORITE, SEEK_FORWARD, SEEK_BACKWARD, TOGGLE_SUBTITLES, SHOW_CONTROLS, RECALL_PREVIOUS,
    DIGIT, TOGGLE_INFO, TOGGLE_STATS, OPEN_AUDIO, LIVE_SEEK_BACKWARD, LIVE_SEEK_FORWARD, NEXT_EPISODE,
    DELEGATE,
}

/** Digit 0–9 for number keys (top row or numeric keypad), or null for any other key. */
internal fun digitForKey(keyCode: Int): Int? = when (keyCode) {
    in KeyEvent.KEYCODE_0..KeyEvent.KEYCODE_9 -> keyCode - KeyEvent.KEYCODE_0
    in KeyEvent.KEYCODE_NUMPAD_0..KeyEvent.KEYCODE_NUMPAD_9 -> keyCode - KeyEvent.KEYCODE_NUMPAD_0
    else -> null
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
    KeyEvent.KEYCODE_INFO -> PlayerKeyAction.TOGGLE_INFO
    KeyEvent.KEYCODE_PROG_BLUE -> PlayerKeyAction.TOGGLE_STATS
    KeyEvent.KEYCODE_PROG_YELLOW -> PlayerKeyAction.OPEN_AUDIO
    KeyEvent.KEYCODE_PROG_GREEN -> PlayerKeyAction.RECALL_PREVIOUS
    KeyEvent.KEYCODE_MEDIA_FAST_FORWARD ->
        if (isLive) PlayerKeyAction.LIVE_SEEK_FORWARD else PlayerKeyAction.SEEK_FORWARD
    KeyEvent.KEYCODE_MEDIA_REWIND ->
        if (isLive) PlayerKeyAction.LIVE_SEEK_BACKWARD else PlayerKeyAction.SEEK_BACKWARD
    KeyEvent.KEYCODE_MEDIA_NEXT -> if (isLive) PlayerKeyAction.ZAP_NEXT else PlayerKeyAction.NEXT_EPISODE
    KeyEvent.KEYCODE_MEDIA_PREVIOUS -> if (isLive) PlayerKeyAction.ZAP_PREVIOUS else PlayerKeyAction.DELEGATE
    KeyEvent.KEYCODE_DPAD_CENTER, KeyEvent.KEYCODE_ENTER, KeyEvent.KEYCODE_NUMPAD_ENTER ->
        if (guideVisible || controlsVisible) PlayerKeyAction.DELEGATE
        else if (isLive) PlayerKeyAction.OPEN_GUIDE
        else PlayerKeyAction.SHOW_CONTROLS
    KeyEvent.KEYCODE_DPAD_LEFT -> when {
        guideVisible || controlsVisible -> PlayerKeyAction.DELEGATE
        isLive -> PlayerKeyAction.OPEN_GUIDE
        else -> PlayerKeyAction.SEEK_BACKWARD
    }
    KeyEvent.KEYCODE_DPAD_RIGHT -> when {
        guideVisible || controlsVisible -> PlayerKeyAction.DELEGATE
        isLive -> PlayerKeyAction.SHOW_CONTROLS
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
    else -> if (digitForKey(keyCode) != null && isLive && !guideVisible && !controlsVisible) {
        PlayerKeyAction.DIGIT
    } else {
        PlayerKeyAction.DELEGATE
    }
}

/**
 * Accumulates remote number presses into a channel number ("1", "12", "125"…). Numbers are
 * 1-based positions in the list being zapped through, like a classic TV's programme numbers.
 */
internal class ChannelNumberEntry(private val maxDigits: Int = 4) {
    var digits: String = ""
        private set

    fun push(digit: Int): String {
        digits = (if (digits.length >= maxDigits) "" else digits) + digit
        return digits
    }

    /** Returns the 0-based index for [channelCount] channels, or null when out of range; clears input. */
    fun commit(channelCount: Int): Int? {
        val number = digits.toIntOrNull()
        digits = ""
        return number?.takeIf { it in 1..channelCount }?.minus(1)
    }

    fun clear() {
        digits = ""
    }
}
