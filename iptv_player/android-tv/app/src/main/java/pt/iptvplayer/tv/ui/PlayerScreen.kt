package pt.iptvplayer.tv.ui

import android.view.KeyEvent
import android.view.LayoutInflater
import android.widget.FrameLayout
import androidx.activity.compose.BackHandler
import androidx.annotation.OptIn
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
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.focus.onFocusChanged
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.input.key.onPreviewKeyEvent
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.media3.common.MediaItem
import androidx.media3.common.C
import androidx.media3.common.PlaybackException
import androidx.media3.common.Player
import androidx.media3.common.util.UnstableApi
import androidx.media3.datasource.DefaultDataSource
import androidx.media3.datasource.DefaultHttpDataSource
import androidx.media3.datasource.HttpDataSource
import androidx.media3.exoplayer.ExoPlayer
import androidx.media3.exoplayer.DefaultLoadControl
import androidx.media3.exoplayer.upstream.DefaultLoadErrorHandlingPolicy
import androidx.media3.exoplayer.source.DefaultMediaSourceFactory
import androidx.media3.ui.PlayerView
import androidx.tv.material3.Button
import androidx.tv.material3.Text
import coil3.compose.AsyncImage
import kotlinx.coroutines.delay
import pt.iptvplayer.tv.model.Channel
import pt.iptvplayer.tv.model.StreamType
import pt.iptvplayer.tv.playback.PlaybackMetrics
import pt.iptvplayer.tv.R

private val PlayerPanel = Color(0xF20B1929)
private val PlayerFocused = Color(0xFF193A52)
private val PlayerAccent = Color(0xFF41D3BD)
private val PlayerMuted = Color(0xFFA6B4C4)

internal enum class PlayerKeyAction {
    TOGGLE_GUIDE, OPEN_GUIDE, ZAP_PREVIOUS, ZAP_NEXT, PLAY_PAUSE, PLAY, PAUSE,
    TOGGLE_FAVORITE, DELEGATE,
}

internal fun playerKeyAction(keyCode: Int, guideVisible: Boolean): PlayerKeyAction = when (keyCode) {
    KeyEvent.KEYCODE_GUIDE, KeyEvent.KEYCODE_MENU -> PlayerKeyAction.TOGGLE_GUIDE
    KeyEvent.KEYCODE_DPAD_LEFT, KeyEvent.KEYCODE_DPAD_CENTER ->
        if (guideVisible) PlayerKeyAction.DELEGATE else PlayerKeyAction.OPEN_GUIDE
    KeyEvent.KEYCODE_CHANNEL_UP -> PlayerKeyAction.ZAP_NEXT
    KeyEvent.KEYCODE_CHANNEL_DOWN -> PlayerKeyAction.ZAP_PREVIOUS
    KeyEvent.KEYCODE_DPAD_UP -> if (guideVisible) PlayerKeyAction.DELEGATE else PlayerKeyAction.ZAP_PREVIOUS
    KeyEvent.KEYCODE_DPAD_DOWN -> if (guideVisible) PlayerKeyAction.DELEGATE else PlayerKeyAction.ZAP_NEXT
    KeyEvent.KEYCODE_MEDIA_PLAY_PAUSE -> PlayerKeyAction.PLAY_PAUSE
    KeyEvent.KEYCODE_MEDIA_PLAY -> PlayerKeyAction.PLAY
    KeyEvent.KEYCODE_MEDIA_PAUSE -> PlayerKeyAction.PAUSE
    KeyEvent.KEYCODE_PROG_RED, KeyEvent.KEYCODE_BOOKMARK -> PlayerKeyAction.TOGGLE_FAVORITE
    else -> PlayerKeyAction.DELEGATE
}

