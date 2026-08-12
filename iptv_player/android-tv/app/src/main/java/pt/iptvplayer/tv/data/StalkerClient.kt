package pt.iptvplayer.tv.data

import java.net.URLDecoder
import java.nio.charset.StandardCharsets
import java.security.MessageDigest
import org.json.JSONArray
import org.json.JSONObject
import pt.iptvplayer.tv.model.Channel
import pt.iptvplayer.tv.model.Playlist
import pt.iptvplayer.tv.model.StreamType

class StalkerClient(private val source: SourceConfig) {
    private val portal = normalizePortal(source.serverUrl)
    private val mac = normalizeMac(source.macAddress)
    private val macCompact = mac.lowercase().replace(":", "")
    private var token = ""

    fun loadCatalog(): Playlist {
        authenticate()
        val channels = loadLive()
        require(channels.isNotEmpty()) { "O portal Stalker não devolveu conteúdos para este MAC." }
        return Playlist("Stalker - $mac", channels)
    }

    fun loadEpisodes(categoryId: String, showId: String): List<Channel> {
        authenticate()
        val seasons = paginated(
            type = "series",
            action = "get_ordered_list",
            extra = mapOf("category" to categoryId, "movie_id" to showId),
        )
        val result = mutableListOf<Channel>()
        seasons.forEachIndexed { index, season ->
            val cmd = season.text("cmd")
            if (cmd.isBlank()) return@forEachIndexed
            val seasonNumber = season.text("season").toIntOrNull() ?: index + 1
            val episodeValues = when (val raw = season.opt("series")) {
                is JSONArray -> (0 until raw.length()).map { raw.optString(it) }
                else -> raw?.toString().orEmpty().split(',', ';', ' ').filter(String::isNotBlank)
            }
            episodeValues.ifEmpty { listOf("1") }.forEach { episode ->
                result += Channel(
                    name = "S${seasonNumber.toString().padStart(2, '0')} E${episode.padStart(2, '0')}",
                    url = "stalker-series://${JsonHttpClient.encode(cmd)}?episode=${JsonHttpClient.encode(episode)}",
                    group = "Temporada $seasonNumber",
                    logo = season.text("screenshot_uri"),
                    type = StreamType.SERIES,
                    userAgent = USER_AGENT,
                    referer = "$portal/c/",
                )
            }
        }
        return result
    }

    fun resolve(url: String): String {
        authenticate()
        val (type, encoded) = when {
            url.startsWith("stalker-live://") -> "itv" to url.removePrefix("stalker-live://")
            url.startsWith("stalker-vod://") -> "vod" to url.removePrefix("stalker-vod://")
            url.startsWith("stalker-series://") -> "vod" to url.removePrefix("stalker-series://")
            else -> return url
        }
        val commandPart = encoded.substringBefore('?')
        val episode = encoded.substringAfter("episode=", "").let(::decode)
        val command = decode(commandPart)
        val directUrl = extractUrl(command)
        // Many portals return a working stream directly in cmd while create_link
        // produces a URL rejected by their CDN. Prefer the known direct stream;
        // the player reconnect watchdog handles providers that close it early.
        if (directUrl.isNotBlank() && !isLocalPlaceholder(directUrl)) return directUrl
        val resolved = runCatching {
            val response = post(type, "create_link", buildMap {
                put("cmd", command)
                put("series", episode)
                if (type == "itv") {
                    put("forced_storage", "undefined")
                    put("disable_ad", "0")
                    put("download", "0")
                }
            })
            val js = response.optJSONObject("js") ?: response
            extractUrl(js.text("cmd"))
        }.getOrDefault("")
        if (resolved.isNotBlank() && !isLocalPlaceholder(resolved)) return resolved
        error("O portal Stalker não devolveu um link de reprodução válido.")
    }

    fun playbackHeaders(): Map<String, String> = buildMap {
        put("User-Agent", USER_AGENT)
        put("Referer", "$portal/c/")
        put("Cookie", "mac=$mac; stb_lang=pt; timezone=Europe/Lisbon")
        put("X-User-Agent", "Model: MAG425; Link: WiFi")
        if (token.isNotBlank()) put("Authorization", "Bearer $token")
    }

