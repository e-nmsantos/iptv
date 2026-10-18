package pt.iptvplayer.tv.data

import java.security.MessageDigest
import pt.iptvplayer.tv.model.Channel

internal const val XTREAM_EPISODE_PREFIX = "xtream-episode:"
internal const val STALKER_EPISODE_PREFIX = "stalker-episode:"

/**
 * Identity shared by resume points and watch history. Episodes are keyed by their provider
 * id alone — season labels differ between this app and the desktop one ("Temporada 1" vs
 * "Series - S01"), and the key must match on both sides for "Continuar a ver" to sync.
 */
internal fun playbackMediaKey(channel: Channel): String {
    val identity = if (channel.tvgId.startsWith(XTREAM_EPISODE_PREFIX) || channel.tvgId.startsWith(STALKER_EPISODE_PREFIX)) {
        "episode\u0000${channel.tvgId}"
    } else {
        listOf(channel.tvgId.ifBlank { channel.name }, channel.group, channel.type.name).joinToString("\u0000")
    }
    val digest = MessageDigest.getInstance("SHA-256").digest(identity.toByteArray(Charsets.UTF_8))
    return "media:" + digest.joinToString("") { "%02x".format(it) }
}
