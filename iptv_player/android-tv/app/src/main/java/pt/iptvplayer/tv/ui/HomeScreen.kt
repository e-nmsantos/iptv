package pt.iptvplayer.tv.ui

import android.view.KeyEvent
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.focusable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.focus.onFocusChanged
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.input.key.onPreviewKeyEvent
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.tv.material3.Text
import coil3.compose.AsyncImage
import kotlinx.coroutines.delay
import pt.iptvplayer.tv.CatalogUiState
import pt.iptvplayer.tv.model.Channel
import pt.iptvplayer.tv.model.EpgProgram
import pt.iptvplayer.tv.model.StreamType
import pt.iptvplayer.tv.model.WatchHistoryItem
import java.util.Calendar

@Composable
internal fun HomeScreen(
    state: CatalogUiState,
    onPlay: (Channel) -> Unit,
    onResume: (WatchHistoryItem) -> Unit,
    onRemoveFromContinue: (WatchHistoryItem) -> Unit,
    onBrowse: (StreamType) -> Unit,
) {
    // The active playlist's identity already lives permanently in the sidebar badge, so this
    // screen doesn't repeat it (that used to surface raw technical identifiers for some
    // sources, e.g. a Stalker portal's MAC address, as if it were a friendly greeting).
    val liveNow = remember(state.channels) { state.channels.filter { it.type == StreamType.LIVE }.take(20) }
    val hero = remember(state.continueWatching, state.recentMovies, state.recentSeries) {
        state.continueWatching.firstOrNull { it.artwork.isNotBlank() }?.let { HeroItem.Resume(it) }
            ?: (state.recentMovies + state.recentSeries).firstOrNull { it.logo.isNotBlank() }?.let { HeroItem.Discover(it) }
    }
    val heroRequester = remember { FocusRequester() }
    LaunchedEffect(hero != null) {
        if (hero != null) {
            delay(120)
            runCatching { heroRequester.requestFocus() }
        }
    }
    val nothingYet = state.continueWatching.isEmpty() && state.homeFavorites.isEmpty() &&
        state.recentLive.isEmpty() && liveNow.isEmpty() && state.recentMovies.isEmpty()

    LazyColumn(Modifier.fillMaxSize(), verticalArrangement = Arrangement.spacedBy(26.dp)) {
        item(key = "header") {
            if (hero != null) {
                HeroBanner(hero, heroRequester, onResume = onResume, onPlay = onPlay)
            } else {
                Column {
                    Text(greeting(), color = Color.White, fontSize = 30.sp, fontWeight = FontWeight.Bold)
                    Text(
                        if (nothingYet) "Adiciona uma lista para começar." else "O que vamos ver hoje?",
                        color = Muted,
                    )
                }
            }
        }
        if (state.continueWatching.isNotEmpty()) {
            item(key = "continue") {
                HomeRow("Continuar a ver", hint = "Botão ☰ ou ⌫ remove da lista") {
                    items(state.continueWatching, key = { it.mediaKey }) { item ->
                        ContinueCard(item, onResume, onRemoveFromContinue)
                    }
                }
            }
        }
        if (state.recentLive.isNotEmpty()) {
            item(key = "recent-live") {
                HomeRow("Vistos recentemente") {
                    items(state.recentLive, key = { "r:${it.id}:${it.tvgId}:${it.name}" }) { channel ->
                        LiveTile(channel, state.epg[channel.tvgId], onPlay)
                    }
                }
            }
        }
        item(key = "favorites") {
            if (state.homeFavorites.isEmpty()) {
                Column {
                    SectionTitle("Favoritos")
                    Spacer(Modifier.height(12.dp))
                    Box(
                        Modifier.fillMaxWidth().height(84.dp).background(Panel, RoundedCornerShape(16.dp)).padding(horizontal = 22.dp),
                        contentAlignment = Alignment.CenterStart,
                    ) {
                        Text(
                            "Marca os teus canais preferidos com o botão vermelho (ou ★ nos controlos) para os veres aqui.",
                            color = Muted,
                        )
                    }
                }
            } else {
                HomeRow("Favoritos") {
                    items(state.homeFavorites, key = { "f:${it.id}" }) { channel ->
                        if (channel.type == StreamType.LIVE) {
                            LiveTile(channel, state.epg[channel.tvgId], onPlay)
                        } else {
                            PosterTile(channel, onPlay)
                        }
                    }
                }
            }
        }
        if (state.recentMovies.isNotEmpty()) {
            item(key = "new-movies") {
                HomeRow("Filmes adicionados recentemente", action = "Ver todos" to { onBrowse(StreamType.VOD) }) {
                    items(state.recentMovies, key = { "m:${it.id}" }) { channel -> PosterTile(channel, onPlay) }
                }
            }
        }
        if (state.recentSeries.isNotEmpty()) {
            item(key = "new-series") {
                HomeRow("Séries adicionadas recentemente", action = "Ver todas" to { onBrowse(StreamType.SERIES) }) {
                    items(state.recentSeries, key = { "s:${it.id}" }) { channel -> PosterTile(channel, onPlay) }
                }
            }
        }
        if (liveNow.isNotEmpty()) {
            item(key = "live-now") {
                HomeRow("Em direto agora", action = "Ver canais" to { onBrowse(StreamType.LIVE) }) {
                    items(liveNow, key = { "l:${it.id}" }) { channel -> LiveTile(channel, state.epg[channel.tvgId], onPlay) }
                }
            }
        }
        item(key = "bottom-space") { Spacer(Modifier.height(24.dp)) }
    }
}

