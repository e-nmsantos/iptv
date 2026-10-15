package pt.iptvplayer.tv.data

import android.content.Context
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

enum class DecoderPreference(val label: String, val description: String) {
    AUTO("Automático", "Hardware primeiro; FFmpeg para AC3, E-AC3, DTS e outros codecs não suportados."),
    PREFER_FFMPEG("Preferir FFmpeg", "Usa o FFmpeg mesmo quando a box diz suportar o codec. Útil se houver som em falta ou dessincronizado."),
}

/** Memory set aside to keep receiving a live channel while it is paused. 0 disables live pause. */
enum class TimeshiftBuffer(val megabytes: Int, val label: String) {
    OFF(0, "Desligada"),
    SMALL(64, "64 MB (≈ 2–4 min)"),
    MEDIUM(128, "128 MB (≈ 4–8 min)"),
    LARGE(256, "256 MB (≈ 8–16 min)"),
}

data class PlayerSettings(
    val decoder: DecoderPreference = DecoderPreference.AUTO,
    val timeshift: TimeshiftBuffer = TimeshiftBuffer.MEDIUM,
    val autoplayNextEpisode: Boolean = true,
    val resumeLastChannelOnStart: Boolean = false,
    val showStreamStats: Boolean = false,
)

/** Small, synchronous preference store; every write is published through [settings]. */
class PlayerPreferences(context: Context) {
    private val preferences = context.applicationContext.getSharedPreferences("player-settings", Context.MODE_PRIVATE)
    private val mutableSettings = MutableStateFlow(read())
    val settings: StateFlow<PlayerSettings> = mutableSettings.asStateFlow()

    fun update(transform: (PlayerSettings) -> PlayerSettings) {
        val next = transform(mutableSettings.value)
        preferences.edit()
            .putString(KEY_DECODER, next.decoder.name)
            .putString(KEY_TIMESHIFT, next.timeshift.name)
            .putBoolean(KEY_AUTOPLAY_NEXT, next.autoplayNextEpisode)
            .putBoolean(KEY_RESUME_LAST, next.resumeLastChannelOnStart)
            .putBoolean(KEY_STATS, next.showStreamStats)
            .apply()
        mutableSettings.value = next
    }

    private fun read() = PlayerSettings(
        decoder = enumOrDefault(preferences.getString(KEY_DECODER, null), DecoderPreference.AUTO),
        timeshift = enumOrDefault(preferences.getString(KEY_TIMESHIFT, null), TimeshiftBuffer.MEDIUM),
        autoplayNextEpisode = preferences.getBoolean(KEY_AUTOPLAY_NEXT, true),
        resumeLastChannelOnStart = preferences.getBoolean(KEY_RESUME_LAST, false),
        showStreamStats = preferences.getBoolean(KEY_STATS, false),
    )

    private inline fun <reified T : Enum<T>> enumOrDefault(value: String?, default: T): T =
        value?.let { runCatching { enumValueOf<T>(it) }.getOrNull() } ?: default

    private companion object {
        const val KEY_DECODER = "decoder"
        const val KEY_TIMESHIFT = "timeshift"
        const val KEY_AUTOPLAY_NEXT = "autoplay_next_episode"
        const val KEY_RESUME_LAST = "resume_last_channel"
        const val KEY_STATS = "show_stream_stats"
    }
}
