package pt.iptvplayer.tv.data

import org.json.JSONObject
import pt.iptvplayer.tv.model.Channel
import pt.iptvplayer.tv.model.StreamType

/**
 * Serialises a replayable [Channel] reference (the value handed to `preparePlayback`, before
 * any Stalker link resolution) so history rows and reminders can start playback again later.
 * The JSON may hold provider credentials inside URLs, so callers must encrypt it at rest.
 */
internal object ChannelCodec {
    fun encode(channel: Channel): String = JSONObject()
        .put("id", channel.id)
        .put("name", channel.name)
        .put("url", channel.url)
        .put("group", channel.group)
        .put("logo", channel.logo)
        .put("tvg_id", channel.tvgId)
        .put("user_agent", channel.userAgent)
        .put("referer", channel.referer)
        .put("type", channel.type.name)
        .put("quality", channel.quality)
        .put("headers", JSONObject(channel.customHeaders as Map<*, *>))
        .toString()

    fun decode(raw: String): Channel? = runCatching {
        val json = JSONObject(raw)
        val headers = json.optJSONObject("headers")
        Channel(
            id = json.optLong("id"),
            name = json.getString("name"),
            url = json.getString("url"),
            group = json.optString("group", "Geral"),
            logo = json.optString("logo"),
            tvgId = json.optString("tvg_id"),
            userAgent = json.optString("user_agent"),
            referer = json.optString("referer"),
            type = runCatching { StreamType.valueOf(json.optString("type")) }.getOrDefault(StreamType.LIVE),
            quality = json.optString("quality"),
            customHeaders = buildMap {
                headers?.keys()?.forEach { key -> put(key, headers.optString(key)) }
            },
        )
    }.getOrNull()?.takeIf { it.name.isNotBlank() && it.url.isNotBlank() }
}