@Composable
@OptIn(UnstableApi::class)
fun PlayerScreen(
    channel: Channel,
    channels: List<Channel>,
    notice: String? = null,
    onToggleFavorite: (Channel) -> Unit,
    onSaveProgress: (Channel, Long, Long) -> Unit,
    onSelectChannel: (Channel) -> Unit,
    onBack: () -> Unit,
) {
    val context = LocalContext.current
    var guideVisible by remember { mutableStateOf(true) }
    var guideCategory by remember(channels) { mutableStateOf(channel.group.ifBlank { "Todos" }) }
    var playbackError by remember(channel.url) { mutableStateOf<String?>(null) }
    var lastFailure by remember(channel.url) { mutableStateOf<String?>(null) }
    var buffering by remember(channel.url) { mutableStateOf(true) }
    var hasPlayed by remember(channel.url) { mutableStateOf(false) }
    var resumeApplied by remember(channel.url) { mutableStateOf(false) }
    val metrics = remember(channel.url) { PlaybackMetrics() }
    val currentIndex = channels.indexOfFirst { sameChannel(it, channel) }.coerceAtLeast(0)
    val player = remember(channel.url) {
        val httpFactory = DefaultHttpDataSource.Factory()
            .setAllowCrossProtocolRedirects(true)
            .setConnectTimeoutMs(15_000)
            .setReadTimeoutMs(60_000)
            .setUserAgent(channel.userAgent.ifBlank { "IPTVPlayerTV/0.9" })
            .setDefaultRequestProperties(
                mapOf("Connection" to "keep-alive", "Accept-Encoding" to "identity") + channel.requestHeaders,
            )
        val mediaSourceFactory = DefaultMediaSourceFactory(DefaultDataSource.Factory(context, httpFactory))
            .setLoadErrorHandlingPolicy(DefaultLoadErrorHandlingPolicy(12))
        ExoPlayer.Builder(context)
            .setMediaSourceFactory(mediaSourceFactory)
            .setLoadControl(
                DefaultLoadControl.Builder().setBufferDurationsMs(
                    15_000, 60_000, 2_500, 5_000,
                ).build(),
            )
            .build()
            .apply {
                setWakeMode(C.WAKE_MODE_NETWORK)
                repeatMode = if (channel.type == StreamType.LIVE) Player.REPEAT_MODE_ONE else Player.REPEAT_MODE_OFF
                setMediaItem(MediaItem.fromUri(channel.url))
                playWhenReady = true
                prepare()
            }
    }

    fun zap(offset: Int) {
        if (channels.size < 2) return
        val index = (currentIndex + offset + channels.size) % channels.size
        onSelectChannel(channels[index])
    }
    val handleKeyCode: (Int) -> Boolean = { keyCode ->
        when (playerKeyAction(keyCode, guideVisible)) {
            PlayerKeyAction.TOGGLE_GUIDE -> { guideVisible = !guideVisible; true }
            PlayerKeyAction.OPEN_GUIDE -> { guideVisible = true; true }
            PlayerKeyAction.ZAP_PREVIOUS -> { zap(-1); true }
            PlayerKeyAction.ZAP_NEXT -> { zap(1); true }
            PlayerKeyAction.PLAY_PAUSE -> { if (player.isPlaying) player.pause() else player.play(); true }
            PlayerKeyAction.PLAY -> { player.play(); true }
            PlayerKeyAction.PAUSE -> { player.pause(); true }
            PlayerKeyAction.TOGGLE_FAVORITE -> { onToggleFavorite(channel); true }
            PlayerKeyAction.DELEGATE -> false
        }
    }

    BackHandler {
        if (guideVisible) guideVisible = false else onBack()
    }
    DisposableEffect(player) {
        val listener = object : Player.Listener {
            override fun onPlaybackStateChanged(playbackState: Int) {
                buffering = playbackState == Player.STATE_BUFFERING || playbackState == Player.STATE_IDLE
                if (playbackState == Player.STATE_BUFFERING) metrics.buffering()
                if (playbackState == Player.STATE_READY) {
                    hasPlayed = true
                    if (
                        channel.type != StreamType.LIVE &&
                        !resumeApplied &&
                        channel.resumePositionMs > 0
                    ) {
                        player.seekTo(channel.resumePositionMs)
                        resumeApplied = true
                    }
                }
            }

            override fun onPlayerError(error: PlaybackException) {
                buffering = false
                val httpError = generateSequence<Throwable>(error) { it.cause }
                    .filterIsInstance<HttpDataSource.InvalidResponseCodeException>()
                    .firstOrNull()
                lastFailure = if (httpError != null) {
                    "HTTP ${httpError.responseCode} — o servidor recusou o stream"
                } else {
                    "${error.errorCodeName}: ${error.message ?: "stream indisponível"}"
                }
                if (channel.type != StreamType.LIVE) playbackError = lastFailure
                metrics.log(lastFailure)
            }
        }
        player.addListener(listener)
        onDispose {
            onSaveProgress(channel, player.currentPosition.coerceAtLeast(0), player.duration.coerceAtLeast(0))
            player.removeListener(listener)
            player.release()
        }
    }
    LaunchedEffect(player, channel.url) {
        if (channel.type != StreamType.LIVE) return@LaunchedEffect
        var bufferingChecks = 0
        var retries = 0
        var stableChecks = 0
        var sessionRefreshRequested = false

        fun reconnect() {
            if (retries >= 6) {
                playbackError = lastFailure ?: "O stream não respondeu após várias tentativas."
                return
            }
            retries++
            metrics.retry()
            if (channel.customHeaders.containsKey("Authorization") && !sessionRefreshRequested) {
                channels.firstOrNull { sameChannel(it, channel) }?.let { source ->
                    sessionRefreshRequested = true
                    onSelectChannel(source)
                }
            }
            playbackError = null
            buffering = true
            player.stop()
            player.clearMediaItems()
            player.setMediaItem(MediaItem.fromUri(channel.url))
            player.prepare()
            player.play()
            bufferingChecks = 0
            stableChecks = 0
        }

        while (true) {
            delay(3_000)
            if (!player.playWhenReady) continue
            when (player.playbackState) {
                Player.STATE_ENDED -> reconnect()
                Player.STATE_IDLE -> if (player.playerError != null) reconnect()
                Player.STATE_BUFFERING -> {
                    bufferingChecks++
                    if (bufferingChecks >= 10) reconnect()
                }
                Player.STATE_READY -> {
                    bufferingChecks = 0
                    if (player.isPlaying) stableChecks++
                    if (stableChecks >= 5) retries = 0
                }
            }
        }
    }

    Box(
        Modifier.fillMaxSize().background(Color.Black).onPreviewKeyEvent { event ->
            if (event.nativeKeyEvent.action != KeyEvent.ACTION_DOWN) return@onPreviewKeyEvent false
            handleKeyCode(event.nativeKeyEvent.keyCode)
        },
    ) {
        Box(Modifier.fillMaxSize().background(Color.Black)) {
            AndroidView(
                factory = { viewContext ->
                    val inflationParent = FrameLayout(viewContext)
                    (LayoutInflater.from(viewContext).inflate(
                        R.layout.player_view_texture, inflationParent, false,
                    ) as PlayerView).apply {
                        this.player = player
                    }
                },
                update = { view ->
                    view.player = player
                    view.setOnKeyListener { _, keyCode, event ->
                        event.action == KeyEvent.ACTION_DOWN && handleKeyCode(keyCode)
                    }
                    if (!guideVisible) view.requestFocus()
                },
                modifier = Modifier.fillMaxSize(),
            )
            if (((buffering && !hasPlayed) || notice != null) && playbackError == null) {
                Text(
                    notice ?: "A ligar ao canal…",
                    color = Color.White,
                    fontSize = 18.sp,
                    modifier = Modifier.align(Alignment.Center).background(Color(0xB807111F), RoundedCornerShape(9.dp)).padding(14.dp),
                )
            }
            playbackError?.let { message ->
                Column(
                    Modifier.align(Alignment.Center).background(Color(0xF010243A), RoundedCornerShape(14.dp)).padding(28.dp),
                    horizontalAlignment = Alignment.CenterHorizontally,
                ) {
                    Text("Não foi possível reproduzir", color = Color.White, fontSize = 22.sp)
                    Text(message, color = PlayerMuted, modifier = Modifier.padding(vertical = 12.dp))
                    Button(onClick = {
                        playbackError = null
                        buffering = true
                        player.prepare()
                        player.play()
                    }) { Text("Tentar novamente") }
                    Button(onClick = { guideVisible = true }, modifier = Modifier.padding(top = 8.dp)) { Text("Escolher outro canal") }
                }
            }
        }
        if (guideVisible) {
            ChannelGuide(
                channels = channels,
                current = channel,
                selectedCategory = guideCategory,
                onSelectCategory = { guideCategory = it },
                onSelect = onSelectChannel,
                onClose = { guideVisible = false },
                modifier = Modifier.align(Alignment.CenterStart).width(600.dp).fillMaxHeight(),
            )
        }
    }
}

