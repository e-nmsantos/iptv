package pt.iptvplayer.tv.playback

import android.content.Context
import androidx.annotation.OptIn
import androidx.media3.common.C
import androidx.media3.common.Format
import androidx.media3.common.MediaItem
import androidx.media3.common.Player
import androidx.media3.common.util.UnstableApi
import androidx.media3.datasource.DefaultDataSource
import androidx.media3.datasource.DefaultHttpDataSource
import androidx.media3.exoplayer.DefaultLoadControl
import androidx.media3.exoplayer.DefaultRenderersFactory
import androidx.media3.exoplayer.ExoPlayer
import androidx.media3.exoplayer.analytics.AnalyticsListener
import androidx.media3.exoplayer.source.DefaultMediaSourceFactory
import androidx.media3.exoplayer.upstream.DefaultBandwidthMeter
import androidx.media3.exoplayer.upstream.DefaultLoadErrorHandlingPolicy
import io.github.anilbeesetti.nextlib.media3ext.ffdecoder.NextRenderersFactory
import pt.iptvplayer.tv.data.DecoderPreference
import pt.iptvplayer.tv.data.PlayerSettings
import pt.iptvplayer.tv.data.TimeshiftBuffer
import pt.iptvplayer.tv.model.Channel
import pt.iptvplayer.tv.model.StreamType

/** Live technical details for the on-screen statistics panel. */
data class StreamStats(
    val resolution: String = "",
    val frameRate: String = "",
    val videoCodec: String = "",
    val audioCodec: String = "",
    val videoDecoder: String = "",
    val audioDecoder: String = "",
    val bitrateKbps: Long = 0,
    val bufferedMs: Long = 0,
    val droppedFrames: Int = 0,
)

/** Collects decoder names and dropped frames, which the Player API alone doesn't expose. */
@OptIn(UnstableApi::class)
class StreamStatsCollector(private val bandwidthMeter: DefaultBandwidthMeter) : AnalyticsListener {
    @Volatile private var videoDecoder = ""
    @Volatile private var audioDecoder = ""
    @Volatile private var droppedFrames = 0

    override fun onVideoDecoderInitialized(
        eventTime: AnalyticsListener.EventTime,
        decoderName: String,
        initializedTimestampMs: Long,
        initializationDurationMs: Long,
    ) {
        videoDecoder = decoderName
    }

    override fun onAudioDecoderInitialized(
        eventTime: AnalyticsListener.EventTime,
        decoderName: String,
        initializedTimestampMs: Long,
        initializationDurationMs: Long,
    ) {
        audioDecoder = decoderName
    }

    override fun onDroppedVideoFrames(eventTime: AnalyticsListener.EventTime, droppedFrames: Int, elapsedMs: Long) {
        this.droppedFrames += droppedFrames
    }

    fun snapshot(player: Player): StreamStats {
        val video = (player as? ExoPlayer)?.videoFormat
        val audio = (player as? ExoPlayer)?.audioFormat
        val measured = bandwidthMeter.bitrateEstimate
        val declared = listOfNotNull(video?.bitrate, audio?.bitrate).filter { it > 0 }.sum()
        return StreamStats(
            resolution = if (video != null && video.width > 0) "${video.width}×${video.height}" else "",
            frameRate = if (video != null && video.frameRate > 0) "%.0f fps".format(video.frameRate) else "",
            videoCodec = codecLabel(video),
            audioCodec = codecLabel(audio) + (audio?.channelCount?.takeIf { it > 0 }?.let { " · ${channelLayout(it)}" } ?: ""),
            videoDecoder = decoderLabel(videoDecoder),
            audioDecoder = decoderLabel(audioDecoder),
            bitrateKbps = (if (declared > 0) declared.toLong() else measured) / 1000,
            bufferedMs = player.totalBufferedDuration,
            droppedFrames = droppedFrames,
        )
    }

    private fun codecLabel(format: Format?): String {
        if (format == null) return ""
        val mime = format.sampleMimeType ?: format.containerMimeType ?: return ""
        return when (mime.substringAfter('/')) {
            "avc" -> "H.264"
            "hevc" -> "HEVC"
            "av01" -> "AV1"
            "x-vnd.on2.vp9" -> "VP9"
            "mp4a-latm" -> "AAC"
            "ac3" -> "Dolby Digital (AC-3)"
            "eac3" -> "Dolby Digital+ (E-AC-3)"
            "eac3-joc" -> "Dolby Atmos (E-AC-3 JOC)"
            "vnd.dts", "vnd.dts.hd" -> "DTS"
            "true-hd" -> "Dolby TrueHD"
            "mpeg" -> "MP3"
            "mpeg-L2" -> "MPEG-2 Áudio"
            "opus" -> "Opus"
            "mpeg2" -> "MPEG-2"
            else -> mime.substringAfter('/').uppercase()
        }
    }

    private fun channelLayout(channels: Int) = when (channels) {
        1 -> "mono"
        2 -> "estéreo"
        6 -> "5.1"
        8 -> "7.1"
        else -> "$channels canais"
    }

    private fun decoderLabel(name: String) = when {
        name.isBlank() -> ""
        name.startsWith("ffmpeg", ignoreCase = true) || name.contains("ffmpeg", ignoreCase = true) -> "FFmpeg (software)"
        name.startsWith("c2.android") || name.startsWith("OMX.google") -> "Software ($name)"
        else -> "Hardware ($name)"
    }
}

class PlayerSession(val player: ExoPlayer, val stats: StreamStatsCollector, val timeshiftEnabled: Boolean)