    private fun authenticate() {
        if (token.isNotBlank()) return
        runCatching { client().get("$portal/c/") }
        val handshake = post(
            "stb",
            "handshake",
            mapOf(
                "device_id" to macCompact,
                "device_id2" to macCompact,
                "device_type" to "MAG425",
                "login" to "",
                "sn" to macCompact,
                "hw_version" to "1.7",
                "image_version" to "2.31.0",
                "stb_type" to "MAG425",
            ),
        )
        token = handshake.text("token")
            .ifBlank { handshake.optJSONObject("js")?.text("token").orEmpty() }
        require(token.isNotBlank()) { "Autenticação Stalker recusada. Confirma o portal e o endereço MAC." }
        post("stb", "get_profile")
    }

    private fun loadLive(): List<Channel> {
        val genres = genres("itv")
        val actions = listOf("get_all_channels", "itv", "get_itv_list")
        val items = actions.asSequence().map { paginated("itv", it) }.firstOrNull { it.isNotEmpty() }.orEmpty()
        return items.mapNotNull { item ->
            val cmd = item.text("cmd").ifBlank { item.text("id") }
            if (cmd.isBlank()) return@mapNotNull null
            val category = item.text("tv_genre_id").ifBlank { item.text("tv_genre") }
            Channel(
                name = item.text("name").ifBlank { "Canal" },
                url = "stalker-live://${JsonHttpClient.encode(cmd)}",
                group = genres[category].orEmpty().ifBlank { "Geral" },
                logo = item.text("logo").ifBlank { item.text("tv_logo") },
                tvgId = item.text("id"),
                userAgent = USER_AGENT,
                referer = "$portal/c/",
                type = StreamType.LIVE,
            )
        }
    }

    fun loadVod(): List<Channel> {
        authenticate()
        val categories = categoryObjects("vod")
        return categories.flatMap { (id, title) ->
            paginated("vod", "get_ordered_list", mapOf("category" to id)).mapNotNull { item ->
                val cmd = item.text("cmd")
                if (cmd.isBlank()) return@mapNotNull null
                Channel(
                    name = item.text("name").ifBlank { "Filme" },
                    url = "stalker-vod://${JsonHttpClient.encode(cmd)}",
                    group = title.ifBlank { "Filmes" },
                    logo = item.text("screenshot_uri"),
                    userAgent = USER_AGENT,
                    referer = "$portal/c/",
                    type = StreamType.VOD,
                )
            }
        }
    }

    fun loadSeries(): List<Channel> {
        authenticate()
        val categories = categoryObjects("series")
        return categories.flatMap { (categoryId, title) ->
            paginated("series", "get_ordered_list", mapOf("category" to categoryId)).mapNotNull { item ->
                val showId = item.text("id").substringBefore(':')
                if (showId.isBlank()) return@mapNotNull null
                Channel(
                    name = item.text("name").ifBlank { "Série" },
                    url = "catalog://stalker/series/${JsonHttpClient.encode(categoryId)}/${JsonHttpClient.encode(showId)}",
                    group = title.ifBlank { "Séries" },
                    logo = item.text("screenshot_uri"),
                    type = StreamType.SERIES,
                )
            }
        }
    }

    private fun genres(type: String): Map<String, String> {
        val response = post(type, "get_genres")
        val array = response.arrayFromJs() ?: return emptyMap()
        return array.objects().filter { it.text("id") != "*" }.associate {
            it.text("id") to it.text("title").ifBlank { it.text("name") }
        }
    }

    private fun categoryObjects(type: String): List<Pair<String, String>> {
        val response = post(type, "get_categories")
        val array = response.arrayFromJs() ?: return emptyList()
        return array.objects().mapNotNull {
            val id = it.text("id")
            if (id.isBlank() || id == "*") null else id to it.text("title").ifBlank { it.text("name") }
        }.toList()
    }

