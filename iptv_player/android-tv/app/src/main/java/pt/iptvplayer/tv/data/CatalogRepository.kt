package pt.iptvplayer.tv.data

import android.content.ContentResolver
import android.net.Uri
import java.io.FilterInputStream
import java.io.InputStream
import java.io.InputStreamReader
import java.net.HttpURLConnection
import java.net.URI
import java.security.MessageDigest
import java.util.zip.GZIPInputStream
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.ensureActive
import kotlinx.coroutines.withContext
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.flowOf
import kotlinx.coroutines.flow.first
import pt.iptvplayer.tv.model.Playlist
import pt.iptvplayer.tv.model.Channel
import pt.iptvplayer.tv.model.EpgProgram
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

    fun observeCatalogPage(
        type: StreamType,
        group: String = "Todos",
        query: String = "",
        limit: Int = PAGE_SIZE,
    ): Flow<CatalogPage> {
        val playlistId = currentPlaylistId ?: return flowOf(CatalogPage(emptyList(), listOf("Todos"), 0, 0))
        return flowStore?.observePage(playlistId, type, group, query, 0, limit)
            ?: flowOf(database.catalogPage(playlistId, type, group, query, 0, limit))
    }

    fun refreshRoom() = room?.invalidationTracker?.refreshAsync()

    suspend fun favorites(): List<Channel> {
        val playlistId = currentPlaylistId ?: return emptyList()
        return flowStore?.observeFavorites(playlistId)?.first() ?: emptyList()
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

    suspend fun importUrl(url: String): Playlist = withContext(Dispatchers.IO) {
        val uri = runCatching { URI(url.trim()) }.getOrNull()
        require(uri?.scheme in setOf("http", "https") && !uri?.host.isNullOrBlank()) {
            "Introduz um endereço HTTP ou HTTPS válido."
        }
        val connection = uri!!.toURL().openConnection() as HttpURLConnection
        try {
            connection.connectTimeout = 15_000
            connection.readTimeout = 30_000
            connection.instanceFollowRedirects = true
            connection.setRequestProperty("User-Agent", "IPTVPlayerTV/0.9")
            connection.setRequestProperty("Accept-Encoding", "gzip")
            connection.connect()
            require(connection.responseCode in 200..299) { "O servidor respondeu com HTTP ${connection.responseCode}." }
            val declared = connection.getHeaderField("Content-Length")?.toLongOrNull() ?: -1L
            require(declared < 0 || declared <= MAX_BYTES) { "A lista excede o limite de 100 MB." }
            val rawStream = LimitedInputStream(connection.inputStream, MAX_BYTES)
            val sourceStream = if (connection.contentEncoding.equals("gzip", true)) {
                GZIPInputStream(rawStream)
            } else {
                rawStream
            }
            val name = uri.path.substringAfterLast('/').substringBeforeLast('.').ifBlank { "Lista IPTV" }
            val source = SourceConfig(SourceType.M3U, url.trim())
            LimitedInputStream(sourceStream, MAX_DECOMPRESSED_BYTES).use { input ->
                importM3uStream(input, name, source)
            }
        } finally {
            connection.disconnect()
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

    suspend fun importXtream(server: String, username: String, password: String): Playlist =
        withContext(Dispatchers.IO) {
            val source = SourceConfig(SourceType.XTREAM, XtreamClient.normalizeBaseUrl(server), username.trim(), password)
            XtreamClient(source).loadCatalog().also {
                currentPlaylistId = database.save(it, source)
                currentSource = source
            }
        }

    suspend fun importStalker(portal: String, macAddress: String): Playlist =
        withContext(Dispatchers.IO) {
            val source = SourceConfig(
                SourceType.STALKER,
                StalkerClient.normalizePortal(portal),
                macAddress = StalkerClient.normalizeMac(macAddress),
            )
            StalkerClient(source).loadCatalog().also {
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
        val prepared = if (resolvedChannel.url.startsWith("stalker-")) {
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

    private fun mediaKey(channel: Channel): String {
        val stableIdentity = listOf(
            channel.tvgId.ifBlank { channel.name },
            channel.group,
            channel.type.name,
        ).joinToString("\u0000")
        val digest = MessageDigest.getInstance("SHA-256")
            .digest(stableIdentity.toByteArray(Charsets.UTF_8))
        return "media:" + digest.joinToString("") { "%02x".format(it) }
    }

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
