package pt.iptvplayer.tv.ui

import android.net.Uri
import android.os.SystemClock
import android.view.KeyEvent
import android.view.LayoutInflater
import android.widget.FrameLayout
import androidx.activity.compose.BackHandler
import androidx.annotation.OptIn
import androidx.compose.foundation.background
import androidx.compose.foundation.focusGroup
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
import androidx.compose.runtime.key
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.input.key.onPreviewKeyEvent
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.media3.common.C
import androidx.media3.common.MediaItem
import androidx.media3.common.MimeTypes
import androidx.media3.common.PlaybackException
import androidx.media3.common.Player
import androidx.media3.common.TrackSelectionOverride
import androidx.media3.common.Tracks
import androidx.media3.common.util.UnstableApi
import androidx.media3.datasource.HttpDataSource
import androidx.media3.ui.PlayerView
import androidx.tv.material3.Text
import kotlinx.coroutines.delay
import pt.iptvplayer.tv.R
import pt.iptvplayer.tv.data.DecoderPreference
import pt.iptvplayer.tv.data.PlayerSettings
import pt.iptvplayer.tv.data.VideoSurface
import pt.iptvplayer.tv.model.Channel
import pt.iptvplayer.tv.model.EpgProgram
import pt.iptvplayer.tv.model.EpgReminder
import pt.iptvplayer.tv.model.StreamType
import pt.iptvplayer.tv.playback.PlaybackMetrics
import pt.iptvplayer.tv.playback.StreamStats
import pt.iptvplayer.tv.playback.buildPlayerSession
import pt.iptvplayer.tv.playback.ffmpegSupports