private sealed interface HeroItem {
    data class Resume(val item: WatchHistoryItem) : HeroItem
    data class Discover(val channel: Channel) : HeroItem
}

@Composable
private fun HeroBanner(
    hero: HeroItem,
    focusRequester: FocusRequester,
    onResume: (WatchHistoryItem) -> Unit,
    onPlay: (Channel) -> Unit,
) {
    val artwork: String
    val eyebrow: String
    val title: String
    val subtitle: String
    val progress: Float?
    val action: String
    when (hero) {
        is HeroItem.Resume -> {
            artwork = hero.item.artwork
            eyebrow = if (hero.item.upNext) "PRÓXIMO EPISÓDIO" else "CONTINUAR A VER"
            title = hero.item.title
            subtitle = hero.item.subtitle
            progress = hero.item.progress.takeIf { !hero.item.upNext && it > 0f }
            action = if (hero.item.upNext) "▶  Ver episódio" else "▶  Continuar · faltam ${formatDuration(hero.item.durationMs - hero.item.positionMs)}"
        }
        is HeroItem.Discover -> {
            artwork = hero.channel.logo
            eyebrow = if (hero.channel.type == StreamType.SERIES) "NOVA SÉRIE" else "NOVIDADE"
            title = hero.channel.name
            subtitle = hero.channel.group
            progress = null
            action = if (hero.channel.type == StreamType.SERIES) "▶  Ver episódios" else "▶  Ver agora"
        }
    }
    Box(
        Modifier.fillMaxWidth().height(300.dp).clip(RoundedCornerShape(20.dp)).background(Panel),
    ) {
        AsyncImage(
            model = artwork,
            contentDescription = null,
            contentScale = ContentScale.Crop,
            modifier = Modifier.fillMaxSize().graphicsLayer { alpha = 0.55f },
        )
        Box(
            Modifier.fillMaxSize().background(
                Brush.horizontalGradient(listOf(Background, Background.copy(alpha = 0.85f), Color.Transparent)),
            ),
        )
        Row(Modifier.fillMaxSize().padding(32.dp), verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Text(eyebrow, color = Accent, fontSize = 12.sp, fontWeight = FontWeight.Bold)
                Spacer(Modifier.height(6.dp))
                Text(title, color = Color.White, fontSize = 34.sp, fontWeight = FontWeight.Bold, maxLines = 2, overflow = TextOverflow.Ellipsis)
                if (subtitle.isNotBlank()) {
                    Text(subtitle, color = Muted, fontSize = 16.sp, maxLines = 1, overflow = TextOverflow.Ellipsis)
                }
                if (progress != null) {
                    Spacer(Modifier.height(12.dp))
                    ProgressLine(progress, Modifier.widthIn(max = 360.dp).fillMaxWidth())
                }
                Spacer(Modifier.height(20.dp))
                HeroButton(action, focusRequester) {
                    when (hero) {
                        is HeroItem.Resume -> onResume(hero.item)
                        is HeroItem.Discover -> onPlay(hero.channel)
                    }
                }
            }
            Box(
                Modifier.width(170.dp).fillMaxHeight().clip(RoundedCornerShape(14.dp)).background(Color(0xFF0A1624)),
            ) {
                AsyncImage(model = artwork, contentDescription = null, contentScale = ContentScale.Crop, modifier = Modifier.fillMaxSize())
            }
        }
    }
}

