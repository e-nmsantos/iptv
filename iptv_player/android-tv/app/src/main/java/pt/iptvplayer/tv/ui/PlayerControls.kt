package pt.iptvplayer.tv.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.focusable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.focus.onFocusChanged
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.tv.material3.Text
import kotlinx.coroutines.delay

internal val PlayerPanel = Color(0xF20B1929)
internal val PlayerFocused = Color(0xFF193A52)
internal val PlayerAccent = Color(0xFF41D3BD)
internal val PlayerMuted = Color(0xFFA6B4C4)

@Composable
internal fun SubtitleOption(label: String, selected: Boolean, onClick: () -> Unit) {
    var focused by remember { mutableStateOf(false) }
    Box(
        Modifier.fillMaxWidth().padding(vertical = 4.dp)
            .onFocusChanged { focused = it.isFocused }
            .background(
                when { focused -> PlayerAccent; selected -> Color(0xFF183B4D); else -> Color.Transparent },
                RoundedCornerShape(8.dp),
            )
            .clickable(onClick = onClick)
            .focusable()
            .padding(horizontal = 14.dp, vertical = 12.dp),
    ) {
        Text(
            label,
            color = if (focused) Color.Black else Color.White,
            fontWeight = if (selected) FontWeight.Bold else FontWeight.Normal,
        )
    }
}

@Composable
internal fun PlayerControlBar(
    isPlaying: Boolean,
    isFavorite: Boolean,
    speedLabel: String,
    onSeekBackward: () -> Unit,
    onPlayPause: () -> Unit,
    onSeekForward: () -> Unit,
    onSubtitles: () -> Unit,
    onAudio: () -> Unit,
    onSpeed: () -> Unit,
    onToggleFavorite: () -> Unit,
    onInteract: () -> Unit,
) {
    val firstRequester = remember { FocusRequester() }
    LaunchedEffect(Unit) {
        delay(80)
        runCatching { firstRequester.requestFocus() }
    }
    Row(
        Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        ControlBarButton("⏪ 10s", Modifier.focusRequester(firstRequester)) { onInteract(); onSeekBackward() }
        ControlBarButton(if (isPlaying) "⏸ Pausa" else "▶ Reproduzir") { onInteract(); onPlayPause() }
        ControlBarButton("10s ⏩") { onInteract(); onSeekForward() }
        ControlBarButton("CC Legendas") { onInteract(); onSubtitles() }
        ControlBarButton("🔊 Áudio") { onInteract(); onAudio() }
        ControlBarButton("Vel. $speedLabel") { onInteract(); onSpeed() }
        ControlBarButton(if (isFavorite) "★ Favorito" else "☆ Favorito") { onInteract(); onToggleFavorite() }
    }
}

@Composable
internal fun ControlBarButton(label: String, modifier: Modifier = Modifier, onClick: () -> Unit) {
    var focused by remember { mutableStateOf(false) }
    Box(
        modifier
            .onFocusChanged { focused = it.isFocused }
            .background(if (focused) PlayerAccent else Color(0xFF193A52), RoundedCornerShape(10.dp))
            .clickable(onClick = onClick)
            .focusable()
            .padding(horizontal = 16.dp, vertical = 12.dp),
    ) {
        Text(label, color = if (focused) Color.Black else Color.White, fontWeight = FontWeight.SemiBold, fontSize = 14.sp)
    }
}

internal fun formatDuration(ms: Long): String {
    val totalSeconds = (ms / 1000).coerceAtLeast(0)
    val hours = totalSeconds / 3600
    val minutes = (totalSeconds % 3600) / 60
    val seconds = totalSeconds % 60
    return if (hours > 0) "%d:%02d:%02d".format(hours, minutes, seconds) else "%d:%02d".format(minutes, seconds)
}

internal fun formatSpeed(speed: Float): String = when (speed) {
    1f -> "1x"
    1.25f -> "1.25x"
    1.5f -> "1.5x"
    2f -> "2x"
    else -> "%.2f".format(speed).trimEnd('0').trimEnd('.') + "x"
}
