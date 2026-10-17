package pt.iptvplayer.tv.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.tv.material3.Text
import coil3.compose.AsyncImage
import kotlinx.coroutines.delay
import pt.iptvplayer.tv.model.Channel
import pt.iptvplayer.tv.model.EpgProgram
import pt.iptvplayer.tv.model.EpgReminder
import pt.iptvplayer.tv.playback.StreamStats
import java.util.Calendar

/** Bottom "now / next" banner shown on every zap, like a set-top box. */
@Composable
internal fun LiveInfoBanner(
    channel: Channel,
    channelNumber: Int,
    programmes: List<EpgProgram>,
    nowMillis: Long,
    behindLiveMs: Long,
    modifier: Modifier = Modifier,
) {
    val current = programmes.firstOrNull { it.startMillis <= nowMillis && nowMillis < it.stopMillis }
    val next = programmes.firstOrNull { it.startMillis >= (current?.stopMillis ?: nowMillis) }
    Row(
        modifier.fillMaxWidth()
            .background(
                Brush.verticalGradient(listOf(Color.Transparent, TvColors.Scrim, TvColors.ScrimStrong)),
            )
            .padding(start = 48.dp, end = 48.dp, top = 40.dp, bottom = 30.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Box(
            Modifier.size(84.dp).background(TvColors.Placeholder, RoundedCornerShape(14.dp)),
            contentAlignment = Alignment.Center,
        ) {
            if (channel.logo.isNotBlank()) {
                AsyncImage(
                    model = channel.logo,
                    contentDescription = null,
                    contentScale = ContentScale.Fit,
                    modifier = Modifier.size(84.dp).padding(8.dp),
                )
            } else {
                Text(channel.name.take(2).uppercase(), color = PlayerAccent, fontSize = 24.sp, fontWeight = FontWeight.Bold)
            }
        }
        Spacer(Modifier.width(22.dp))
        Column(Modifier.weight(1f)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                if (channelNumber > 0) {
                    Text("$channelNumber", color = PlayerAccent, fontSize = 22.sp, fontWeight = FontWeight.Bold)
                    Spacer(Modifier.width(12.dp))
                }
                Text(
                    channel.name,
                    color = Color.White,
                    fontSize = 24.sp,
                    fontWeight = FontWeight.Bold,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                    modifier = Modifier.weight(1f, fill = false),
                )
                if (channel.quality.isNotBlank()) {
                    Spacer(Modifier.width(10.dp))
                    Badge(channel.quality, PlayerAccent, Color.Black)
                }
                Spacer(Modifier.width(10.dp))
                if (behindLiveMs > 1_000) {
                    Badge("EM DIFERIDO −${formatDuration(behindLiveMs)}", TvColors.Warning, Color.Black)
                } else {
                    Badge("● DIRETO", TvColors.Live, Color.White)
                }
                if (channel.favorite) {
                    Spacer(Modifier.width(10.dp))
                    Text("★", color = TvColors.Gold, fontSize = 20.sp)
                }
            }
            Spacer(Modifier.height(10.dp))
            if (current == null) {
                Text(channel.group, color = PlayerMuted, fontSize = 15.sp)
            } else {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text(
                        "${formatClock(current.startMillis)} – ${formatClock(current.stopMillis)}",
                        color = PlayerMuted,
                        fontSize = 14.sp,
                    )
                    Spacer(Modifier.width(12.dp))
                    Text(
                        current.title,
                        color = Color.White,
                        fontSize = 17.sp,
                        fontWeight = FontWeight.SemiBold,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                    )
                }
                Spacer(Modifier.height(6.dp))
                val span = (current.stopMillis - current.startMillis).coerceAtLeast(1)
                val fraction = ((nowMillis - current.startMillis).toFloat() / span).coerceIn(0f, 1f)
                ProgressLine(fraction, Modifier.widthIn(max = 520.dp).fillMaxWidth())
                if (current.description.isNotBlank()) {
                    Spacer(Modifier.height(6.dp))
                    Text(current.description, color = PlayerMuted, fontSize = 13.sp, maxLines = 2, overflow = TextOverflow.Ellipsis)
                }
            }
            if (next != null) {
                Spacer(Modifier.height(8.dp))
                Text(
                    "A seguir  ${formatClock(next.startMillis)}  ${next.title}",
                    color = PlayerMuted,
                    fontSize = 14.sp,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
            }
        }
    }
}

@Composable
internal fun Badge(label: String, background: Color, foreground: Color) {
    Text(
        label,
        color = foreground,
        fontSize = 11.sp,
        fontWeight = FontWeight.Bold,
        modifier = Modifier.background(background, RoundedCornerShape(5.dp)).padding(horizontal = 7.dp, vertical = 3.dp),
    )
}

@Composable
internal fun ProgressLine(fraction: Float, modifier: Modifier = Modifier, height: Int = 4) {
    Box(modifier.height(height.dp).background(Color(0x33FFFFFF), RoundedCornerShape(2.dp))) {
        Box(Modifier.fillMaxWidth(fraction.coerceIn(0f, 1f)).height(height.dp).background(PlayerAccent, RoundedCornerShape(2.dp)))
    }
}

