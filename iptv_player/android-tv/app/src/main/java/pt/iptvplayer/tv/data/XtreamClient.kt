package pt.iptvplayer.tv.data

import org.json.JSONArray
import org.json.JSONObject
import java.util.concurrent.Executors
import pt.iptvplayer.tv.model.Channel
import pt.iptvplayer.tv.model.Playlist
import pt.iptvplayer.tv.model.StreamType

class XtreamClient(private val config: SourceConfig) {
    private val baseUrl = normalizeBaseUrl(config.serverUrl)
    private val http = JsonHttpClient("IPTVPlayerTV/0.9")
    private var streamBaseUrl = baseUrl

    fun loadCatalog(): Playlist {
        authenticate()
        // Xtream endpoints are independent. Fetching them concurrently cuts several
        // network round trips from the initial import on high-latency providers.
        val executor = Executors.newFixedThreadPool(4)
        val liveCategoriesTask = executor.submit<Map<String, String>> { categories("get_live_categories") }
        val vodCategoriesTask = executor.submit<Map<String, String>> { categories("get_vod_categories") }
        val seriesCategoriesTask = executor.submit<Map<String, String>> { categories("get_series_categories") }
        val liveTask = executor.submit<JSONArray> { array("get_live_streams") }
        val vodTask = executor.submit<JSONArray> { array("get_vod_streams") }
        val seriesTask = executor.submit<JSONArray> { array("get_series") }
        val liveCategories: Map<String, String>
        val vodCategories: Map<String, String>
        val seriesCategories: Map<String, String>
        val liveItems: JSONArray
        val vodItems: JSONArray
        val seriesItems: JSONArray
        try {
            liveCategories = liveCategoriesTask.get()
            vodCategories = vodCategoriesTask.get()
            seriesCategories = seriesCategoriesTask.get()
            liveItems = liveTask.get()
            vodItems = vodTask.get()
            seriesItems = seriesTask.get()
        } finally {
            executor.shutdownNow()
        }
        val channels = mutableListOf<Channel>()

        liveItems.objects().forEach { item ->
            val id = item.text("stream_id")
            if (id.isNotBlank()) channels += Channel(
                name = item.text("name").ifBlank { "Canal" },
                url = streamUrl("live", id, item.text("container_extension").ifBlank { "ts" }),
                group = item.text("category_name").ifBlank { liveCategories[item.text("category_id")].orEmpty().ifBlank { "Geral" } },
                logo = item.text("stream_icon"),
                tvgId = item.text("epg_channel_id"),
                type = StreamType.LIVE,
            )
        }
        vodItems.objects().forEach { item ->
            val id = item.text("stream_id")
            if (id.isNotBlank()) channels += Channel(
                name = item.text("name").ifBlank { "Filme" },
                url = streamUrl("movie", id, item.text("container_extension").ifBlank { "mp4" }),
                group = item.text("category_name").ifBlank { vodCategories[item.text("category_id")].orEmpty().ifBlank { "Filmes" } },
                logo = item.text("stream_icon"),
                type = StreamType.VOD,
            )
        }
        seriesItems.objects().forEach { item ->
            val id = item.text("series_id")
            if (id.isNotBlank()) channels += Channel(
                name = item.text("name").ifBlank { "Série" },
                url = "catalog://xtream/series/$id",
                group = item.text("category_name").ifBlank { seriesCategories[item.text("category_id")].orEmpty().ifBlank { "Séries" } },
                logo = item.text("cover"),
                type = StreamType.SERIES,
            )
        }
        return Playlist("Xtream - ${config.username}", channels)
    }

    fun loadEpisodes(seriesId: String): List<Channel> {
        authenticate()
        val response = objectRequest("get_series_info", mapOf("series_id" to seriesId))
        val episodes = response.optJSONObject("episodes") ?: return emptyList()
        val result = mutableListOf<Channel>()
        episodes.keys().forEach { seasonKey ->
            val season = episodes.optJSONArray(seasonKey) ?: return@forEach
            season.objects().forEach { item ->
                val id = item.text("id")
                if (id.isBlank()) return@forEach
                val episodeNumber = item.optInt("episode_num", 0)
                val title = item.text("title").ifBlank {
                    "S${seasonKey.padStart(2, '0')} E${episodeNumber.toString().padStart(2, '0')}"
                }
                result += Channel(
                    name = title,
                    url = streamUrl("series", id, item.text("container_extension").ifBlank { "mp4" }),
                    group = "Temporada ${seasonKey.toIntOrNull() ?: seasonKey}",
                    logo = item.optJSONObject("info")?.text("movie_image").orEmpty(),
                    type = StreamType.SERIES,
                )
            }
        }
        return result
    }

    private fun authenticate() {
        val root = objectRequest("")
        val user = root.optJSONObject("user_info") ?: error("O servidor não devolveu dados de utilizador Xtream.")
        require(user.optInt("auth", 0) == 1 || user.optString("auth") == "1") {
            "Autenticação Xtream recusada. Confirma o utilizador e a palavra-passe."
        }
        root.optJSONObject("server_info")?.let { info ->
            val host = info.text("url")
            if (host.isNotBlank()) {
                val protocol = info.text("server_protocol").ifBlank { "http" }
                val port = if (protocol == "https") info.text("https_port") else info.text("port")
                streamBaseUrl = "$protocol://$host" + if (port.isNotBlank()) ":$port" else ""
            }
        }
    }

    private fun categories(action: String): Map<String, String> = array(action).objects().associate {
        it.text("category_id") to it.text("category_name")
    }

    private fun array(action: String): JSONArray {
        val text = request(action)
        return runCatching { JSONArray(text) }.getOrElse {
            val root = runCatching { JSONObject(text) }.getOrNull()
            root?.optJSONArray("data") ?: JSONArray()
        }
    }

    private fun objectRequest(action: String, extra: Map<String, String> = emptyMap()): JSONObject {
        val text = request(action, extra)
        return runCatching { JSONObject(text) }.getOrElse {
            error("O servidor Xtream devolveu uma resposta inválida.")
        }
    }

    private fun request(action: String, extra: Map<String, String> = emptyMap()): String {
        val params = linkedMapOf("username" to config.username, "password" to config.password)
        if (action.isNotBlank()) params["action"] = action
        params.putAll(extra)
        return http.get("$baseUrl/player_api.php", params)
    }

    private fun streamUrl(type: String, id: String, extension: String): String =
        "${streamBaseUrl.trimEnd('/')}/$type/${path(config.username)}/${path(config.password)}/${path(id)}.${extension.trimStart('.')}"

    companion object {
        fun normalizeBaseUrl(value: String): String {
            val trimmed = value.trim().trimEnd('/')
            return if (trimmed.startsWith("http://") || trimmed.startsWith("https://")) trimmed else "https://$trimmed"
        }

        private fun path(value: String): String = JsonHttpClient.encode(value).replace("+", "%20")
    }
}

private fun JSONArray.objects(): Sequence<JSONObject> = sequence {
    for (index in 0 until length()) optJSONObject(index)?.let { yield(it) }
}

private fun JSONObject.text(key: String): String = if (isNull(key)) "" else optString(key, "").trim()