@Composable
@OptIn(UnstableApi::class)
fun PlayerScreen(
    channel: Channel,
    channels: List<Channel>,
    settings: PlayerSettings,
    epg: Map<String, List<EpgProgram>>,
    nextEpisode: Channel?,
    dueReminder: EpgReminder?,
    notice: String? = null,
    canRecallPrevious: Boolean,
    onToggleFavorite: (Channel) -> Unit,
    onSaveProgress: (Channel, Long, Long) -> Unit,
    onSelectChannel: (Channel) -> Unit,
    onRecallPrevious: () -> Unit,
    onPlayNextEpisode: (Channel) -> Unit,
    onEpisodeFinished: (Channel) -> Unit,
    onToggleStats: () -> Unit,
    onWatchReminder: (EpgReminder) -> Unit,
    onDismissReminder: () -> Unit,
    onBack: () -> Unit,
) {
    val context = LocalContext.current
    val isLive = channel.type == StreamType.LIVE
    var guideVisible by remember { mutableStateOf(false) }
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
    var seekTick by remember(channel.url) { mutableIntStateOf(0) }
    var seekBarVisible by remember { mutableStateOf(false) }
    var controlsVisible by remember(channel.url) { mutableStateOf(false) }
    var controlsHideTick by remember(channel.url) { mutableIntStateOf(0) }
    var isPlaying by remember(channel.url) { mutableStateOf(true) }
    var paused by remember(channel.url) { mutableStateOf(false) }
    var showControlsHint by remember(channel.url) { mutableStateOf(!isLive) }
    // Live "now/next" banner, re-shown on every zap and with the INFO key.
    var infoTick by remember(channel.url) { mutableIntStateOf(if (isLive) 1 else 0) }
    var infoVisible by remember(channel.url) { mutableStateOf(isLive) }
    var statsVisible by remember { mutableStateOf(settings.showStreamStats) }
    var stats by remember(channel.url) { mutableStateOf(StreamStats()) }
    var nowMillis by remember { mutableLongStateOf(System.currentTimeMillis()) }
    // Number zapping.
    val numberEntry = remember { ChannelNumberEntry() }
    var typedNumber by remember { mutableStateOf("") }
    var numberTick by remember { mutableIntStateOf(0) }
    // Live pause (timeshift): how far behind the broadcast the picture currently is.
    var behindLiveMs by remember(channel.url) { mutableLongStateOf(0L) }
    var livePausedAt by remember(channel.url) { mutableStateOf<Long?>(null) }
    var liveBaselineOffsetMs by remember(channel.url) { mutableStateOf<Long?>(null) }
    var transientNotice by remember(channel.url) { mutableStateOf<String?>(null) }
    // End-of-episode handling.
    var nextCardVisible by remember(channel.url) { mutableStateOf(false) }
    var nextCountdown by remember(channel.url) { mutableStateOf<Int?>(null) }
    var nextDismissed by remember(channel.url) { mutableStateOf(false) }
    var ended by remember(channel.url) { mutableStateOf(false) }

    val metrics = remember(channel.url) { PlaybackMetrics() }
    val audioPanelFocus = remember { FocusRequester() }
    val subtitlePanelFocus = remember { FocusRequester() }
    LaunchedEffect(showAudio) {
        if (showAudio) { delay(80); runCatching { audioPanelFocus.requestFocus() } }
    }
    LaunchedEffect(showSubtitles) {
        if (showSubtitles) { delay(80); runCatching { subtitlePanelFocus.requestFocus() } }
    }
    val currentIndex = channels.indexOfFirst { sameChannel(it, channel) }.coerceAtLeast(0)
    // HLS often lists AAC, AC-3 and E-AC-3 renditions in one track group, which the track
    // selector hands wholesale to the hardware renderer (it handles the AAC one), so the
    // Dolby tracks show as unsupported. Picking one rebuilds the player with FFmpeg first.
    var ffmpegAudioMime by remember(channel.url) { mutableStateOf<String?>(null) }
    var restorePositionMs by remember(channel.url) { mutableStateOf<Long?>(null) }
    val session = remember(channel.url, ffmpegAudioMime) {
        val effective = if (ffmpegAudioMime != null) settings.copy(decoder = DecoderPreference.PREFER_FFMPEG) else settings
        buildPlayerSession(context, channel, effective, ffmpegAudioMime)
    }
    val player = session.player

    fun zap(offset: Int) {
        if (channels.size < 2) return
        val index = (currentIndex + offset + channels.size) % channels.size
        onSelectChannel(channels[index])
    }
    fun seek(deltaMs: Long) {
        if (isLive) return
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
    fun flash(message: String) {
        transientNotice = message
    }
    fun showInfo() {
        infoVisible = true
        infoTick++
    }
    fun pauseLive() {
        player.pause()
        if (livePausedAt == null) livePausedAt = SystemClock.elapsedRealtime()
        if (!session.timeshiftEnabled) flash("Pausa em direto desligada nas Definições: ao retomar, o canal volta ao direto.")
        showInfo()
    }
    fun resumeLive() {
        livePausedAt?.let { pausedAt ->
            if (session.timeshiftEnabled && !player.isCurrentMediaItemLive) {
                behindLiveMs += SystemClock.elapsedRealtime() - pausedAt
            }
        }
        livePausedAt = null
        if (!session.timeshiftEnabled && !player.isCurrentMediaItemLive) {
            // Without a timeshift buffer the stalled connection is useless; start fresh at "now".
            player.stop()
            player.setMediaItem(MediaItem.fromUri(channel.url))
            player.prepare()
        }
        player.play()
        showInfo()
    }
    fun togglePlayPause() {
        if (isLive) {
            if (player.playWhenReady) pauseLive() else resumeLive()
        } else if (player.isPlaying) {
            player.pause()
        } else {
            player.play()
        }
    }
    fun returnToLive() {
        if (player.isCurrentMediaItemLive) {
            player.seekToDefaultPosition()
        } else {
            player.stop()
            player.setMediaItem(MediaItem.fromUri(channel.url))
            player.prepare()
        }
        player.play()
        behindLiveMs = 0
        livePausedAt = null
        flash("De volta ao direto")
        showInfo()
    }
    fun liveSeek(deltaMs: Long) {
        if (!player.isCurrentMediaItemSeekable) {
            flash("Este canal não permite avançar ou recuar. Usa ⏯ para pausar o direto.")
            return
        }
        player.seekTo((player.currentPosition + deltaMs).coerceAtLeast(0))
        showInfo()
    }
    fun playNext() {
        val next = nextEpisode ?: return
        nextCardVisible = false
        nextCountdown = null
        onPlayNextEpisode(next)
    }
    fun cancelNext() {
        nextCardVisible = false
        nextCountdown = null
        nextDismissed = true
        onEpisodeFinished(channel)
    }

    val handleKeyCode: (Int) -> Boolean = { keyCode ->
        // Any open panel or card takes the D-pad for its own focus navigation, so ▲/▼ never
        // zap away underneath it.
        val overlayOpen = controlsVisible || showAudio || showSubtitles || nextCardVisible || dueReminder != null
        when (playerKeyAction(keyCode, guideVisible, isLive, overlayOpen)) {
            PlayerKeyAction.TOGGLE_GUIDE -> { guideVisible = !guideVisible; true }
            PlayerKeyAction.OPEN_GUIDE -> { guideVisible = true; true }
            PlayerKeyAction.ZAP_PREVIOUS -> { zap(-1); true }
            PlayerKeyAction.ZAP_NEXT -> { zap(1); true }
            PlayerKeyAction.RECALL_PREVIOUS -> {
                if (canRecallPrevious) onRecallPrevious() else flash("Ainda não há canal anterior.")
                true
            }
            PlayerKeyAction.PLAY_PAUSE -> { togglePlayPause(); true }
            PlayerKeyAction.PLAY -> { if (isLive) resumeLive() else player.play(); true }
            PlayerKeyAction.PAUSE -> { if (isLive) pauseLive() else player.pause(); true }
            PlayerKeyAction.TOGGLE_FAVORITE -> { onToggleFavorite(channel); true }
            PlayerKeyAction.SEEK_FORWARD -> { seek(10_000); true }
            PlayerKeyAction.SEEK_BACKWARD -> { seek(-10_000); true }
            PlayerKeyAction.LIVE_SEEK_FORWARD -> { liveSeek(30_000); true }
            PlayerKeyAction.LIVE_SEEK_BACKWARD -> { liveSeek(-30_000); true }
            PlayerKeyAction.NEXT_EPISODE -> {
                if (nextEpisode != null) playNext() else flash("Não há próximo episódio.")
                true
            }
            PlayerKeyAction.TOGGLE_SUBTITLES -> { showSubtitles = true; true }
            PlayerKeyAction.OPEN_AUDIO -> { showAudio = true; true }
            PlayerKeyAction.TOGGLE_STATS -> { statsVisible = !statsVisible; onToggleStats(); true }
            PlayerKeyAction.TOGGLE_INFO -> {
                if (infoVisible) infoVisible = false else showInfo()
                true
            }
            PlayerKeyAction.SHOW_CONTROLS -> { controlsVisible = true; controlsHideTick++; true }
            PlayerKeyAction.DIGIT -> {
                digitForKey(keyCode)?.let { digit ->
                    typedNumber = numberEntry.push(digit)
                    numberTick++
                }
                true
            }
            PlayerKeyAction.DELEGATE -> false
        }
    }

    BackHandler {
        when {
            typedNumber.isNotEmpty() -> { numberEntry.clear(); typedNumber = "" }
            guideVisible -> guideVisible = false
            showSubtitles -> showSubtitles = false
            showAudio -> showAudio = false
            controlsVisible -> controlsVisible = false
            nextCardVisible -> cancelNext()
            infoVisible && isLive -> infoVisible = false
            else -> onBack()
        }
    }
    DisposableEffect(player) {
        val listener = object : Player.Listener {
            override fun onIsPlayingChanged(playing: Boolean) {
                isPlaying = playing
            }

            override fun onPlayWhenReadyChanged(playWhenReady: Boolean, reason: Int) {
                paused = !playWhenReady
            }

            override fun onPlaybackStateChanged(playbackState: Int) {
                buffering = playbackState == Player.STATE_BUFFERING || playbackState == Player.STATE_IDLE
                if (playbackState == Player.STATE_BUFFERING) metrics.buffering()
                if (playbackState == Player.STATE_READY) {
                    hasPlayed = true
                    if (isLive && liveBaselineOffsetMs == null && player.isCurrentMediaItemLive) {
                        liveBaselineOffsetMs = player.currentLiveOffset.takeIf { it != C.TIME_UNSET }
                    }
                    val restore = restorePositionMs
                    if (!isLive && restore != null && restore > 0) {
                        player.seekTo(restore)
                        restorePositionMs = null
                        resumeApplied = true
                    } else if (!isLive && !resumeApplied && channel.resumePositionMs > 0) {
                        player.seekTo(channel.resumePositionMs)
                        resumeApplied = true
                    }
                }
                if (playbackState == Player.STATE_ENDED && !isLive) ended = true
            }

            override fun onPlayerError(error: PlaybackException) {
                buffering = false
                val httpError = generateSequence<Throwable>(error) { it.cause }
                    .filterIsInstance<HttpDataSource.InvalidResponseCodeException>()
                    .firstOrNull()
                lastFailure = when {
                    httpError != null -> "HTTP ${httpError.responseCode} — o servidor recusou o stream"
                    error.errorCode == PlaybackException.ERROR_CODE_DECODING_FORMAT_UNSUPPORTED ||
                        error.errorCode == PlaybackException.ERROR_CODE_DECODER_INIT_FAILED ->
                        "Formato não suportado por esta box. Experimenta \"Preferir FFmpeg\" nas Definições."
                    else -> "${error.errorCodeName}: ${error.message ?: "stream indisponível"}"
                }
                if (!isLive) playbackError = lastFailure
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
    // Leaving the app (Home, input switch) must not keep streaming behind the launcher.
    // Live channels drop the connection and rejoin "now" on return; VOD pauses in place.
    val lifecycleOwner = LocalLifecycleOwner.current
    DisposableEffect(lifecycleOwner, player) {
        var stoppedInBackground = false
        var resumeOnStart = false
        val observer = LifecycleEventObserver { _, event ->
            when (event) {
                Lifecycle.Event.ON_STOP -> {
                    resumeOnStart = player.playWhenReady
                    if (isLive) {
                        player.stop()
                        stoppedInBackground = true
                    } else {
                        onSaveProgress(channel, player.currentPosition.coerceAtLeast(0), player.duration.coerceAtLeast(0))
                        player.pause()
                    }
                }
                Lifecycle.Event.ON_START -> {
                    if (stoppedInBackground) {
                        stoppedInBackground = false
                        behindLiveMs = 0
                        liveBaselineOffsetMs = null
                        livePausedAt = if (resumeOnStart) null else SystemClock.elapsedRealtime()
                        player.prepare()
                    }
                    if (resumeOnStart) player.play()
                    resumeOnStart = false
                }
                else -> Unit
            }
        }
        lifecycleOwner.lifecycle.addObserver(observer)
        onDispose { lifecycleOwner.lifecycle.removeObserver(observer) }
    }
    // Live reconnection watchdog.
    LaunchedEffect(player, channel.url) {
        if (!isLive) return@LaunchedEffect
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
            behindLiveMs = 0
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
    // Clock + live offset + statistics, once a second.
    LaunchedEffect(player) {
        while (true) {
            nowMillis = System.currentTimeMillis()
            if (isLive && player.isCurrentMediaItemLive) {
                val offset = player.currentLiveOffset
                val baseline = liveBaselineOffsetMs
                if (offset != C.TIME_UNSET && baseline != null) {
                    behindLiveMs = (offset - baseline).coerceAtLeast(0).let { if (it < 3_000) 0 else it }
                }
            }
            if (statsVisible) stats = session.stats.snapshot(player)
            delay(1_000)
        }
    }
    // Persist resume points regularly, not only when leaving the player.
    LaunchedEffect(player) {
        if (isLive) return@LaunchedEffect
        while (true) {
            delay(30_000)
            if (player.isPlaying) {
                onSaveProgress(channel, player.currentPosition.coerceAtLeast(0), player.duration.coerceAtLeast(0))
            }
        }
    }
    // "A seguir" card: offered in the last seconds of an episode, auto-played after it ends.
    LaunchedEffect(player, nextEpisode) {
        if (isLive || nextEpisode == null) return@LaunchedEffect
        while (!nextCardVisible) {
            val duration = player.duration
            if (!nextDismissed && duration > 60_000 && duration - player.currentPosition in 1..NEXT_CARD_LEAD_MS) {
                nextCardVisible = true
            }
            delay(1_000)
        }
    }
    LaunchedEffect(ended) {
        if (!ended) return@LaunchedEffect
        when {
            nextEpisode == null -> {
                delay(1_500)
                onBack()
            }
            nextDismissed -> Unit
            settings.autoplayNextEpisode -> {
                nextCardVisible = true
                for (seconds in AUTOPLAY_COUNTDOWN_SECONDS downTo 1) {
                    nextCountdown = seconds
                    delay(1_000)
                    if (!nextCardVisible) return@LaunchedEffect
                }
                playNext()
            }
            else -> {
                nextCardVisible = true
                onEpisodeFinished(channel)
            }
        }
    }
    LaunchedEffect(numberTick) {
        if (numberTick == 0) return@LaunchedEffect
        delay(1_800)
        val index = numberEntry.commit(channels.size)
        typedNumber = ""
        if (index == null) {
            flash("Esse número de canal não existe nesta lista.")
        } else if (index != currentIndex) {
            onSelectChannel(channels[index])
        }
    }
    LaunchedEffect(infoTick) {
        if (infoTick == 0) return@LaunchedEffect
        delay(INFO_BANNER_MS)
        if (player.playWhenReady) infoVisible = false
    }
    LaunchedEffect(transientNotice) {
        if (transientNotice == null) return@LaunchedEffect
        delay(3_500)
        transientNotice = null
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
    var positionTick by remember(channel.url) { mutableIntStateOf(0) }
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
            // The surface type is fixed at inflation, so a change rebuilds the view.
            key(settings.videoSurface) { AndroidView(
                factory = { viewContext ->
                    val inflationParent = FrameLayout(viewContext)
                    val layout = when (settings.videoSurface) {
                        VideoSurface.TEXTURE -> R.layout.player_view_texture
                        VideoSurface.SURFACE -> R.layout.player_view_surface
                    }
                    (LayoutInflater.from(viewContext).inflate(
                        layout, inflationParent, false,
                    ) as PlayerView).apply {
                        this.player = player
                    }
                },
                update = { view ->
                    view.player = player
                    view.setOnKeyListener { _, keyCode, event ->
                        event.action == KeyEvent.ACTION_DOWN && handleKeyCode(keyCode)
                    }
                    if (!guideVisible && !controlsVisible && !nextCardVisible && dueReminder == null) view.requestFocus()
                },
                modifier = Modifier.fillMaxSize(),
            ) }
            if (((buffering && !hasPlayed) || notice != null) && playbackError == null) {
                Text(
                    notice ?: "A ligar ao canal…",
                    color = Color.White,
                    fontSize = 18.sp,
                    modifier = Modifier.align(Alignment.Center).background(TvColors.Toast, RoundedCornerShape(9.dp)).padding(14.dp),
                )
            }
            if (isLive && paused && hasPlayed && playbackError == null) {
                Text(
                    if (session.timeshiftEnabled) "⏸  Em pausa — o direto continua a ser guardado" else "⏸  Em pausa",
                    color = Color.White,
                    fontSize = 18.sp,
                    modifier = Modifier.align(Alignment.Center).background(TvColors.Toast, RoundedCornerShape(9.dp)).padding(14.dp),
                )
            }
            playbackError?.let { message ->
                Column(
                    Modifier.align(Alignment.Center).background(TvColors.Dialog, RoundedCornerShape(14.dp)).padding(28.dp),
                    horizontalAlignment = Alignment.CenterHorizontally,
                ) {
                    Text("Não foi possível reproduzir", color = Color.White, fontSize = 22.sp)
                    Text(message, color = PlayerMuted, modifier = Modifier.padding(vertical = 12.dp))
                    BrandButton(onClick = {
                        playbackError = null
                        buffering = true
                        player.prepare()
                        player.play()
                    }) { Text("Tentar novamente") }
                    BrandButton(onClick = { guideVisible = true }, modifier = Modifier.padding(top = 8.dp)) { Text("Escolher outro canal") }
                }
            }
        }
        if (statsVisible) {
            StreamStatsOverlay(stats, session.timeshiftEnabled, Modifier.align(Alignment.TopStart).padding(28.dp))
        }
        if (typedNumber.isNotEmpty()) {
            val previewIndex = typedNumber.toIntOrNull()?.minus(1)
            ChannelNumberOverlay(
                digits = typedNumber,
                preview = previewIndex?.let { channels.getOrNull(it) },
                modifier = Modifier.align(Alignment.TopEnd).padding(28.dp),
            )
        }
        transientNotice?.let { message ->
            Text(
                message,
                color = Color.White,
                fontSize = 15.sp,
                modifier = Modifier.align(Alignment.TopCenter).padding(top = 28.dp)
                    .background(TvColors.Scrim, RoundedCornerShape(10.dp)).padding(horizontal = 18.dp, vertical = 10.dp),
            )
        }
        if (isLive && infoVisible && !guideVisible && !controlsVisible) {
            LiveInfoBanner(
                channel = channel,
                channelNumber = currentIndex + 1,
                programmes = epg[channel.tvgId].orEmpty(),
                nowMillis = nowMillis,
                behindLiveMs = behindLiveMs,
                modifier = Modifier.align(Alignment.BottomCenter),
            )
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
        if (showControlsHint && !isLive && !guideVisible && !controlsVisible) {
            Text(
                "▲ ou ▼ para abrir os controlos",
                color = PlayerMuted,
                fontSize = 13.sp,
                modifier = Modifier.align(Alignment.BottomCenter).padding(bottom = 24.dp)
                    .background(TvColors.Toast, RoundedCornerShape(8.dp)).padding(horizontal = 14.dp, vertical = 8.dp),
            )
        }
        if (seekBarVisible && !controlsVisible && !isLive && !guideVisible) {
            val position = remember(positionTick) { player.currentPosition.coerceAtLeast(0) }
            val duration = remember(positionTick) { player.duration.coerceAtLeast(0) }
            Column(
                Modifier.align(Alignment.BottomCenter).fillMaxWidth().padding(horizontal = 48.dp, vertical = 30.dp)
                    .background(TvColors.OverlaySoft, RoundedCornerShape(12.dp)).padding(20.dp),
            ) {
                ProgressLine(if (duration > 0) position.toFloat() / duration else 0f, Modifier.fillMaxWidth(), height = 6)
                Spacer(Modifier.height(10.dp))
                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                    Text(formatDuration(position), color = Color.White, fontSize = 14.sp)
                    Text(if (duration > 0) formatDuration(duration) else "--:--", color = PlayerMuted, fontSize = 14.sp)
                }
            }
        }
        // Discoverable, D-pad + OK only control panels — the sole reliable input on a bare
        // remote with no colour/media-transport/captions keys (e.g. a minimal Android TV box
        // remote). Opened with D-pad up/down (VOD) or right (live).
        if (controlsVisible && !guideVisible) {
            Column(
                Modifier.align(Alignment.BottomCenter).fillMaxWidth().padding(horizontal = 40.dp, vertical = 28.dp)
                    .background(TvColors.OverlaySoft, RoundedCornerShape(14.dp)).padding(20.dp),
            ) {
                if (isLive) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Text(channel.name, color = Color.White, fontSize = 18.sp, fontWeight = FontWeight.Bold)
                        Spacer(Modifier.width(12.dp))
                        if (behindLiveMs > 1_000) {
                            Badge("EM DIFERIDO −${formatDuration(behindLiveMs)}", TvColors.Warning, Color.Black)
                        } else {
                            Badge("● DIRETO", TvColors.Live, Color.White)
                        }
                    }
                    Spacer(Modifier.height(14.dp))
                    LiveControlBar(
                        isPaused = paused,
                        behindLive = behindLiveMs > 1_000 || livePausedAt != null,
                        isFavorite = channel.favorite,
                        statsVisible = statsVisible,
                        canRecall = canRecallPrevious,
                        onPlayPause = { togglePlayPause() },
                        onGoLive = { returnToLive() },
                        onSubtitles = { showSubtitles = true },
                        onAudio = { showAudio = true },
                        onStats = { statsVisible = !statsVisible; onToggleStats() },
                        onToggleFavorite = { onToggleFavorite(channel) },
                        onRecall = onRecallPrevious,
                        onInteract = { controlsHideTick++ },
                    )
                } else {
                    val position = remember(positionTick) { player.currentPosition.coerceAtLeast(0) }
                    val duration = remember(positionTick) { player.duration.coerceAtLeast(0) }
                    ProgressLine(if (duration > 0) position.toFloat() / duration else 0f, Modifier.fillMaxWidth(), height = 6)
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
                        hasNextEpisode = nextEpisode != null,
                        onSeekBackward = { seek(-10_000) },
                        onPlayPause = { togglePlayPause() },
                        onSeekForward = { seek(10_000) },
                        onSubtitles = { showSubtitles = true },
                        onAudio = { showAudio = true },
                        onSpeed = { cycleSpeed() },
                        onToggleFavorite = { onToggleFavorite(channel) },
                        onNextEpisode = { playNext() },
                        onInteract = { controlsHideTick++ },
                    )
                }
            }
        }
        if (nextCardVisible && nextEpisode != null && !guideVisible) {
            NextEpisodeCard(
                next = nextEpisode,
                secondsLeft = nextCountdown,
                onPlayNow = { playNext() },
                onCancel = { cancelNext() },
                modifier = Modifier.align(Alignment.BottomEnd).padding(36.dp),
            )
        }
        dueReminder?.let { reminder ->
            ReminderCard(
                reminder = reminder,
                onWatch = { onWatchReminder(reminder) },
                onDismiss = onDismissReminder,
                modifier = Modifier.align(Alignment.TopEnd).padding(28.dp),
            )
        }
        if (showSubtitles) {
            val textGroups = tracksState?.groups?.filter { it.type == C.TRACK_TYPE_TEXT } ?: emptyList()
            Column(
                Modifier.align(Alignment.CenterEnd).width(360.dp)
                    .background(PlayerPanel, RoundedCornerShape(14.dp)).padding(20.dp)
                    .focusRequester(subtitlePanelFocus).focusGroup(),
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
                if (!isLive) {
                    BrandButton(onClick = { showOnlineSubs = true; showSubtitles = false }) {
                        Text("🔍 Procurar Legendas Online...")
                    }
                    Spacer(Modifier.height(8.dp))
                }
                BrandButton(onClick = { showSubtitles = false }) { Text("Fechar") }
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
                    .background(PlayerPanel, RoundedCornerShape(14.dp)).padding(20.dp)
                    .focusRequester(audioPanelFocus).focusGroup(),
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
                            val format = group.getTrackFormat(trackIndex)
                            val supported = group.isTrackSupported(trackIndex)
                            val base = format.label
                                ?: format.language?.uppercase()
                                ?: "Faixa ${groupIndex + 1}"
                            val codec = format.sampleMimeType?.substringAfter('/')?.uppercase().orEmpty()
                            val label = listOf(base, codec).filter(String::isNotBlank).joinToString(" · ") +
                                if (supported) "" else " (não suportada)"
                            if (!supported) {
                                if (ffmpegSupports(format.sampleMimeType)) {
                                    SubtitleOption(
                                        listOf(base, codec).filter(String::isNotBlank).joinToString(" · ") + " · via FFmpeg",
                                        selected = false,
                                    ) {
                                        restorePositionMs = player.currentPosition.takeIf { !isLive }
                                        ffmpegAudioMime = format.sampleMimeType
                                        showAudio = false
                                    }
                                } else {
                                    Text(label, color = PlayerMuted, fontSize = 13.sp, modifier = Modifier.padding(vertical = 8.dp, horizontal = 14.dp))
                                }
                                continue
                            }
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
                BrandButton(onClick = { showAudio = false }) { Text("Fechar") }
            }
        }
    }
}

private const val INFO_BANNER_MS = 5_000L
private const val NEXT_CARD_LEAD_MS = 20_000L
private const val AUTOPLAY_COUNTDOWN_SECONDS = 10
