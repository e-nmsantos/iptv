package pt.iptvplayer.tv.ui

import android.view.KeyEvent
import android.view.LayoutInflater
import android.widget.FrameLayout
import androidx.activity.compose.BackHandler
import androidx.annotation.OptIn
import androidx.compose.foundation.background
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
import androidx.compose.foundation.layout.width
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
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.input.key.onPreviewKeyEvent
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.media3.common.MediaItem
import androidx.media3.common.C
import androidx.media3.common.PlaybackException
import androidx.media3.common.Player
import androidx.media3.common.TrackSelectionOverride
import androidx.media3.common.Tracks
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
import kotlinx.coroutines.delay
import pt.iptvplayer.tv.model.Channel
import pt.iptvplayer.tv.model.StreamType
import pt.iptvplayer.tv.playback.PlaybackMetrics
import pt.iptvplayer.tv.R

import android.net.Uri
import androidx.media3.common.MimeTypes

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
    var tracksState by remember(channel.url) { mutableStateOf<Tracks?>(null) }
    var showSubtitles by remember { mutableStateOf(false) }
    var showOnlineSubs by remember { mutableStateOf(false) }
    var showAudio by remember { mutableStateOf(false) }
    var speed by remember(channel.url) { mutableStateOf(1f) }
    var seekTick by remember(channel.url) { mutableStateOf(0) }
    var seekBarVisible by remember { mutableStateOf(false) }
    var controlsVisible by remember(channel.url) { mutableStateOf(false) }
    var controlsHideTick by remember(channel.url) { mutableStateOf(0) }
    var isPlaying by remember(channel.url) { mutableStateOf(true) }
    var showControlsHint by remember(channel.url) { mutableStateOf(channel.type != StreamType.LIVE) }
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
    fun seek(deltaMs: Long) {
        if (channel.type == StreamType.LIVE) return
        val duration = player.duration.coerceAtLeast(0)
        val upperBound = if (duration > 0) duration else Long.MAX_VALUE
        player.seekTo((player.currentPosition + deltaMs).coerceIn(0, upperBound))
        seekTick++
    }
    fun cycleSpeed() {
        speed = when (speed) {
            1f -> 1.25f
            1.25f -> 1.5f
            1.5f -> 2f
            else -> 1f
        }
        player.setPlaybackSpeed(speed)
    }
    val handleKeyCode: (Int) -> Boolean = { keyCode ->
        when (playerKeyAction(keyCode, guideVisible, channel.type == StreamType.LIVE, controlsVisible)) {
            PlayerKeyAction.TOGGLE_GUIDE -> { guideVisible = !guideVisible; true }
            PlayerKeyAction.OPEN_GUIDE -> { guideVisible = true; true }
            PlayerKeyAction.ZAP_PREVIOUS -> { zap(-1); true }
            PlayerKeyAction.ZAP_NEXT -> { zap(1); true }
            PlayerKeyAction.RECALL_PREVIOUS -> { zap(-1); true }
            PlayerKeyAction.PLAY_PAUSE -> { if (player.isPlaying) player.pause() else player.play(); true }
            PlayerKeyAction.PLAY -> { player.play(); true }
            PlayerKeyAction.PAUSE -> { player.pause(); true }
            PlayerKeyAction.TOGGLE_FAVORITE -> { onToggleFavorite(channel); true }
            PlayerKeyAction.SEEK_FORWARD -> { seek(10_000); true }
            PlayerKeyAction.SEEK_BACKWARD -> { seek(-10_000); true }
            PlayerKeyAction.TOGGLE_SUBTITLES -> { showSubtitles = true; true }
            PlayerKeyAction.SHOW_CONTROLS -> { controlsVisible = true; controlsHideTick++; true }
            PlayerKeyAction.DELEGATE -> false
        }
    }

    BackHandler {
        when {
            guideVisible -> guideVisible = false
            showSubtitles -> showSubtitles = false
            showAudio -> showAudio = false
            controlsVisible -> controlsVisible = false
            else -> onBack()
        }
    }
    DisposableEffect(player) {
        val listener = object : Player.Listener {
            override fun onIsPlayingChanged(playing: Boolean) {
                isPlaying = playing
            }

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

            override fun onTracksChanged(tracks: Tracks) {
                tracksState = tracks
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

    LaunchedEffect(seekTick) {
        if (seekTick == 0 || controlsVisible) return@LaunchedEffect
        seekBarVisible = true
        delay(3_000)
        seekBarVisible = false
    }
    LaunchedEffect(controlsHideTick) {
        if (controlsHideTick == 0) return@LaunchedEffect
        delay(6_000)
        controlsVisible = false
    }
    var positionTick by remember(channel.url) { mutableStateOf(0) }
    LaunchedEffect(seekBarVisible, controlsVisible) {
        while (seekBarVisible || controlsVisible) {
            positionTick++
            delay(500)
        }
    }
    LaunchedEffect(channel.url) {
        if (showControlsHint) {
            delay(4_000)
            showControlsHint = false
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
                    if (!guideVisible && !controlsVisible) view.requestFocus()
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
        if (showControlsHint && channel.type != StreamType.LIVE && !guideVisible && !controlsVisible) {
            Text(
                "▲ ou ▼ para abrir os controlos",
                color = PlayerMuted,
                fontSize = 13.sp,
                modifier = Modifier.align(Alignment.BottomCenter).padding(bottom = 24.dp)
                    .background(Color(0xB807111F), RoundedCornerShape(8.dp)).padding(horizontal = 14.dp, vertical = 8.dp),
            )
        }
        if (seekBarVisible && !controlsVisible && channel.type != StreamType.LIVE && !guideVisible) {
            val position = remember(positionTick) { player.currentPosition.coerceAtLeast(0) }
            val duration = remember(positionTick) { player.duration.coerceAtLeast(0) }
            val fraction = if (duration > 0) (position.toFloat() / duration.toFloat()).coerceIn(0f, 1f) else 0f
            Column(
                Modifier.align(Alignment.BottomCenter).fillMaxWidth().padding(horizontal = 48.dp, vertical = 30.dp)
                    .background(Color(0xE60B1929), RoundedCornerShape(12.dp)).padding(20.dp),
            ) {
                Box(Modifier.fillMaxWidth().height(6.dp).background(Color(0x33FFFFFF), RoundedCornerShape(3.dp))) {
                    Box(Modifier.fillMaxWidth(fraction).height(6.dp).background(PlayerAccent, RoundedCornerShape(3.dp)))
                }
                Spacer(Modifier.height(10.dp))
                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                    Text(formatDuration(position), color = Color.White, fontSize = 14.sp)
                    Text(if (duration > 0) formatDuration(duration) else "--:--", color = PlayerMuted, fontSize = 14.sp)
                }
            }
        }
        // Discoverable, D-pad + OK only control panel — the sole reliable input on a bare
        // remote with no colour/media-transport/captions keys (e.g. a minimal Android TV box
        // remote). Opened with D-pad up/down; every action inside it is reachable the same way.
        if (controlsVisible && channel.type != StreamType.LIVE && !guideVisible) {
            val position = remember(positionTick) { player.currentPosition.coerceAtLeast(0) }
            val duration = remember(positionTick) { player.duration.coerceAtLeast(0) }
            val fraction = if (duration > 0) (position.toFloat() / duration.toFloat()).coerceIn(0f, 1f) else 0f
            Column(
                Modifier.align(Alignment.BottomCenter).fillMaxWidth().padding(horizontal = 40.dp, vertical = 28.dp)
                    .background(Color(0xE60B1929), RoundedCornerShape(14.dp)).padding(20.dp),
            ) {
                Box(Modifier.fillMaxWidth().height(6.dp).background(Color(0x33FFFFFF), RoundedCornerShape(3.dp))) {
                    Box(Modifier.fillMaxWidth(fraction).height(6.dp).background(PlayerAccent, RoundedCornerShape(3.dp)))
                }
                Spacer(Modifier.height(6.dp))
                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                    Text(formatDuration(position), color = Color.White, fontSize = 13.sp)
                    Text(if (duration > 0) formatDuration(duration) else "--:--", color = PlayerMuted, fontSize = 13.sp)
                }
                Spacer(Modifier.height(16.dp))
                PlayerControlBar(
                    isPlaying = isPlaying,
                    isFavorite = channel.favorite,
                    speedLabel = formatSpeed(speed),
                    onSeekBackward = { seek(-10_000) },
                    onPlayPause = { if (player.isPlaying) player.pause() else player.play() },
                    onSeekForward = { seek(10_000) },
                    onSubtitles = { showSubtitles = true },
                    onAudio = { showAudio = true },
                    onSpeed = { cycleSpeed() },
                    onToggleFavorite = { onToggleFavorite(channel) },
                    onInteract = { controlsHideTick++ },
                )
            }
        }
        if (showSubtitles) {
            val textGroups = tracksState?.groups?.filter { it.type == C.TRACK_TYPE_TEXT } ?: emptyList()
            Column(
                Modifier.align(Alignment.CenterEnd).width(360.dp)
                    .background(PlayerPanel, RoundedCornerShape(14.dp)).padding(20.dp),
            ) {
                Text("Legendas", color = Color.White, fontSize = 20.sp, fontWeight = FontWeight.Bold)
                Spacer(Modifier.height(14.dp))
                SubtitleOption("Desligadas", selected = textGroups.none { it.isSelected }) {
                    player.trackSelectionParameters = player.trackSelectionParameters.buildUpon()
                        .setTrackTypeDisabled(C.TRACK_TYPE_TEXT, true)
                        .clearOverridesOfType(C.TRACK_TYPE_TEXT)
                        .build()
                    showSubtitles = false
                }
                if (textGroups.isEmpty()) {
                    Text(
                        "Sem legendas disponíveis para este conteúdo.",
                        color = PlayerMuted,
                        fontSize = 13.sp,
                        modifier = Modifier.padding(top = 8.dp),
                    )
                } else {
                    textGroups.forEachIndexed { groupIndex, group ->
                        for (trackIndex in 0 until group.length) {
                            if (!group.isTrackSupported(trackIndex)) continue
                            val format = group.getTrackFormat(trackIndex)
                            val label = format.label ?: format.language?.uppercase() ?: "Faixa ${groupIndex + 1}"
                            SubtitleOption(label, selected = group.isTrackSelected(trackIndex)) {
                                player.trackSelectionParameters = player.trackSelectionParameters.buildUpon()
                                    .setTrackTypeDisabled(C.TRACK_TYPE_TEXT, false)
                                    .setOverrideForType(TrackSelectionOverride(group.mediaTrackGroup, trackIndex))
                                    .build()
                                showSubtitles = false
                            }
                        }
                    }
                }
                Spacer(Modifier.height(10.dp))
                Button(onClick = { showOnlineSubs = true; showSubtitles = false }) {
                    Text("🔍 Procurar Legendas Online...")
                }
                Spacer(Modifier.height(8.dp))
                Button(onClick = { showSubtitles = false }) { Text("Fechar") }
            }
        }
        if (showOnlineSubs) {
            TvOnlineSubtitleSearchDialog(
                queryTitle = channel.name,
                onSelectSubtitle = { sub ->
                    val subConfig = MediaItem.SubtitleConfiguration.Builder(Uri.parse(sub.url))
                        .setMimeType(MimeTypes.APPLICATION_SUBRIP)
                        .setLanguage(sub.language.lowercase())
                        .setSelectionFlags(C.SELECTION_FLAG_DEFAULT)
                        .build()
                    val currentItem = player.currentMediaItem
                    if (currentItem != null) {
                        val updatedItem = currentItem.buildUpon()
                            .setSubtitleConfigurations(listOf(subConfig))
                            .build()
                        val currentPos = player.currentPosition
                        val wasPlaying = player.isPlaying
                        player.setMediaItem(updatedItem, currentPos)
                        player.prepare()
                        if (wasPlaying) player.play()
                    }
                    showOnlineSubs = false
                },
                onDismiss = { showOnlineSubs = false },
            )
        }
        if (showAudio) {
            val audioGroups = tracksState?.groups?.filter { it.type == C.TRACK_TYPE_AUDIO } ?: emptyList()
            Column(
                Modifier.align(Alignment.CenterEnd).width(360.dp)
                    .background(PlayerPanel, RoundedCornerShape(14.dp)).padding(20.dp),
            ) {
                Text("Áudio", color = Color.White, fontSize = 20.sp, fontWeight = FontWeight.Bold)
                Spacer(Modifier.height(14.dp))
                if (audioGroups.isEmpty()) {
                    Text(
                        "Sem faixas de áudio disponíveis para este conteúdo.",
                        color = PlayerMuted,
                        fontSize = 13.sp,
                        modifier = Modifier.padding(top = 8.dp),
                    )
                } else {
                    audioGroups.forEachIndexed { groupIndex, group ->
                        for (trackIndex in 0 until group.length) {
                            if (!group.isTrackSupported(trackIndex)) continue
                            val format = group.getTrackFormat(trackIndex)
                            val label = format.label
                                ?: format.language?.uppercase()
                                ?: "Faixa ${groupIndex + 1}"
                            SubtitleOption(label, selected = group.isTrackSelected(trackIndex)) {
                                player.trackSelectionParameters = player.trackSelectionParameters.buildUpon()
                                    .setTrackTypeDisabled(C.TRACK_TYPE_AUDIO, false)
                                    .setOverrideForType(TrackSelectionOverride(group.mediaTrackGroup, trackIndex))
                                    .build()
                                showAudio = false
                            }
                        }
                    }
                }
                Spacer(Modifier.height(10.dp))
                Button(onClick = { showAudio = false }) { Text("Fechar") }
            }
        }
    }
}