@Composable
private fun HeroButton(label: String, focusRequester: FocusRequester, onClick: () -> Unit) {
    var focused by remember { mutableStateOf(false) }
    Box(
        Modifier.focusRequester(focusRequester)
            .onFocusChanged { focused = it.isFocused }
            .graphicsLayer { scaleX = if (focused) 1.05f else 1f; scaleY = if (focused) 1.05f else 1f }
            .background(if (focused) Color.White else Accent, RoundedCornerShape(12.dp))
            .clickable(onClick = onClick)
            .focusable()
            .padding(horizontal = 24.dp, vertical = 13.dp),
    ) {
        Text(label, color = Background, fontWeight = FontWeight.Bold, fontSize = 16.sp)
    }
}

@Composable
private fun SectionTitle(title: String, hint: String? = null) {
    Row(verticalAlignment = Alignment.Bottom) {
        Text(title, color = Color.White, fontSize = 22.sp, fontWeight = FontWeight.Bold)
        if (hint != null) {
            Spacer(Modifier.width(14.dp))
            Text(hint, color = Muted, fontSize = 12.sp)
        }
    }
}

@Composable
private fun HomeRow(
    title: String,
    hint: String? = null,
    action: Pair<String, () -> Unit>? = null,
    content: androidx.compose.foundation.lazy.LazyListScope.() -> Unit,
) {
    Column {
        Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
            Box(Modifier.weight(1f)) { SectionTitle(title, hint) }
            if (action != null) SmallLink(action.first, action.second)
        }
        Spacer(Modifier.height(12.dp))
        LazyRow(horizontalArrangement = Arrangement.spacedBy(14.dp), content = content)
    }
}

@Composable
private fun SmallLink(label: String, onClick: () -> Unit) {
    var focused by remember { mutableStateOf(false) }
    Text(
        "$label  ›",
        color = if (focused) Background else Accent,
        fontSize = 13.sp,
        fontWeight = FontWeight.SemiBold,
        modifier = Modifier.onFocusChanged { focused = it.isFocused }
            .background(if (focused) Accent else Color.Transparent, RoundedCornerShape(8.dp))
            .clickable(onClick = onClick).focusable()
            .padding(horizontal = 10.dp, vertical = 6.dp),
    )
}

