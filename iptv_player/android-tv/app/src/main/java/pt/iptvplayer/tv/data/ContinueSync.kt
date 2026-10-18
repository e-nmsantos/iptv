package pt.iptvplayer.tv.data

import java.net.URLDecoder
import org.json.JSONObject
import pt.iptvplayer.tv.model.Channel
import pt.iptvplayer.tv.model.StreamType
import pt.iptvplayer.tv.model.WatchHistoryItem

/**
 * One "Continuar a ver" entry exchanged with the desktop app (the `continue` list of the
 * sync state). Entries carry provider identifiers only — no URLs or credentials; the
 * receiving device rebuilds episodes with its own playlist.
 */
internal sealed interface ContinueEntry {
    val positionMs: Long
    val durationMs: Long
    val upNext: Boolean
    val playedAtMillis: Long

    data class Catalog(
        val key: String,
        override val positionMs: Long,
        override val durationMs: Long,
        override val upNext: Boolean,
        override val playedAtMillis: Long,
    ) : ContinueEntry

    data class XtreamEpisode(
        val episodeId: String,
        val title: String,
        val season: Int,
        val extension: String,
        val logo: String,
        val seriesId: String,
        val seriesName: String,
        val seriesLogo: String,
        override val positionMs: Long,
        override val durationMs: Long,
        override val upNext: Boolean,
        override val playedAtMillis: Long,
    ) : ContinueEntry

    data class StalkerEpisode(
        val cmd: String,
        val episode: String,
        val season: Int,
        val logo: String,
        val seriesId: String,
        val seriesCategory: String,
        val seriesName: String,
        val seriesLogo: String,
        override val positionMs: Long,
        override val durationMs: Long,
        override val upNext: Boolean,
        override val playedAtMillis: Long,
    ) : ContinueEntry
}

internal object ContinueSyncCodec {
    const val MAX_ENTRIES = 200

    /** [catalogKey] gives the cross-device key of a catalogue film/series (null if none). */
    fun encode(item: WatchHistoryItem, catalogKey: (Channel) -> String?): JSONObject? {
        val channel = item.channel
        val base = JSONObject()
            .put("title", channel.name)
            .put("logo", channel.logo)
            .put("position_ms", item.positionMs)
            .put("duration_ms", item.durationMs)
            .put("up_next", item.upNext)
            .put("played_at", item.playedAtMillis)
        val parentUrl = item.parent?.url.orEmpty()
        return when {
            channel.tvgId.startsWith(XTREAM_EPISODE_PREFIX) && parentUrl.startsWith(XTREAM_SERIES) -> base
                .put("kind", "episode")
                .put("source", "xtream")
                .put("episode_id", channel.tvgId.removePrefix(XTREAM_EPISODE_PREFIX))
                .put("ext", extensionOf(channel.url))
                .put("season", seasonOf(channel.group))
                .put("series_id", parentUrl.removePrefix(XTREAM_SERIES).substringBefore('?'))
                .put("series_name", item.parent?.name.orEmpty())
                .put("series_logo", item.parent?.logo.orEmpty())
            channel.tvgId.startsWith(STALKER_EPISODE_PREFIX) && parentUrl.startsWith(STALKER_SERIES) -> {
                val reference = channel.tvgId.removePrefix(STALKER_EPISODE_PREFIX)
                val parts = parentUrl.removePrefix(STALKER_SERIES).split('/')
                if (parts.size < 2) return null
                base.put("kind", "episode")
                    .put("source", "stalker")
                    .put("cmd", reference.substringBeforeLast('#'))
                    .put("episode", reference.substringAfterLast('#'))
                    .put("season", seasonOf(channel.group))
                    .put("series_category", decode(parts[0]))
                    .put("series_id", decode(parts[1]))
                    .put("series_name", item.parent?.name.orEmpty())
                    .put("series_logo", item.parent?.logo.orEmpty())
            }
            else -> catalogKey(channel)?.let { base.put("kind", "catalog").put("key", it) }
        }
    }

