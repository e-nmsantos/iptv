package pt.iptvplayer.tv.data

import android.content.Context
import android.util.Log
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL
import java.net.URLEncoder

data class TmdbMovieInfo(
    val title: String,
    val year: Int?,
    val overview: String,
    val rating: Float,
    val posterUrl: String,
    val backdropUrl: String,
)

class TmdbEnricher(
    private val context: Context,
    private val apiKey: String = "b728b6d396a84976c66cf17f6984e1b7",
) {
    private val memoryCache = mutableMapOf<String, TmdbMovieInfo>()

    suspend fun fetchMovieInfo(rawTitle: String): TmdbMovieInfo? = withContext(Dispatchers.IO) {
        val cleanTitle = cleanTitle(rawTitle)
        if (cleanTitle.isBlank()) return@withContext null
        val cacheKey = cleanTitle.lowercase()

        memoryCache[cacheKey]?.let { return@withContext it }

        runCatching {
            val encodedQuery = URLEncoder.encode(cleanTitle, "UTF-8")
            val urlString = "https://api.themoviedb.org/3/search/movie?api_key=$apiKey&query=$encodedQuery&language=pt-PT&include_adult=false"
            val connection = (URL(urlString).openConnection() as HttpURLConnection).apply {
                connectTimeout = 4000
                readTimeout = 4000
                setRequestProperty("Accept", "application/json")
            }

            if (connection.responseCode == 200) {
                val jsonText = connection.inputStream.bufferedReader().use { it.readText() }
                val root = JSONObject(jsonText)
                val results = root.optJSONArray("results")
                if (results != null && results.length() > 0) {
                    val first = results.getJSONObject(0)
                    val posterPath = first.optString("poster_path", "")
                    val backdropPath = first.optString("backdrop_path", "")
                    val releaseDate = first.optString("release_date", "")
                    val year = if (releaseDate.length >= 4) releaseDate.substring(0, 4).toIntOrNull() else null
                    val info = TmdbMovieInfo(
                        title = first.optString("title", cleanTitle),
                        year = year,
                        overview = first.optString("overview", ""),
                        rating = first.optDouble("vote_average", 0.0).toFloat(),
                        posterUrl = if (posterPath.isNotBlank()) "https://image.tmdb.org/t/p/w500$posterPath" else "",
                        backdropUrl = if (backdropPath.isNotBlank()) "https://image.tmdb.org/t/p/w1280$backdropPath" else "",
                    )
                    memoryCache[cacheKey] = info
                    return@withContext info
                }
            }
            null
        }.getOrNull()
    }

    private fun cleanTitle(title: String): String {
        return title
            .replace(Regex("\\[.*?\\]"), "")
            .replace(Regex("\\(\\d{4}\\)"), "")
            .replace(Regex("(?i)\\b(1080p|720p|4k|fhd|hd|uhd|hevc|h265|bluray|web-dl)\\b"), "")
            .replace(Regex("\\s+"), " ")
            .trim()
    }
}

