package pt.iptvplayer.tv.data

import android.content.ContentResolver
import android.net.Uri
import java.io.FilterInputStream
import java.io.InputStream
import java.io.InputStreamReader
import java.net.HttpURLConnection
import java.net.URI
import java.util.zip.GZIPInputStream
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.ensureActive
import kotlinx.coroutines.withContext
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.catch
import kotlinx.coroutines.flow.flowOf
import kotlinx.coroutines.flow.first
import pt.iptvplayer.tv.model.Playlist
import pt.iptvplayer.tv.model.Channel
import pt.iptvplayer.tv.model.EpgProgram
import pt.iptvplayer.tv.model.EpgReminder
import pt.iptvplayer.tv.model.WatchHistoryItem
import pt.iptvplayer.tv.model.StreamType
import pt.iptvplayer.tv.model.PlaylistSummary
import pt.iptvplayer.tv.parser.M3uParser
import pt.iptvplayer.tv.data.room.RoomCatalogDatabase
import pt.iptvplayer.tv.data.room.RoomCatalogFlowStore

class CatalogRepository(
    private val database: CatalogDatabase,
    roomDatabase: RoomCatalogDatabase? = null,
) {
    private val parser = M3uParser()
    private val room = roomDatabase
    private val flowStore = roomDatabase?.let { RoomCatalogFlowStore(it.catalogDao()) }
    @Volatile
    private var currentSource = SourceConfig(SourceType.M3U, "")
    @Volatile
    private var currentPlaylistId: Long? = null

    suspend fun load(): Playlist = withContext(Dispatchers.IO) {
        val (id, playlist) = database.loadActive()
        currentPlaylistId = id
        if (id != null) currentSource = database.loadSource(id)
        playlist
    }

    suspend fun playlists(): List<PlaylistSummary> = withContext(Dispatchers.IO) { database.summaries() }

    suspend fun catalogPage(
        type: StreamType,
        group: String = "Todos",
        query: String = "",
        offset: Int = 0,
    ): CatalogPage = withContext(Dispatchers.IO) {
        val playlistId = currentPlaylistId ?: return@withContext CatalogPage(emptyList(), listOf("Todos"), 0, 0)
        database.catalogPage(playlistId, type, group, query, offset, PAGE_SIZE)
    }

    // Room validates the on-disk schema like a pre-packaged database whenever it opens a file
    // it didn't create itself (e.g. one an older app version built with the legacy SQLiteOpenHelper
    // migration chain). If that validation ever rejects the schema, fall back to the legacy,
    // always-available query path instead of breaking playlist loading for the user.
    fun observeCatalogPage(
        type: StreamType,
        group: String = "Todos",
        query: String = "",
        limit: Int = PAGE_SIZE,
    ): Flow<CatalogPage> {
        val playlistId = currentPlaylistId ?: return flowOf(CatalogPage(emptyList(), listOf("Todos"), 0, 0))
        fun legacyPage() = database.catalogPage(playlistId, type, group, query, 0, limit)
        return flowStore?.observePage(playlistId, type, group, query, 0, limit)
            ?.catch { emit(legacyPage()) }
            ?: flowOf(legacyPage())
    }

    /** Every LIVE channel, independent of whatever filter the main catalog browser last used. */
    fun observeLiveGuideChannels(): Flow<CatalogPage> =
        observeCatalogPage(StreamType.LIVE, "Todos", "", limit = Int.MAX_VALUE)

    /** Every EPG programme in [fromMillis, toMillis), keyed by tvg-id, for the EPG timeline grid. */
    fun observeEpgWindow(fromMillis: Long, toMillis: Long): Flow<Map<String, List<EpgProgram>>> {
        val playlistId = currentPlaylistId ?: return flowOf(emptyMap())
        fun legacyWindow() = database.epgWindow(fromMillis, toMillis)
        return flowStore?.observeEpg(playlistId, fromMillis, toMillis)
            ?.catch { emit(legacyWindow()) }
            ?: flowOf(legacyWindow())
    }

    fun refreshRoom() {
        runCatching { room?.invalidationTracker?.refreshAsync() }
    }

    suspend fun favorites(): List<Channel> {
        val playlistId = currentPlaylistId ?: return emptyList()
        return flowStore?.let { store -> runCatching { store.observeFavorites(playlistId).first() }.getOrNull() }
            ?: emptyList()
    }

    suspend fun refreshEpg(playlist: Playlist): Map<String, List<EpgProgram>> = withContext(Dispatchers.IO) {
        val programmes = EpgClient().loadSchedule(
            playlist.epgUrl,
            playlist.channels.asSequence().map(Channel::tvgId).filter(String::isNotBlank).toSet(),
        )
        database.replaceEpg(programmes)
        refreshRoom()
        database.currentAndNextEpg()
    }

    suspend fun cachedEpg(): Map<String, List<EpgProgram>> = withContext(Dispatchers.IO) {
        database.currentAndNextEpg()
    }

    suspend fun importDeviceSync(data: String): Playlist = withContext(Dispatchers.IO) {
        val playlistId = currentPlaylistId ?: error("Seleciona primeiro uma playlist na TV.")
        database.applyDeviceSync(playlistId, data)
        database.load(playlistId)
    }

    suspend fun exportDeviceSync(): String = withContext(Dispatchers.IO) {
        val playlistId = currentPlaylistId ?: error("Seleciona primeiro uma playlist na TV.")
        database.exportDeviceSync(playlistId)
    }

    suspend fun selectPlaylist(id: Long): Playlist = withContext(Dispatchers.IO) {
        database.activate(id).also {
            currentPlaylistId = id
            currentSource = database.loadSource(id)
        }
    }

    suspend fun deletePlaylist(id: Long): Playlist = withContext(Dispatchers.IO) {
        database.delete(id)
        val (activeId, playlist) = database.loadActive()
        currentPlaylistId = activeId
        currentSource = if (activeId == null) SourceConfig(SourceType.M3U, "") else database.loadSource(activeId)
        playlist
    }

    suspend fun refresh(): Playlist = when (currentSource.type) {
        SourceType.M3U -> {
            require(currentSource.serverUrl.startsWith("http://") || currentSource.serverUrl.startsWith("https://")) {
                "Esta lista veio de um ficheiro local. Volta a escolher o ficheiro para a atualizar."
            }
            importUrl(currentSource.serverUrl)
        }
        SourceType.XTREAM -> importXtream(currentSource.serverUrl, currentSource.username, currentSource.password)
        SourceType.STALKER -> importStalker(currentSource.serverUrl, currentSource.macAddress)
    }

    suspend fun importUrl(url: String, customName: String? = null): Playlist = withContext(Dispatchers.IO) {
        var currentUrl = url.trim()
        var redirects = 0
        var connection: HttpURLConnection? = null
        try {
            while (redirects < 5) {
                val uri = runCatching { URI(currentUrl) }.getOrNull()
                require(uri?.scheme in setOf("http", "https") && !uri?.host.isNullOrBlank()) {
                    "Introduz um endereço HTTP ou HTTPS válido."
                }
                val conn = uri!!.toURL().openConnection() as HttpURLConnection
                conn.connectTimeout = 15_000
                conn.readTimeout = 30_000
                conn.instanceFollowRedirects = false
                conn.setRequestProperty("User-Agent", "IPTVPlayerTV/0.9")
                conn.setRequestProperty("Accept-Encoding", "gzip")
                conn.connect()

                val code = conn.responseCode
                if (code in setOf(HttpURLConnection.HTTP_MOVED_PERM, HttpURLConnection.HTTP_MOVED_TEMP, HttpURLConnection.HTTP_SEE_OTHER, 307, 308)) {
                    val location = conn.getHeaderField("Location")
                    conn.disconnect()
                    if (!location.isNullOrBlank()) {
                        currentUrl = uri.resolve(location).toString()
                        redirects++
                        continue
                    }
                }
                connection = conn
                break
            }
            val finalConn = connection ?: error("Não foi possível estabelecer ligação.")
            require(finalConn.responseCode in 200..299) { "O servidor respondeu com HTTP ${finalConn.responseCode}." }
            val declared = finalConn.getHeaderField("Content-Length")?.toLongOrNull() ?: -1L
            require(declared < 0 || declared <= MAX_BYTES) { "A lista excede o limite de 100 MB." }
            val rawStream = LimitedInputStream(finalConn.inputStream, MAX_BYTES)
            val sourceStream = if (finalConn.contentEncoding.equals("gzip", true)) {
                GZIPInputStream(rawStream)
            } else {
                rawStream
            }
            val defaultName = runCatching { URI(currentUrl).path.substringAfterLast('/').substringBeforeLast('.') }.getOrNull()
            val resolvedName = when {
                !customName.isNullOrBlank() -> customName.trim()
                !defaultName.isNullOrBlank() && defaultName != "get" -> defaultName
                else -> "Lista IPTV"
            }
            val source = SourceConfig(SourceType.M3U, url.trim())
            LimitedInputStream(sourceStream, MAX_DECOMPRESSED_BYTES).use { input ->
                importM3uStream(input, resolvedName, source)
            }
        } finally {
            connection?.disconnect()
        }
    }

    suspend fun importDocument(resolver: ContentResolver, uri: Uri): Playlist = withContext(Dispatchers.IO) {
        val name = uri.lastPathSegment?.substringAfterLast('/')?.substringBeforeLast('.')
            ?.ifBlank { "Lista IPTV" } ?: "Lista IPTV"
        val source = SourceConfig(SourceType.M3U, uri.toString())
        resolver.openInputStream(uri)?.use { raw ->
            importM3uStream(LimitedInputStream(raw, MAX_BYTES), name, source)
        } ?: error("Não foi possível abrir o ficheiro.")
    }

    suspend fun importXtream(server: String, username: String, password: String, customName: String? = null): Playlist =
        withContext(Dispatchers.IO) {
            val source = SourceConfig(SourceType.XTREAM, XtreamClient.normalizeBaseUrl(server), username.trim(), password)
            val loaded = XtreamClient(source).loadCatalog()
            val playlist = if (!customName.isNullOrBlank()) loaded.copy(name = customName.trim()) else loaded
            playlist.also {
                currentPlaylistId = database.save(it, source)
                currentSource = source
            }
        }

    suspend fun importStalker(portal: String, macAddress: String, customName: String? = null): Playlist =
        withContext(Dispatchers.IO) {
            val source = SourceConfig(
                SourceType.STALKER,
                StalkerClient.normalizePortal(portal),
                macAddress = StalkerClient.normalizeMac(macAddress),
            )
            val loaded = StalkerClient(source).loadCatalog()
            val playlist = if (!customName.isNullOrBlank()) loaded.copy(name = customName.trim()) else loaded
            playlist.also {
                currentPlaylistId = database.save(it, source)
                currentSource = source
            }
        }

    suspend fun loadSeriesEpisodes(channel: Channel): List<Channel> = withContext(Dispatchers.IO) {
        when {
            channel.url.startsWith("catalog://xtream/series/") -> {
                val id = channel.url.removePrefix("catalog://xtream/series/").substringBefore('?')
                XtreamClient(currentSource).loadEpisodes(id)
            }
            channel.url.startsWith("catalog://stalker/series/") -> {
                val parts = channel.url.removePrefix("catalog://stalker/series/").split('/')
                require(parts.size >= 2) { "Identificador de série Stalker inválido." }
                StalkerClient(currentSource).loadEpisodes(
                    java.net.URLDecoder.decode(parts[0], Charsets.UTF_8.name()),
                    java.net.URLDecoder.decode(parts[1], Charsets.UTF_8.name()),
                )
            }
            else -> emptyList()
        }
    }

    suspend fun preparePlayback(channel: Channel): Channel = withContext(Dispatchers.IO) {
        val resolvedChannel = database.resolveChannel(channel)
        val prepared = if (resolvedChannel.url.startsWith(ContinueSyncCodec.XTREAM_EPISODE_SCHEME)) {
            // Episode received from the desktop: rebuilt with this playlist's own credentials.
            val (episodeId, extension) = ContinueSyncCodec.parseXtreamEpisodeUrl(resolvedChannel.url)
            resolvedChannel.copy(url = XtreamClient(currentSource).episodeUrl(episodeId, extension))
        } else if (resolvedChannel.url.startsWith("stalker-")) {
            val client = StalkerClient(currentSource)
            resolvedChannel.copy(
                url = client.resolve(resolvedChannel.url),
                customHeaders = client.playbackHeaders(),
            )
        } else {
            resolvedChannel
        }
        val playlistId = currentPlaylistId
        if (playlistId != null && prepared.type != StreamType.LIVE) {
            prepared.copy(resumePositionMs = database.playbackPosition(playlistId, mediaKey(prepared)))
        } else {
            prepared
        }
    }

    suspend fun setFavorite(channel: Channel, favorite: Boolean): Channel = withContext(Dispatchers.IO) {
        database.setFavorite(channel.id, favorite)
        channel.copy(favorite = favorite)
    }

    suspend fun savePlaybackPosition(channel: Channel, positionMs: Long, durationMs: Long) =
        withContext(Dispatchers.IO) {
            val playlistId = currentPlaylistId ?: return@withContext
            if (channel.type != StreamType.LIVE) {
                database.savePlaybackPosition(playlistId, mediaKey(channel), positionMs, durationMs)
            }
        }

    /**
     * Remembers [channel] (the replayable reference, before link resolution) as just watched.
     * [parent] is the series an episode belongs to; [upNext] queues an episode that hasn't been
     * started yet so it shows up in "Continuar a ver".
     */
    suspend fun recordPlayback(channel: Channel, parent: Channel? = null, upNext: Boolean = false) =
        withContext(Dispatchers.IO) {
            val playlistId = currentPlaylistId ?: return@withContext
            if (channel.url.startsWith("catalog://")) return@withContext
            database.recordHistory(
                playlistId = playlistId,
                mediaKey = mediaKey(channel),
                channel = channel,
                parent = parent,
                subtitle = parent?.name ?: channel.group,
                artwork = channel.logo.ifBlank { parent?.logo.orEmpty() },
                upNext = upNext,
            )
        }

    suspend fun continueWatching(): List<WatchHistoryItem> = withContext(Dispatchers.IO) {
        val playlistId = currentPlaylistId ?: return@withContext emptyList()
        database.continueWatching(playlistId)
    }

    suspend fun removeFromContinueWatching(item: WatchHistoryItem) = withContext(Dispatchers.IO) {
        val playlistId = currentPlaylistId ?: return@withContext
        database.removeHistory(playlistId, item.mediaKey)
    }

    suspend fun recentLive(): List<Channel> = withContext(Dispatchers.IO) {
        val playlistId = currentPlaylistId ?: return@withContext emptyList()
        database.recentLive(playlistId)
    }

    suspend fun recentlyAdded(type: StreamType, limit: Int = 20): List<Channel> = withContext(Dispatchers.IO) {
        val playlistId = currentPlaylistId ?: return@withContext emptyList()
        database.recentlyAdded(playlistId, type, limit)
    }

    suspend fun reminders(): List<EpgReminder> = withContext(Dispatchers.IO) {
        val playlistId = currentPlaylistId ?: return@withContext emptyList()
        database.reminders(playlistId)
    }

    suspend fun addReminder(reminder: EpgReminder) = withContext(Dispatchers.IO) {
        val playlistId = currentPlaylistId ?: error("Seleciona primeiro uma playlist.")
        database.saveReminder(playlistId, reminder)
    }

    suspend fun removeReminder(reminder: EpgReminder) = withContext(Dispatchers.IO) {
        val playlistId = currentPlaylistId ?: return@withContext
        database.deleteReminder(playlistId, reminder.tvgId, reminder.startMillis)
    }

    suspend fun loadAdditionalCatalog(
        type: StreamType,
        @Suppress("UNUSED_PARAMETER") playlistName: String,
        @Suppress("UNUSED_PARAMETER") existing: List<Channel>,
    ): List<Channel> = withContext(Dispatchers.IO) {
        if (currentSource.type != SourceType.STALKER) return@withContext emptyList()
        val client = StalkerClient(currentSource)
        val additions = when (type) {
            StreamType.VOD -> client.loadVod()
            StreamType.SERIES -> client.loadSeries()
            StreamType.LIVE -> emptyList()
        }
        if (additions.isNotEmpty()) {
            val playlistId = currentPlaylistId ?: error("Seleciona primeiro uma playlist.")
            database.replaceCatalogType(playlistId, type, additions)
            refreshRoom()
        }
        additions
    }

    private suspend fun importM3uStream(
        input: InputStream,
        name: String,
        source: SourceConfig,
    ): Playlist {
        val context = currentCoroutineContext()
        val playlistId = database.saveIncremental(name, source) { consume ->
            val batch = ArrayList<Channel>(IMPORT_BATCH_SIZE)
            val result = parser.parse(InputStreamReader(input, Charsets.UTF_8)) { channel ->
                batch += channel
                if (batch.size >= IMPORT_BATCH_SIZE) {
                    context.ensureActive()
                    consume(batch.toList())
                    batch.clear()
                }
            }
            if (batch.isNotEmpty()) {
                context.ensureActive()
                consume(batch)
            }
            result.epgUrl
        }
        currentPlaylistId = playlistId
        currentSource = source
        refreshRoom()
        return database.load(playlistId)
    }

    private fun mediaKey(channel: Channel): String = playbackMediaKey(channel)

    companion object {
        const val MAX_BYTES = 100L * 1024 * 1024
        const val MAX_DECOMPRESSED_BYTES = 256L * 1024 * 1024
        const val PAGE_SIZE = 240
        const val IMPORT_BATCH_SIZE = 500
    }
}

private class LimitedInputStream(
    input: InputStream,
    private val limit: Long,
) : FilterInputStream(input) {
    private var total = 0L

    override fun read(): Int = super.read().also { value ->
        if (value >= 0) addBytes(1)
    }

    override fun read(buffer: ByteArray, offset: Int, length: Int): Int =
        super.read(buffer, offset, length).also { count ->
            if (count > 0) addBytes(count.toLong())
        }

    private fun addBytes(count: Long) {
        total += count
        require(total <= limit) { "A lista excede o limite de tamanho permitido." }
    }
}