    private fun paginated(type: String, action: String, extra: Map<String, String> = emptyMap()): List<JSONObject> {
        val result = mutableListOf<JSONObject>()
        val seen = mutableSetOf<String>()
        for (page in 1..50) {
            val response = post(type, action, extra + ("p" to page.toString()))
            val js = response.optJSONObject("js") ?: response
            val array = listOf("data", "channels", "tv_channels", "list", "items", "itv", "tv")
                .firstNotNullOfOrNull { js.optJSONArray(it) }
                ?: response.arrayFromJs()
                ?: break
            var added = false
            array.objects().forEach { item ->
                val id = item.text("id").ifBlank { item.toString().hashCode().toString() }
                if (seen.add(id)) {
                    result += item
                    added = true
                }
            }
            if (!added || array.length() == 0) break
            val total = js.optInt("total_items", 0)
            if (total > 0 && result.size >= total) break
        }
        return result
    }

    private fun post(type: String, action: String, extra: Map<String, String> = emptyMap()): JSONObject {
        val fields = linkedMapOf(
            "type" to type,
            "action" to action,
            "token" to token,
            "mac" to mac,
            "JsHttpRequest" to "1-xml:${nonce()}",
        )
        fields.putAll(extra)
        val text = client().post("$portal/server/load.php", fields).trim()
        val start = text.indexOf('{')
        val end = text.lastIndexOf('}')
        require(start >= 0 && end >= start) { "O portal Stalker devolveu uma resposta inválida." }
        return runCatching { JSONObject(text.substring(start, end + 1)) }.getOrElse {
            error("O portal Stalker devolveu uma resposta inválida.")
        }
    }

    private fun client(): JsonHttpClient = JsonHttpClient(
        USER_AGENT,
        buildMap {
            put("Cookie", "mac=$mac; stb_lang=pt; timezone=Europe/Lisbon")
            put("X-User-Agent", "Model: MAG425; Link: WiFi")
            put("Referer", "$portal/c/")
            if (token.isNotBlank()) put("Authorization", "Bearer $token")
        },
    )

    companion object {
        private const val USER_AGENT = "Mozilla/5.0 (QtEmbedded; U; Linux; C) AppleWebKit/533.3 (KHTML, like Gecko) MAG425 STBw3 firmware ver=2.31.0"

        fun normalizePortal(value: String): String {
            var result = value.trim().trimEnd('/')
            if (!result.startsWith("http://") && !result.startsWith("https://")) result = "http://$result"
            listOf("/stalker_portal/c", "/server/load.php", "/portal.php", "/index.html", "/c").firstOrNull {
                result.lowercase().endsWith(it)
            }?.let { result = result.dropLast(it.length).trimEnd('/') }
            return result
        }

        fun normalizeMac(value: String): String {
            val compact = value.filter(Char::isLetterOrDigit).uppercase()
            require(compact.length == 12 && compact.all { it in '0'..'9' || it in 'A'..'F' }) {
                "Endereço MAC inválido. Usa o formato 00:1A:79:00:00:00."
            }
            return compact.chunked(2).joinToString(":")
        }

        private fun nonce(): String = MessageDigest.getInstance("MD5")
            .digest(System.nanoTime().toString().toByteArray())
            .take(4).joinToString("") { "%02x".format(it) }

        private fun decode(value: String): String = URLDecoder.decode(value, StandardCharsets.UTF_8.name())
        private fun extractUrl(command: String): String = Regex("(?:https?|rtp|udp|rtsp)://\\S+").find(command)?.value.orEmpty()
        private fun isLocalPlaceholder(url: String): Boolean = runCatching {
            java.net.URI(url).host?.lowercase() in setOf("localhost", "127.0.0.1", "0.0.0.0")
        }.getOrDefault(false)
    }
}

private fun JSONObject.arrayFromJs(): JSONArray? = when (val js = opt("js")) {
    is JSONArray -> js
    is JSONObject -> js.optJSONArray("data")
    else -> optJSONArray("data")
}

private fun JSONArray.objects(): Sequence<JSONObject> = sequence {
    for (index in 0 until length()) optJSONObject(index)?.let { yield(it) }
}

private fun JSONObject.text(key: String): String = if (isNull(key)) "" else optString(key, "").trim()