/**
 * Builds the ExoPlayer for one channel. Hardware decoders are tried first and the bundled
 * FFmpeg decoders cover AC-3/E-AC-3/DTS/TrueHD/MP2 audio that many TV boxes can't decode
 * (the classic "picture but no sound" IPTV complaint). HDMI passthrough is used automatically
 * whenever the connected receiver/TV advertises support for the codec.
 *
 * For live channels with timeshift enabled the buffer may grow to the configured byte budget
 * while paused, so pressing pause keeps receiving the broadcast and resuming continues from
 * where the viewer stopped instead of jumping to "now".
 */
@OptIn(UnstableApi::class)
fun buildPlayerSession(
    context: Context,
    channel: Channel,
    settings: PlayerSettings,
    preferredAudioMime: String? = null,
): PlayerSession {
    val bandwidthMeter = DefaultBandwidthMeter.Builder(context).build()
    val httpFactory = DefaultHttpDataSource.Factory()
        .setAllowCrossProtocolRedirects(true)
        .setConnectTimeoutMs(15_000)
        .setReadTimeoutMs(60_000)
        .setTransferListener(bandwidthMeter)
        .setUserAgent(channel.userAgent.ifBlank { "IPTVPlayerTV/0.9" })
        .setDefaultRequestProperties(
            mapOf("Connection" to "keep-alive", "Accept-Encoding" to "identity") + channel.requestHeaders,
        )
    val mediaSourceFactory = DefaultMediaSourceFactory(DefaultDataSource.Factory(context, httpFactory))
        .setLoadErrorHandlingPolicy(DefaultLoadErrorHandlingPolicy(12))
    val isLive = channel.type == StreamType.LIVE
    val timeshift = isLive && settings.timeshift != TimeshiftBuffer.OFF
    val loadControl = DefaultLoadControl.Builder().apply {
        if (timeshift) {
            setBufferDurationsMs(15_000, TIMESHIFT_MAX_BUFFER_MS, 2_500, 5_000)
            setTargetBufferBytes(settings.timeshift.megabytes * 1024 * 1024)
            setPrioritizeTimeOverSizeThresholds(false)
        } else {
            setBufferDurationsMs(15_000, 60_000, 2_500, 5_000)
        }
    }.build()
    val renderersFactory = NextRenderersFactory(context)
        .setExtensionRendererMode(
            when (settings.decoder) {
                DecoderPreference.AUTO -> DefaultRenderersFactory.EXTENSION_RENDERER_MODE_ON
                DecoderPreference.PREFER_FFMPEG -> DefaultRenderersFactory.EXTENSION_RENDERER_MODE_PREFER
            },
        )
        .setEnableDecoderFallback(true)
    logDecodersOnce
    val stats = StreamStatsCollector(bandwidthMeter)
    val player = ExoPlayer.Builder(context, renderersFactory)
        .setMediaSourceFactory(mediaSourceFactory)
        .setBandwidthMeter(bandwidthMeter)
        .setLoadControl(loadControl)
        .build()
        .apply {
            addAnalyticsListener(stats)
            if (preferredAudioMime != null) {
                trackSelectionParameters = trackSelectionParameters.buildUpon()
                    .setPreferredAudioMimeType(preferredAudioMime)
                    .build()
            }
            setWakeMode(C.WAKE_MODE_NETWORK)
            repeatMode = if (isLive) Player.REPEAT_MODE_ONE else Player.REPEAT_MODE_OFF
            setMediaItem(MediaItem.fromUri(channel.url))
            playWhenReady = true
            prepare()
        }
    return PlayerSession(player, stats, timeshift)
}

/** Upper bound for a paused live buffer; in practice the byte budget is reached first. */
private const val TIMESHIFT_MAX_BUFFER_MS = 60 * 60 * 1000

private val logDecodersOnce: Unit by lazy {
    android.util.Log.i("PlayerEngine", "Decoders: ${ffmpegCapabilities()}")
    Unit
}

/** True when the bundled FFmpeg build can decode [mimeType]. */
@OptIn(UnstableApi::class)
fun ffmpegSupports(mimeType: String?): Boolean = mimeType != null && runCatching {
    io.github.anilbeesetti.nextlib.media3ext.ffdecoder.FfmpegLibrary.isAvailable() &&
        io.github.anilbeesetti.nextlib.media3ext.ffdecoder.FfmpegLibrary.supportsFormat(mimeType)
}.getOrDefault(false)

/** Whether the bundled FFmpeg decoders loaded, and which problem codecs they cover. */
@OptIn(UnstableApi::class)
fun ffmpegCapabilities(): String = runCatching {
    if (!io.github.anilbeesetti.nextlib.media3ext.ffdecoder.FfmpegLibrary.isAvailable()) {
        return@runCatching "Indisponível nesta box"
    }
    val codecs = listOf(
        "AC-3" to androidx.media3.common.MimeTypes.AUDIO_AC3,
        "E-AC-3" to androidx.media3.common.MimeTypes.AUDIO_E_AC3,
        "DTS" to androidx.media3.common.MimeTypes.AUDIO_DTS,
        "TrueHD" to androidx.media3.common.MimeTypes.AUDIO_TRUEHD,
        "MP2" to androidx.media3.common.MimeTypes.AUDIO_MPEG_L2,
    ).filter { (_, mime) -> io.github.anilbeesetti.nextlib.media3ext.ffdecoder.FfmpegLibrary.supportsFormat(mime) }
        .joinToString(", ") { it.first }
    "FFmpeg ${io.github.anilbeesetti.nextlib.media3ext.ffdecoder.FfmpegLibrary.getVersion()} · ${codecs.ifBlank { "sem codecs de áudio extra" }}"
}.getOrElse { "Erro: ${it.message}" }