/** Big digits in the corner while the viewer types a channel number. */
@Composable
internal fun ChannelNumberOverlay(digits: String, preview: Channel?, modifier: Modifier = Modifier) {
    Column(
        modifier.background(TvColors.Scrim, RoundedCornerShape(16.dp)).padding(horizontal = 26.dp, vertical = 16.dp),
        horizontalAlignment = Alignment.End,
    ) {
        Text(digits, color = Color.White, fontSize = 48.sp, fontWeight = FontWeight.Bold)
        Text(
            preview?.name ?: "Canal inexistente",
            color = if (preview == null) TvColors.Warning else PlayerMuted,
            fontSize = 14.sp,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
            modifier = Modifier.widthIn(max = 280.dp),
        )
    }
}

@Composable
internal fun StreamStatsOverlay(stats: StreamStats, timeshiftEnabled: Boolean, modifier: Modifier = Modifier) {
    Column(
        modifier.background(TvColors.ScrimSoft, RoundedCornerShape(12.dp)).padding(16.dp).widthIn(min = 300.dp),
    ) {
        Text("ESTATÍSTICAS", color = PlayerAccent, fontSize = 11.sp, fontWeight = FontWeight.Bold)
        Spacer(Modifier.height(8.dp))
        StatLine("Vídeo", listOf(stats.resolution, stats.frameRate, stats.videoCodec).filter(String::isNotBlank).joinToString(" · "))
        StatLine("Descodificador", stats.videoDecoder)
        StatLine("Áudio", stats.audioCodec)
        StatLine("Descodificador", stats.audioDecoder)
        StatLine("Débito", if (stats.bitrateKbps > 0) "%.1f Mbps".format(stats.bitrateKbps / 1000f) else "")
        StatLine("Buffer", "%.1f s".format(stats.bufferedMs / 1000f) + if (timeshiftEnabled) " (pausa em direto ativa)" else "")
        StatLine("Frames perdidos", stats.droppedFrames.toString())
    }
}

@Composable
private fun StatLine(label: String, value: String) {
    if (value.isBlank()) return
    Row(Modifier.padding(vertical = 2.dp)) {
        Text(label, color = PlayerMuted, fontSize = 13.sp, modifier = Modifier.width(118.dp))
        Text(value, color = Color.White, fontSize = 13.sp)
    }
}

/** "A seguir" card at the end of an episode, with an optional auto-play countdown. */
@Composable
internal fun NextEpisodeCard(
    next: Channel,
    secondsLeft: Int?,
    onPlayNow: () -> Unit,
    onCancel: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val playRequester = remember { FocusRequester() }
    LaunchedEffect(Unit) {
        delay(80)
        runCatching { playRequester.requestFocus() }
    }
    Row(
        modifier.background(TvColors.Overlay, RoundedCornerShape(16.dp)).padding(18.dp).width(520.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Box(Modifier.size(width = 150.dp, height = 88.dp).background(TvColors.Placeholder, RoundedCornerShape(10.dp))) {
            if (next.logo.isNotBlank()) {
                AsyncImage(
                    model = next.logo,
                    contentDescription = null,
                    contentScale = ContentScale.Crop,
                    modifier = Modifier.size(width = 150.dp, height = 88.dp),
                )
            }
        }
        Spacer(Modifier.width(16.dp))
        Column(Modifier.weight(1f)) {
            Text(
                if (secondsLeft != null) "Próximo episódio em $secondsLeft s" else "Próximo episódio",
                color = PlayerAccent,
                fontSize = 12.sp,
                fontWeight = FontWeight.Bold,
            )
            Text(next.name, color = Color.White, fontSize = 18.sp, fontWeight = FontWeight.Bold, maxLines = 2, overflow = TextOverflow.Ellipsis)
            Text(next.group, color = PlayerMuted, fontSize = 13.sp)
            Spacer(Modifier.height(10.dp))
            Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                ControlBarButton("▶ Ver agora", Modifier.focusRequester(playRequester), onPlayNow)
                ControlBarButton("Cancelar", onClick = onCancel)
            }
        }
    }
}

/** Shown over playback or the catalog when a reminded programme starts. */
@Composable
internal fun ReminderCard(
    reminder: EpgReminder,
    onWatch: () -> Unit,
    onDismiss: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val watchRequester = remember { FocusRequester() }
    LaunchedEffect(reminder) {
        delay(80)
        runCatching { watchRequester.requestFocus() }
    }
    Column(modifier.background(TvColors.Overlay, RoundedCornerShape(16.dp)).padding(20.dp).width(440.dp)) {
        Text(
            if (System.currentTimeMillis() < reminder.startMillis) "🔔 Começa dentro de momentos" else "🔔 Já começou",
            color = PlayerAccent,
            fontSize = 12.sp,
            fontWeight = FontWeight.Bold,
        )
        Spacer(Modifier.height(4.dp))
        Text(reminder.title, color = Color.White, fontSize = 20.sp, fontWeight = FontWeight.Bold, maxLines = 2, overflow = TextOverflow.Ellipsis)
        Text(
            "${reminder.channel.name} · ${formatClock(reminder.startMillis)}–${formatClock(reminder.stopMillis)}",
            color = PlayerMuted,
            fontSize = 14.sp,
        )
        Spacer(Modifier.height(14.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            ControlBarButton("Ver agora", Modifier.focusRequester(watchRequester), onWatch)
            ControlBarButton("Ignorar", onClick = onDismiss)
        }
    }
}

internal fun formatClock(millis: Long): String {
    val calendar = Calendar.getInstance().apply { timeInMillis = millis }
    return "%02d:%02d".format(calendar.get(Calendar.HOUR_OF_DAY), calendar.get(Calendar.MINUTE))
}
