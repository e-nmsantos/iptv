package pt.iptvplayer.tv.data

import android.net.Uri
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL
import java.net.URLEncoder

data class OnlineSubtitle(
    val id: String,
    val language: String,
    val releaseName: String,
    val url: String,
)

object OnlineSubtitlesClient {

    suspend fun search(query: String): List<OnlineSubtitle> = withContext(Dispatchers.IO) {
        val results = mutableListOf<OnlineSubtitle>()
        try {
            val cleanQuery = query
                .replace(Regex("(?i)\\[.*?\\]|\\(.*?\\)"), "")
                .replace(Regex("(?i)\\b(1080p|720p|4k|uhd|fhd|hd|hevc|x265|x264|bluray|web-dl)\\b"), "")
                .trim()

            val encoded = URLEncoder.encode(cleanQuery, "UTF-8")
            val metaUrl = "https://v3-cinemeta.strem.io/catalog/movie/top/search=$encoded.json"
            val metaJson = httpGet(metaUrl) ?: return@withContext emptyList()
            
            val metas = JSONObject(metaJson).optJSONArray("metas") ?: return@withContext emptyList()
            val candidateIds = mutableListOf<String>()
            for (i in 0 until minOf(3, metas.length())) {
                val id = metas.getJSONObject(i).optString("id")
                if (id.isNotBlank()) candidateIds.add(id)
            }

            for (imdbId in candidateIds) {
                val subUrl = "https://opensubtitles-v3.strem.io/subtitles/movie/$imdbId.json"
                val subJson = httpGet(subUrl) ?: continue
                val subs = JSONObject(subJson).optJSONArray("subtitles") ?: continue
                for (j in 0 until subs.length()) {
                    val item = subs.getJSONObject(j)
                    val lang = item.optString("lang", "").lowercase()
                    if (lang in setOf("por", "pob", "eng", "spa")) {
                        val dlUrl = item.optString("url", "")
                        if (dlUrl.isNotBlank()) {
                            val tag = if (lang == "por") "PT" else if (lang == "pob") "BR" else lang.uppercase()
                            val rel = item.optString("movieReleaseName").ifBlank { cleanQuery }
                            results.add(
                                OnlineSubtitle(
                                    id = item.optString("id", "$j"),
                                    language = tag,
                                    releaseName = rel,
                                    url = dlUrl,
                                )
                            )
                        }
                    }
                }
            }
        } catch (e: Exception) {
            // Silently handle offline/error
        }
        results
    }

    private fun httpGet(urlString: String): String? {
        return try {
            val url = URL(urlString)
            val conn = url.openConnection() as HttpURLConnection
            conn.requestMethod = "GET"
            conn.connectTimeout = 4000
            conn.readTimeout = 4000
            conn.setRequestProperty("User-Agent", "VLSub 0.10.2")
            if (conn.responseCode == 200) {
                conn.inputStream.bufferedReader().use { it.readText() }
            } else null
        } catch (e: Exception) {
            null
        }
    }
}