    fun decode(json: JSONObject): ContinueEntry? = runCatching {
        val position = json.optLong("position_ms").coerceAtLeast(0)
        val duration = json.optLong("duration_ms").coerceAtLeast(0)
        val upNext = json.optBoolean("up_next")
        val playedAt = json.optLong("played_at")
        when (json.optString("kind")) {
            "catalog" -> json.optString("key").takeIf { it.startsWith("media:") && it.length < 200 }
                ?.let { ContinueEntry.Catalog(it, position, duration, upNext, playedAt) }
            "episode" -> when (json.optString("source")) {
                "xtream" -> ContinueEntry.XtreamEpisode(
                    episodeId = json.text("episode_id", 200).ifBlank { return null },
                    title = json.text("title", 500),
                    season = json.optInt("season"),
                    extension = json.text("ext", 16).ifBlank { "mp4" },
                    logo = json.text("logo"),
                    seriesId = json.text("series_id", 200).ifBlank { return null },
                    seriesName = json.text("series_name", 500),
                    seriesLogo = json.text("series_logo"),
                    positionMs = position,
                    durationMs = duration,
                    upNext = upNext,
                    playedAtMillis = playedAt,
                )
                "stalker" -> ContinueEntry.StalkerEpisode(
                    cmd = json.text("cmd", 4096).ifBlank { return null },
                    episode = json.text("episode", 32).ifBlank { return null },
                    season = json.optInt("season"),
                    logo = json.text("logo"),
                    seriesId = json.text("series_id", 200).ifBlank { return null },
                    seriesCategory = json.text("series_category", 200),
                    seriesName = json.text("series_name", 500),
                    seriesLogo = json.text("series_logo"),
                    positionMs = position,
                    durationMs = duration,
                    upNext = upNext,
                    playedAtMillis = playedAt,
                )
                else -> null
            }
            else -> null
        }
    }.getOrNull()

    fun xtreamSeriesReference(entry: ContinueEntry.XtreamEpisode) = Channel(
        name = entry.seriesName.ifBlank { "Série" },
        url = "$XTREAM_SERIES${entry.seriesId}",
        logo = entry.seriesLogo,
        type = StreamType.SERIES,
    )

    fun stalkerSeriesReference(entry: ContinueEntry.StalkerEpisode) = Channel(
        name = entry.seriesName.ifBlank { "Série" },
        url = "$STALKER_SERIES${JsonHttpClient.encode(entry.seriesCategory)}/${JsonHttpClient.encode(entry.seriesId)}",
        logo = entry.seriesLogo,
        type = StreamType.SERIES,
    )

    /** Synced Xtream episodes keep no credentials: resolved by `XtreamClient.episodeUrl` on play. */
    fun xtreamEpisodeUrl(episodeId: String, extension: String) =
        "$XTREAM_EPISODE_SCHEME${JsonHttpClient.encode(episodeId)}?ext=${JsonHttpClient.encode(extension)}"

    fun parseXtreamEpisodeUrl(url: String): Pair<String, String> {
        val body = url.removePrefix(XTREAM_EPISODE_SCHEME)
        val id = decode(body.substringBefore('?'))
        val ext = body.substringAfter("ext=", "mp4").substringBefore('&').let(::decode)
        return id to ext.ifBlank { "mp4" }
    }

    private fun extensionOf(url: String): String =
        if (url.startsWith(XTREAM_EPISODE_SCHEME)) {
            parseXtreamEpisodeUrl(url).second
        } else {
            url.substringBefore('?').substringAfterLast('/').substringAfterLast('.', "mp4")
        }

    private fun seasonOf(group: String): Int = Regex("\\d+").find(group)?.value?.toIntOrNull() ?: 0

    private fun decode(value: String): String = URLDecoder.decode(value, Charsets.UTF_8.name())

    private fun JSONObject.text(key: String, limit: Int = 2048): String = optString(key).take(limit)

    const val XTREAM_EPISODE_SCHEME = "xtream-episode://"
    private const val XTREAM_SERIES = "catalog://xtream/series/"
    private const val STALKER_SERIES = "catalog://stalker/series/"
}