@Composable
private fun ChannelGuide(
    channels: List<Channel>,
    current: Channel,
    selectedCategory: String,
    onSelectCategory: (String) -> Unit,
    onSelect: (Channel) -> Unit,
    onClose: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val categories = remember(channels) {
        listOf("Todos") + channels.asSequence().map { it.group.ifBlank { "Geral" } }
            .distinct().sortedBy { it.lowercase() }.toList()
    }
    val filteredChannels = remember(channels, selectedCategory) {
        if (selectedCategory == "Todos") channels else channels.filter { it.group == selectedCategory }
    }
    val currentIndex = filteredChannels.indexOfFirst { sameChannel(it, current) }.coerceAtLeast(0)
    val listState = rememberLazyListState()
    val categoryListState = rememberLazyListState()
    val currentRequester = remember { FocusRequester() }
    LaunchedEffect(selectedCategory, currentIndex, filteredChannels.size) {
        if (filteredChannels.isNotEmpty()) {
            listState.scrollToItem((currentIndex - 2).coerceAtLeast(0))
            delay(80)
            runCatching { currentRequester.requestFocus() }
        }
    }
    LaunchedEffect(selectedCategory, categories.size) {
        val selectedIndex = categories.indexOf(selectedCategory)
        if (selectedIndex >= 0) categoryListState.scrollToItem((selectedIndex - 2).coerceAtLeast(0))
    }
    Row(modifier.background(PlayerPanel)) {
        Column(
            Modifier.width(210.dp).fillMaxHeight().background(Color(0xFF071421)).padding(14.dp),
        ) {
            Text("CATEGORIAS", color = PlayerAccent, fontSize = 12.sp, fontWeight = FontWeight.Bold)
            Text("Botão vermelho: adicionar/remover favorito", color = PlayerMuted, fontSize = 11.sp)
            Spacer(Modifier.height(12.dp))
            LazyColumn(state = categoryListState, verticalArrangement = Arrangement.spacedBy(6.dp)) {
                itemsIndexed(categories, key = { _, item -> item }) { _, category ->
                    var focused by remember { mutableStateOf(false) }
                    val selected = selectedCategory == category
                    Box(
                        Modifier.fillMaxWidth()
                            .onFocusChanged { focused = it.isFocused }
                            .background(
                                when { focused -> PlayerFocused; selected -> Color(0xFF183B4D); else -> Color.Transparent },
                                RoundedCornerShape(9.dp),
                            )
                            .border(if (focused) 2.dp else 0.dp, PlayerAccent, RoundedCornerShape(9.dp))
                            .clickable { onSelectCategory(category) }.focusable()
                            .padding(horizontal = 12.dp, vertical = 13.dp),
                    ) {
                        Text(
                            category,
                            color = if (selected || focused) Color.White else PlayerMuted,
                            fontWeight = if (selected) FontWeight.Bold else FontWeight.Normal,
                            maxLines = 1,
                            overflow = TextOverflow.Ellipsis,
                        )
                    }
                }
            }
        }
        Column(Modifier.weight(1f).fillMaxHeight().padding(16.dp)) {
        Text("CANAIS", color = PlayerAccent, fontSize = 12.sp, fontWeight = FontWeight.Bold)
        Text(selectedCategory, color = Color.White, fontSize = 24.sp, fontWeight = FontWeight.Bold, maxLines = 1, overflow = TextOverflow.Ellipsis)
        Text("${filteredChannels.size} canais", color = PlayerMuted, fontSize = 13.sp)
        Spacer(Modifier.height(16.dp))
        if (filteredChannels.isEmpty()) {
            Text("Não há canais nesta categoria.", color = PlayerMuted)
        } else {
            LazyColumn(state = listState, verticalArrangement = Arrangement.spacedBy(7.dp)) {
                itemsIndexed(filteredChannels, key = { index, item -> "${item.id}:${item.tvgId}:$index" }) { index, item ->
                    val selected = sameChannel(item, current)
                    var focused by remember { mutableStateOf(false) }
                    Row(
                        Modifier.fillMaxWidth().height(72.dp)
                            .then(if (index == currentIndex) Modifier.focusRequester(currentRequester) else Modifier)
                            .onPreviewKeyEvent { event ->
                                if (
                                    event.nativeKeyEvent.action == KeyEvent.ACTION_DOWN &&
                                    event.nativeKeyEvent.keyCode == KeyEvent.KEYCODE_DPAD_RIGHT
                                ) {
                                    onClose()
                                    true
                                } else false
                            }
                            .onFocusChanged { focused = it.isFocused }
                            .background(
                                when { focused -> PlayerFocused; selected -> Color(0xFF183B4D); else -> Color.Transparent },
                                RoundedCornerShape(10.dp),
                            )
                            .border(if (focused) 2.dp else 0.dp, PlayerAccent, RoundedCornerShape(10.dp))
                            .clickable { onSelect(item) }.focusable().padding(horizontal = 10.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Box(
                            Modifier.size(48.dp).background(Color(0xFF07111F), RoundedCornerShape(8.dp)),
                            contentAlignment = Alignment.Center,
                        ) {
                            if (item.logo.isNotBlank()) AsyncImage(
                                model = item.logo,
                                contentDescription = null,
                                contentScale = ContentScale.Fit,
                                modifier = Modifier.fillMaxSize().padding(4.dp),
                            ) else Text(item.name.take(2).uppercase(), color = PlayerAccent, fontSize = 12.sp)
                        }
                        Spacer(Modifier.width(11.dp))
                        Column(Modifier.weight(1f)) {
                            Text(item.name, color = Color.White, maxLines = 1, overflow = TextOverflow.Ellipsis, fontWeight = if (selected) FontWeight.Bold else FontWeight.Normal)
                            Text(item.group, color = PlayerMuted, fontSize = 11.sp, maxLines = 1, overflow = TextOverflow.Ellipsis)
                        }
                        if (item.favorite) Text("★", color = PlayerAccent, fontSize = 15.sp)
                        if (selected) Text("●", color = PlayerAccent, fontSize = 12.sp)
                    }
                }
            }
        }
        }
    }
}

private fun sameChannel(left: Channel, right: Channel): Boolean = when {
    left.id != 0L && right.id != 0L -> left.id == right.id
    left.tvgId.isNotBlank() && right.tvgId.isNotBlank() -> left.tvgId == right.tvgId
    else -> left.name == right.name && left.group == right.group
}