@Composable
private fun ContinueCard(
    item: WatchHistoryItem,
    onResume: (WatchHistoryItem) -> Unit,
    onRemove: (WatchHistoryItem) -> Unit,
) {
    var focused by remember { mutableStateOf(false) }
    Column(
        Modifier.width(300.dp)
            .graphicsLayer { scaleX = if (focused) 1.05f else 1f; scaleY = if (focused) 1.05f else 1f }
            .onFocusChanged { focused = it.isFocused }
            .onPreviewKeyEvent { event ->
                val code = event.nativeKeyEvent.keyCode
                if (event.nativeKeyEvent.action == KeyEvent.ACTION_DOWN &&
                    (code == KeyEvent.KEYCODE_MENU || code == KeyEvent.KEYCODE_DEL || code == KeyEvent.KEYCODE_FORWARD_DEL)
                ) {
                    onRemove(item)
                    true
                } else {
                    false
                }
            }
            .background(if (focused) PanelFocused else Panel, RoundedCornerShape(14.dp))
            .border(if (focused) 3.dp else 0.dp, Accent, RoundedCornerShape(14.dp))
            .clickable { onResume(item) }
            .focusable(),
    ) {
        Box(Modifier.fillMaxWidth().height(160.dp).clip(RoundedCornerShape(topStart = 14.dp, topEnd = 14.dp)).background(Color(0xFF0A1624))) {
            if (item.artwork.isNotBlank()) {
                AsyncImage(model = item.artwork, contentDescription = null, contentScale = ContentScale.Crop, modifier = Modifier.fillMaxSize())
            } else {
                Text(item.title.take(2).uppercase(), color = Accent, fontSize = 30.sp, fontWeight = FontWeight.Bold, modifier = Modifier.align(Alignment.Center))
            }
            if (item.upNext) {
                Box(Modifier.align(Alignment.TopStart).padding(8.dp)) { Badge("PRÓXIMO EPISÓDIO", Accent, Background) }
            }
            if (!item.upNext && item.durationMs > 0) {
                ProgressLine(item.progress, Modifier.align(Alignment.BottomCenter).fillMaxWidth(), height = 5)
            }
        }
        Column(Modifier.padding(12.dp)) {
            Text(item.title, color = Color.White, fontWeight = FontWeight.SemiBold, maxLines = 1, overflow = TextOverflow.Ellipsis)
            Text(
                when {
                    item.upNext -> item.subtitle
                    item.durationMs > 0 -> "${item.subtitle} · faltam ${formatDuration(item.durationMs - item.positionMs)}".trimStart(' ', '·')
                    else -> item.subtitle
                },
                color = Muted,
                fontSize = 12.sp,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
        }
    }
}

@Composable
private fun LiveTile(channel: Channel, programmes: List<EpgProgram>?, onPlay: (Channel) -> Unit) {
    var focused by remember { mutableStateOf(false) }
    val now = System.currentTimeMillis()
    val current = programmes?.firstOrNull { it.startMillis <= now && now < it.stopMillis }
    Column(
        Modifier.width(250.dp).height(140.dp)
            .graphicsLayer { scaleX = if (focused) 1.05f else 1f; scaleY = if (focused) 1.05f else 1f }
            .onFocusChanged { focused = it.isFocused }
            .background(if (focused) PanelFocused else Panel, RoundedCornerShape(14.dp))
            .border(if (focused) 3.dp else 0.dp, Accent, RoundedCornerShape(14.dp))
            .clickable { onPlay(channel) }.focusable().padding(14.dp),
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Box(Modifier.size(52.dp).background(Color(0xFF0A1624), RoundedCornerShape(10.dp)), contentAlignment = Alignment.Center) {
                if (channel.logo.isNotBlank()) {
                    AsyncImage(model = channel.logo, contentDescription = null, contentScale = ContentScale.Fit, modifier = Modifier.fillMaxSize().padding(5.dp))
                } else {
                    Text(channel.name.take(2).uppercase(), color = Accent, fontWeight = FontWeight.Bold)
                }
            }
            Spacer(Modifier.width(12.dp))
            Column(Modifier.weight(1f)) {
                Text(channel.name, color = Color.White, fontWeight = FontWeight.Bold, maxLines = 1, overflow = TextOverflow.Ellipsis)
                Text(channel.group, color = Muted, fontSize = 11.sp, maxLines = 1, overflow = TextOverflow.Ellipsis)
            }
            if (channel.favorite) Text("★", color = Accent, fontSize = 16.sp)
        }
        Spacer(Modifier.weight(1f))
        if (current != null) {
            Text(current.title, color = Accent, fontSize = 13.sp, maxLines = 1, overflow = TextOverflow.Ellipsis)
            Spacer(Modifier.height(5.dp))
            val span = (current.stopMillis - current.startMillis).coerceAtLeast(1)
            ProgressLine(((now - current.startMillis).toFloat() / span), Modifier.fillMaxWidth(), height = 3)
        } else {
            Text("Sem guia disponível", color = Muted, fontSize = 12.sp)
        }
    }
}

@Composable
private fun PosterTile(channel: Channel, onPlay: (Channel) -> Unit) {
    var focused by remember { mutableStateOf(false) }
    Column(
        Modifier.width(150.dp)
            .graphicsLayer { scaleX = if (focused) 1.07f else 1f; scaleY = if (focused) 1.07f else 1f }
            .onFocusChanged { focused = it.isFocused }
            .clickable { onPlay(channel) }.focusable(),
    ) {
        Box(
            Modifier.fillMaxWidth().height(220.dp).clip(RoundedCornerShape(12.dp))
                .background(Color(0xFF0A1624))
                .border(if (focused) 3.dp else 0.dp, Accent, RoundedCornerShape(12.dp)),
            contentAlignment = Alignment.Center,
        ) {
            if (channel.logo.isNotBlank()) {
                AsyncImage(model = channel.logo, contentDescription = null, contentScale = ContentScale.Crop, modifier = Modifier.fillMaxSize())
            } else {
                Text(channel.name.take(2).uppercase(), color = Accent, fontSize = 30.sp, fontWeight = FontWeight.Bold)
            }
        }
        Text(
            channel.name,
            color = if (focused) Color.White else Muted,
            fontSize = 13.sp,
            fontWeight = if (focused) FontWeight.Bold else FontWeight.Normal,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
            modifier = Modifier.padding(top = 8.dp, start = 2.dp, end = 2.dp),
        )
    }
}

private fun greeting(): String = when (Calendar.getInstance().get(Calendar.HOUR_OF_DAY)) {
    in 6..12 -> "Bom dia"
    in 13..19 -> "Boa tarde"
    else -> "Boa noite"
}
