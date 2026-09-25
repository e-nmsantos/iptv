package pt.iptvplayer.tv.data

import android.content.ContentValues
import android.content.Context
import android.database.sqlite.SQLiteDatabase
import android.database.sqlite.SQLiteOpenHelper
import androidx.core.database.sqlite.transaction
import java.security.MessageDigest
import org.json.JSONObject
import pt.iptvplayer.tv.model.Channel
import pt.iptvplayer.tv.model.Playlist
import pt.iptvplayer.tv.model.PlaylistSummary
import pt.iptvplayer.tv.model.StreamType

class CatalogDatabase(context: Context) :
    SQLiteOpenHelper(context, "iptv-tv.db", null, DATABASE_VERSION), PagedCatalogStore {
    private val cipher = SecretCipher(context.applicationContext)

    init {
        setWriteAheadLoggingEnabled(true)
    }

    override fun onConfigure(db: SQLiteDatabase) {
        super.onConfigure(db)
        // PRAGMA busy_timeout returns a row on Android and therefore must use the
        // query API. execSQL rejects it with "queries can be performed using query".
        db.rawQuery("PRAGMA busy_timeout=15000", null).use { it.moveToFirst() }
        db.setForeignKeyConstraintsEnabled(true)
    }

    override fun onCreate(db: SQLiteDatabase) {
        createPlaylistsTable(db)
        createChannelsTable(db)
        createPlaybackProgressTable(db)
        createCatalogSearch(db)
        createEpgTable(db)
    }

    override fun onUpgrade(db: SQLiteDatabase, oldVersion: Int, newVersion: Int) {
        if (oldVersion < 2) migrateSinglePlaylist(db)
        if (oldVersion < 3) createPlaybackProgressTable(db)
        if (oldVersion < 4) createCatalogSearch(db)
        if (oldVersion < 5) {
            // oldVersion < 2 already rebuilds "channels" via the current createChannelsTable(),
            // which has included content_hash since that column's default value was added below.
            // Devices jumping straight from version 1 to 6 must not add it a second time here.
            if (!hasColumn(db, "channels", "content_hash")) {
                db.execSQL("ALTER TABLE channels ADD COLUMN content_hash TEXT NOT NULL DEFAULT ''")
            }
            db.execSQL("CREATE INDEX IF NOT EXISTS channels_differential ON channels(playlist_id, stream_type, tvg_id, name)")
            db.execSQL("CREATE INDEX IF NOT EXISTS playback_progress_playlist ON playback_progress(playlist_id)")
            createCatalogSearch(db)
        }
        if (oldVersion < 6) createEpgTable(db)
    }

    private fun hasColumn(db: SQLiteDatabase, table: String, column: String): Boolean =
        db.rawQuery("PRAGMA table_info($table)", null).use { cursor ->
            val nameIndex = cursor.getColumnIndexOrThrow("name")
            while (cursor.moveToNext()) {
                if (cursor.getString(nameIndex) == column) return@use true
            }
            false
        }

    private fun createPlaylistsTable(db: SQLiteDatabase) {
        db.execSQL(
            """CREATE TABLE playlists (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                encrypted_epg_url TEXT NOT NULL,
                source_type TEXT NOT NULL,
                encrypted_source_data TEXT NOT NULL,
                updated_at INTEGER NOT NULL,
                active INTEGER NOT NULL DEFAULT 0
            )""".trimIndent(),
        )
    }

    private fun createChannelsTable(db: SQLiteDatabase) {
        db.execSQL(
            """CREATE TABLE channels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                playlist_id INTEGER NOT NULL REFERENCES playlists(id) ON DELETE CASCADE,
                name TEXT NOT NULL,
                encrypted_url TEXT NOT NULL,
                group_name TEXT NOT NULL,
                logo TEXT NOT NULL,
                tvg_id TEXT NOT NULL,
                encrypted_headers TEXT NOT NULL,
                stream_type TEXT NOT NULL,
                quality TEXT NOT NULL,
                favorite INTEGER NOT NULL DEFAULT 0,
                content_hash TEXT NOT NULL DEFAULT ''
            )""".trimIndent(),
        )
        db.execSQL("CREATE INDEX channels_playlist_type_group ON channels(playlist_id, stream_type, group_name)")
        db.execSQL("CREATE INDEX channels_differential ON channels(playlist_id, stream_type, tvg_id, name)")
    }

    private fun createPlaybackProgressTable(db: SQLiteDatabase) {
        db.execSQL(
            """CREATE TABLE IF NOT EXISTS playback_progress (
                playlist_id INTEGER NOT NULL REFERENCES playlists(id) ON DELETE CASCADE,
                media_key TEXT NOT NULL,
                position_ms INTEGER NOT NULL,
                duration_ms INTEGER NOT NULL,
                updated_at INTEGER NOT NULL,
                PRIMARY KEY (playlist_id, media_key)
            )""".trimIndent(),
        )
        db.execSQL("CREATE INDEX IF NOT EXISTS playback_progress_playlist ON playback_progress(playlist_id)")
    }

    private fun createEpgTable(db: SQLiteDatabase) {
        db.execSQL(
            """CREATE TABLE IF NOT EXISTS epg_programmes (
                playlist_id INTEGER NOT NULL REFERENCES playlists(id) ON DELETE CASCADE,
                channel_id TEXT NOT NULL,
                title TEXT NOT NULL,
                start_millis INTEGER NOT NULL,
                stop_millis INTEGER NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                category TEXT NOT NULL DEFAULT '',
                catchup_url TEXT NOT NULL DEFAULT '',
                PRIMARY KEY (playlist_id, channel_id, start_millis)
            )""".trimIndent(),
        )
        db.execSQL(
            "CREATE INDEX IF NOT EXISTS epg_playlist_time ON epg_programmes(playlist_id, start_millis, stop_millis)",
        )
        db.execSQL(
            "CREATE INDEX IF NOT EXISTS epg_channel_time ON epg_programmes(playlist_id, channel_id, start_millis)",
        )
    }

    private fun createCatalogSearch(db: SQLiteDatabase) {
        // FTS5 is available on current Android TV devices. Keep queries able to
        // fall back to indexed SQL if an OEM ships SQLite without that module.
        runCatching {
            db.execSQL(
                """CREATE VIRTUAL TABLE IF NOT EXISTS channels_fts USING fts5(
                    name, group_name, tvg_id,
                    content='channels', content_rowid='id',
                    tokenize='unicode61 remove_diacritics 2'
                )""".trimIndent(),
            )
            db.execSQL(
                """CREATE TRIGGER IF NOT EXISTS channels_fts_update AFTER UPDATE OF name, group_name, tvg_id ON channels BEGIN
                    INSERT INTO channels_fts(channels_fts, rowid, name, group_name, tvg_id)
                    VALUES ('delete', old.id, old.name, old.group_name, old.tvg_id);
                    INSERT INTO channels_fts(rowid, name, group_name, tvg_id)
                    VALUES (new.id, new.name, new.group_name, new.tvg_id);
                END""".trimIndent(),
            )
            db.execSQL(
                """CREATE TRIGGER IF NOT EXISTS channels_fts_insert AFTER INSERT ON channels BEGIN
                    INSERT INTO channels_fts(rowid, name, group_name, tvg_id)
                    VALUES (new.id, new.name, new.group_name, new.tvg_id);
                END""".trimIndent(),
            )
            db.execSQL(
                """CREATE TRIGGER IF NOT EXISTS channels_fts_delete AFTER DELETE ON channels BEGIN
                    INSERT INTO channels_fts(channels_fts, rowid, name, group_name, tvg_id)
                    VALUES ('delete', old.id, old.name, old.group_name, old.tvg_id);
                END""".trimIndent(),
            )
            db.execSQL("INSERT INTO channels_fts(channels_fts) VALUES ('rebuild')")
        }
    }

    private fun migrateSinglePlaylist(db: SQLiteDatabase) {
        createPlaylistsTable(db)
        val name = legacyMetadata(db, "playlist_name").ifBlank { "Lista IPTV" }
        val epg = legacyMetadata(db, "epg_url")
        val type = legacyMetadata(db, "source_type").ifBlank { SourceType.M3U.name }
        val source = legacyMetadata(db, "source_data")
        val hasChannels = db.rawQuery("SELECT EXISTS(SELECT 1 FROM channels LIMIT 1)", null).use {
            it.moveToFirst() && it.getInt(0) == 1
        }
        if (hasChannels || source.isNotBlank()) {
            db.insertOrThrow("playlists", null, ContentValues().apply {
                put("id", 1L)
                put("name", name)
                put("encrypted_epg_url", epg)
                put("source_type", type)
                put("encrypted_source_data", source)
                put("updated_at", System.currentTimeMillis())
                put("active", 1)
            })
        }
        // SQLite on older Android versions rejects ADD COLUMN when it combines a
        // non-null default with REFERENCES. Rebuild the table so the v1 catalog is
        // copied atomically and remains available after the upgrade.
        db.execSQL("ALTER TABLE channels RENAME TO channels_v1")
        db.execSQL("DROP INDEX IF EXISTS channels_type_group")
        createChannelsTable(db)
        db.execSQL(
            """INSERT INTO channels (
                id, playlist_id, name, encrypted_url, group_name, logo, tvg_id,
                encrypted_headers, stream_type, quality, favorite
            ) SELECT
                id, 1, name, encrypted_url, group_name, logo, tvg_id,
                encrypted_headers, stream_type, quality, favorite
            FROM channels_v1""".trimIndent(),
        )
        db.execSQL("DROP TABLE channels_v1")
        db.execSQL("DROP TABLE metadata")
    }

    @Synchronized
    fun save(playlist: Playlist, source: SourceConfig, preferredId: Long? = null): Long {
        val db = writableDatabase
        return db.transaction {
            val playlistId = preferredId?.takeIf { playlistExists(db, it) }
                ?: findSourceId(db, source)
                ?: db.insertOrThrow("playlists", null, playlistValues(playlist, source, active = true))
            db.update("playlists", playlistValues(playlist, source, active = true), "id = ?", arrayOf(playlistId.toString()))
            db.update("playlists", ContentValues().apply { put("active", 0) }, "id != ?", arrayOf(playlistId.toString()))
            syncChannels(db, playlistId, playlist.channels)
            playlistId
        }
    }

    @Synchronized
    fun saveIncremental(
        name: String,
        source: SourceConfig,
        preferredId: Long? = null,
        produce: ((List<Channel>) -> Unit) -> String,
    ): Long {
        val db = writableDatabase
        return db.transaction {
            val empty = Playlist(name, emptyList())
            val playlistId = preferredId?.takeIf { playlistExists(db, it) }
                ?: findSourceId(db, source)
                ?: db.insertOrThrow("playlists", null, playlistValues(empty, source, active = true))
            db.update("playlists", ContentValues().apply { put("active", 0) }, "id != ?", arrayOf(playlistId.toString()))
            val existing = loadExistingChannels(db, playlistId, null)
            val consume: (List<Channel>) -> Unit = { batch ->
                batch.forEach { channel -> applyDifferentialChannel(db, playlistId, channel, existing) }
            }
            val epgUrl = produce(consume)
            deleteStaleChannels(db, playlistId, existing)
            db.update(
                "playlists",
                playlistValues(Playlist(name, emptyList(), epgUrl), source, active = true),
                "id = ?",
                arrayOf(playlistId.toString()),
            )
            playlistId
        }
    }

    @Synchronized
    fun loadActive(): Pair<Long?, Playlist> {
        val id = readableDatabase.rawQuery(
            "SELECT id FROM playlists ORDER BY active DESC, updated_at DESC LIMIT 1", null,
        ).use { if (it.moveToFirst()) it.getLong(0) else null }
        return id to if (id == null) Playlist("IPTV Player TV", emptyList()) else load(id)
    }

    @Synchronized
    fun activate(id: Long): Playlist {
        require(playlistExists(readableDatabase, id)) { "A lista selecionada já não existe." }
        writableDatabase.transaction {
            writableDatabase.update("playlists", ContentValues().apply { put("active", 0) }, null, null)
            writableDatabase.update("playlists", ContentValues().apply { put("active", 1) }, "id = ?", arrayOf(id.toString()))
        }
        return load(id)
    }

    @Synchronized
    fun load(id: Long): Playlist {
        val header = readableDatabase.query(
            "playlists", arrayOf("name", "encrypted_epg_url"), "id = ?", arrayOf(id.toString()), null, null, null,
        ).use {
            require(it.moveToFirst()) { "A lista selecionada já não existe." }
            it.getString(0) to cipher.decrypt(it.getString(1))
        }
        // Catalogue rows are deliberately not materialized here. Consumers
        // obtain them through catalogPage(), keeping startup memory bounded.
        return Playlist(header.first, emptyList(), header.second)
    }

    @Synchronized
    override fun catalogPage(
        playlistId: Long,
        type: StreamType,
        group: String,
        query: String,
        offset: Int,
        limit: Int,
    ): CatalogPage {
        // No artificial ceiling: "Todos" and the in-player guide intentionally request every
        // channel in one page, and some playlists run to tens of thousands of channels.
        require(offset >= 0 && limit > 0) { "Página de catálogo inválida." }
        val db = readableDatabase
        val clauses = mutableListOf("c.playlist_id = ?", "c.stream_type = ?")
        val args = mutableListOf(playlistId.toString(), type.name)
        if (group != "Todos" && group.isNotBlank()) {
            clauses += "c.group_name = ?"
            args += group
        }
        val normalizedQuery = query.trim()
        val ftsTerms = Regex("[\\p{L}\\p{N}_]+")
            .findAll(normalizedQuery)
            .map { "\"${it.value.replace("\"", "\"\"")}\"*" }
            .joinToString(" AND ")
        val useFts = ftsTerms.isNotBlank() && db.rawQuery(
            "SELECT EXISTS(SELECT 1 FROM sqlite_master WHERE name = 'channels_fts')", null,
        ).use { it.moveToFirst() && it.getInt(0) == 1 }
        val from = if (useFts) {
            clauses += "channels_fts MATCH ?"
            args += ftsTerms
            "channels c JOIN channels_fts ON channels_fts.rowid = c.id"
        } else {
            if (normalizedQuery.isNotBlank()) {
                clauses += "(instr(lower(c.name), lower(?)) > 0 OR instr(lower(c.group_name), lower(?)) > 0)"
                args += normalizedQuery
                args += normalizedQuery
            }
            "channels c"
        }
        val where = clauses.joinToString(" AND ")
        val total = db.rawQuery(
            "SELECT COUNT(*) FROM $from WHERE $where",
            args.toTypedArray(),
        ).use { cursor -> if (cursor.moveToFirst()) cursor.getInt(0) else 0 }
        val channels = ArrayList<Channel>(minOf(limit, total))
        db.rawQuery(
            """SELECT c.id, c.name, c.group_name, c.logo, c.tvg_id, c.stream_type, c.quality, c.favorite
                FROM $from WHERE $where
                ORDER BY c.name COLLATE NOCASE, c.id
                LIMIT ? OFFSET ?""".trimIndent(),
            (args + limit.toString() + offset.toString()).toTypedArray(),
        ).use { cursor ->
            while (cursor.moveToNext()) channels += catalogChannel(cursor)
        }
        val groups = mutableListOf("Todos")
        db.rawQuery(
            """SELECT DISTINCT group_name FROM channels
                WHERE playlist_id = ? AND stream_type = ?
                ORDER BY group_name COLLATE NOCASE""".trimIndent(),
            arrayOf(playlistId.toString(), type.name),
        ).use { cursor -> while (cursor.moveToNext()) groups += cursor.getString(0).orEmpty() }
        return CatalogPage(channels, groups, total, offset)
    }

    private fun catalogChannel(cursor: android.database.Cursor) = Channel(
        id = cursor.getLong(cursor.getColumnIndexOrThrow("id")),
        name = cursor.string("name"),
        url = "secure-channel://${cursor.getLong(cursor.getColumnIndexOrThrow("id"))}",
        group = cursor.string("group_name"),
        logo = cursor.string("logo"),
        tvgId = cursor.string("tvg_id"),
        type = runCatching { StreamType.valueOf(cursor.string("stream_type")) }.getOrDefault(StreamType.LIVE),
        quality = cursor.string("quality"),
        favorite = cursor.getInt(cursor.getColumnIndexOrThrow("favorite")) == 1,
    )

    @Synchronized
    fun resolveChannel(channel: Channel): Channel {
        if (!channel.url.startsWith("secure-channel://")) return channel
        val id = channel.url.removePrefix("secure-channel://").toLongOrNull()
            ?: error("Identificador de conteúdo inválido.")
        return readableDatabase.query(
            "channels", arrayOf("encrypted_url", "encrypted_headers"), "id = ?", arrayOf(id.toString()), null, null, null,
        ).use { cursor ->
            require(cursor.moveToFirst()) { "Este conteúdo já não existe na lista." }
            val headers = cipher.decrypt(cursor.getString(1)).split('\u0000')
            val url = cipher.decrypt(cursor.getString(0))
            require(url.isNotBlank()) { "Não foi possível ler os dados protegidos deste conteúdo." }
            channel.copy(
                url = url,
                userAgent = headers.getOrElse(0) { "" },
                referer = headers.getOrElse(1) { "" },
            )
        }
    }

    @Synchronized
    fun loadSource(id: Long): SourceConfig = readableDatabase.query(
        "playlists", arrayOf("source_type", "encrypted_source_data"), "id = ?", arrayOf(id.toString()), null, null, null,
    ).use {
        require(it.moveToFirst()) { "A lista selecionada já não existe." }
        decodeSource(it.getString(0), it.getString(1))
    }

    @Synchronized
    fun summaries(): List<PlaylistSummary> {
        val result = mutableListOf<PlaylistSummary>()
        readableDatabase.rawQuery(
            """SELECT p.id, p.name, p.source_type, p.updated_at, p.active, COUNT(c.id)
                FROM playlists p LEFT JOIN channels c ON c.playlist_id = p.id
                GROUP BY p.id ORDER BY p.active DESC, p.updated_at DESC""".trimIndent(), null,
        ).use { cursor ->
            while (cursor.moveToNext()) result += PlaylistSummary(
                id = cursor.getLong(0),
                name = cursor.getString(1),
                sourceLabel = when (runCatching { SourceType.valueOf(cursor.getString(2)) }.getOrDefault(SourceType.M3U)) {
                    SourceType.M3U -> "M3U"
                    SourceType.XTREAM -> "Xtream Codes"
                    SourceType.STALKER -> "Stalker Portal"
                },
                updatedAtMillis = cursor.getLong(3),
                active = cursor.getInt(4) == 1,
                channelCount = cursor.getInt(5),
            )
        }
        return result
    }

    @Synchronized
    fun delete(id: Long): Boolean {
        val wasActive = readableDatabase.query("playlists", arrayOf("active"), "id = ?", arrayOf(id.toString()), null, null, null)
            .use { it.moveToFirst() && it.getInt(0) == 1 }
        writableDatabase.delete("playlists", "id = ?", arrayOf(id.toString()))
        if (wasActive) {
            writableDatabase.execSQL(
                "UPDATE playlists SET active = 1 WHERE id = (SELECT id FROM playlists ORDER BY updated_at DESC LIMIT 1)",
            )
        }
        return wasActive
    }

    @Synchronized
    fun setFavorite(channelId: Long, favorite: Boolean) {
        require(channelId > 0) { "Este conteúdo ainda não está guardado no catálogo." }
        val changed = writableDatabase.update(
            "channels",
            ContentValues().apply { put("favorite", if (favorite) 1 else 0) },
            "id = ?",
            arrayOf(channelId.toString()),
        )
        require(changed == 1) { "Este conteúdo já não existe na lista." }
    }

    @Synchronized
    fun replaceCatalogType(playlistId: Long, type: StreamType, channels: List<Channel>) {
        val db = writableDatabase
        db.transaction {
            syncChannels(db, playlistId, channels, type)
            db.execSQL("UPDATE playlists SET updated_at = ? WHERE id = ?", arrayOf(System.currentTimeMillis(), playlistId))
        }
    }

    @Synchronized
    fun playbackPosition(playlistId: Long, mediaKey: String): Long = readableDatabase.query(
        "playback_progress",
        arrayOf("position_ms"),
        "playlist_id = ? AND media_key = ?",
        arrayOf(playlistId.toString(), mediaKey),
        null,
        null,
        null,
    ).use { if (it.moveToFirst()) it.getLong(0) else 0L }

    @Synchronized
    fun savePlaybackPosition(playlistId: Long, mediaKey: String, positionMs: Long, durationMs: Long) {
        if (positionMs < 10_000 || (durationMs > 0 && positionMs >= durationMs * 95 / 100)) {
            writableDatabase.delete(
                "playback_progress",
                "playlist_id = ? AND media_key = ?",
                arrayOf(playlistId.toString(), mediaKey),
            )
            return
        }
        writableDatabase.insertWithOnConflict(
            "playback_progress",
            null,
            ContentValues().apply {
                put("playlist_id", playlistId)
                put("media_key", mediaKey)
                put("position_ms", positionMs)
                put("duration_ms", durationMs.coerceAtLeast(0))
                put("updated_at", System.currentTimeMillis())
            },
            SQLiteDatabase.CONFLICT_REPLACE,
        )
    }

    @Synchronized
    fun replaceEpg(programmes: List<pt.iptvplayer.tv.model.EpgProgram>, nowMillis: Long = System.currentTimeMillis()) {
        val playlistId = activePlaylistId() ?: return
        val db = writableDatabase
        db.transaction {
            db.delete("epg_programmes", "playlist_id = ? AND stop_millis < ?", arrayOf(playlistId.toString(), nowMillis.toString()))
            val statement = db.compileStatement(
                """INSERT OR REPLACE INTO epg_programmes
                    (playlist_id, channel_id, title, start_millis, stop_millis, description, category, catchup_url)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)""".trimIndent(),
            )
            programmes.forEach { item ->
                statement.clearBindings()
                statement.bindLong(1, playlistId)
                statement.bindString(2, item.channelId)
                statement.bindString(3, item.title)
                statement.bindLong(4, item.startMillis)
                statement.bindLong(5, item.stopMillis)
                statement.bindString(6, item.description)
                statement.bindString(7, item.category)
                statement.bindString(8, item.catchupUrl)
                statement.executeInsert()
            }
        }
    }

    @Synchronized
    fun currentAndNextEpg(nowMillis: Long = System.currentTimeMillis()): Map<String, List<pt.iptvplayer.tv.model.EpgProgram>> {
        val playlistId = activePlaylistId() ?: return emptyMap()
        val result = linkedMapOf<String, MutableList<pt.iptvplayer.tv.model.EpgProgram>>()
        readableDatabase.rawQuery(
            """SELECT channel_id, title, start_millis, stop_millis, description, category, catchup_url
                FROM epg_programmes
                WHERE playlist_id = ? AND stop_millis > ?
                ORDER BY channel_id, start_millis""".trimIndent(),
            arrayOf(playlistId.toString(), nowMillis.toString()),
        ).use { cursor ->
            while (cursor.moveToNext()) {
                val channelId = cursor.getString(0)
                val items = result.getOrPut(channelId) { mutableListOf() }
                if (items.size < 2) items += pt.iptvplayer.tv.model.EpgProgram(
                    channelId, cursor.getString(1), cursor.getLong(2), cursor.getLong(3),
                    cursor.getString(4), cursor.getString(5), cursor.getString(6),
                )
            }
        }
        return result
    }

    /** Like [currentAndNextEpg] but returns every programme in an arbitrary window, for the EPG grid. */
    @Synchronized
    fun epgWindow(fromMillis: Long, toMillis: Long): Map<String, List<pt.iptvplayer.tv.model.EpgProgram>> {
        val playlistId = activePlaylistId() ?: return emptyMap()
        val result = linkedMapOf<String, MutableList<pt.iptvplayer.tv.model.EpgProgram>>()
        readableDatabase.rawQuery(
            """SELECT channel_id, title, start_millis, stop_millis, description, category, catchup_url
                FROM epg_programmes
                WHERE playlist_id = ? AND stop_millis > ? AND start_millis < ?
                ORDER BY channel_id, start_millis""".trimIndent(),
            arrayOf(playlistId.toString(), fromMillis.toString(), toMillis.toString()),
        ).use { cursor ->
            while (cursor.moveToNext()) {
                val channelId = cursor.getString(0)
                result.getOrPut(channelId) { mutableListOf() } += pt.iptvplayer.tv.model.EpgProgram(
                    channelId, cursor.getString(1), cursor.getLong(2), cursor.getLong(3),
                    cursor.getString(4), cursor.getString(5), cursor.getString(6),
                )
            }
        }
        return result
    }

    private fun activePlaylistId(): Long? = readableDatabase.rawQuery(
        "SELECT id FROM playlists WHERE active = 1 LIMIT 1", null,
    ).use { if (it.moveToFirst()) it.getLong(0) else null }

    @Synchronized
    fun applyDeviceSync(playlistId: Long, rawData: String) {
        val data = JSONObject(rawData)
        require(data.optInt("schema_version") == 1) { "Versão de sincronização incompatível." }
        val favoritesArray = data.optJSONArray("favorites") ?: org.json.JSONArray()
        val progress = data.optJSONObject("progress") ?: JSONObject()
        require(favoritesArray.length() <= 100_000 && progress.length() <= 100_000) {
            "A sincronização contém demasiados itens."
        }
        val favorites = buildSet {
            for (index in 0 until favoritesArray.length()) add(favoritesArray.getString(index))
        }
        val db = writableDatabase
        db.transaction {
            db.query(
                "channels",
                arrayOf("id", "name", "group_name", "tvg_id", "stream_type"),
                "playlist_id = ?",
                arrayOf(playlistId.toString()),
                null,
                null,
                null,
            ).use { cursor ->
                while (cursor.moveToNext()) {
                    val key = stableMediaKey(
                        tvgId = cursor.getString(3).orEmpty(),
                        name = cursor.getString(1).orEmpty(),
                        group = cursor.getString(2).orEmpty(),
                        type = cursor.getString(4).orEmpty(),
                    )
                    if (key in favorites) {
                        db.update(
                            "channels",
                            ContentValues().apply { put("favorite", 1) },
                            "id = ?",
                            arrayOf(cursor.getLong(0).toString()),
                        )
                    }
                }
            }
            progress.keys().forEach { key ->
                val item = progress.optJSONObject(key) ?: return@forEach
                val position = item.optLong("position_ms").coerceAtLeast(0)
                val duration = item.optLong("duration_ms").coerceAtLeast(0)
                if (duration > 0 && position >= 10_000 && position < duration * 95 / 100) {
                    db.insertWithOnConflict(
                        "playback_progress",
                        null,
                        ContentValues().apply {
                            put("playlist_id", playlistId)
                            put("media_key", key)
                            put("position_ms", position)
                            put("duration_ms", duration)
                            put("updated_at", System.currentTimeMillis())
                        },
                        SQLiteDatabase.CONFLICT_REPLACE,
                    )
                }
            }
        }
    }

    @Synchronized
    fun exportDeviceSync(playlistId: Long): String {
        val favorites = org.json.JSONArray()
        readableDatabase.query(
            "channels", arrayOf("name", "group_name", "tvg_id", "stream_type", "favorite"),
            "playlist_id = ?", arrayOf(playlistId.toString()), null, null, null,
        ).use { cursor ->
            while (cursor.moveToNext()) if (cursor.getInt(4) == 1) {
                favorites.put(stableMediaKey(cursor.getString(2), cursor.getString(0), cursor.getString(1), cursor.getString(3)))
            }
        }
        val progress = JSONObject()
        readableDatabase.query(
            "playback_progress", arrayOf("media_key", "position_ms", "duration_ms", "updated_at"),
            "playlist_id = ?", arrayOf(playlistId.toString()), null, null, null,
        ).use { cursor ->
            while (cursor.moveToNext()) progress.put(
                cursor.getString(0),
                JSONObject().put("position_ms", cursor.getLong(1)).put("duration_ms", cursor.getLong(2))
                    .put("updated_at", cursor.getLong(3)),
            )
        }
        return JSONObject()
            .put("schema_version", 1)
            .put("exported_at", System.currentTimeMillis())
            .put("favorites", favorites)
            .put("progress", progress)
            .toString()
    }

    private fun playlistValues(playlist: Playlist, source: SourceConfig, active: Boolean) = ContentValues().apply {
        put("name", playlist.name)
        put("encrypted_epg_url", cipher.encrypt(playlist.epgUrl))
        put("source_type", source.type.name)
        put("encrypted_source_data", encodeSource(source))
        put("updated_at", System.currentTimeMillis())
        put("active", if (active) 1 else 0)
    }

    private fun insertChannel(
        db: SQLiteDatabase,
        playlistId: Long,
        channel: Channel,
        favorite: Boolean = channel.favorite,
    ) {
        db.insertOrThrow("channels", null, channelValues(playlistId, channel, favorite))
    }

    private data class ExistingChannel(
        val id: Long,
        val contentHash: String,
        val favorite: Boolean,
    )

    private fun syncChannels(
        db: SQLiteDatabase,
        playlistId: Long,
        channels: List<Channel>,
        type: StreamType? = null,
    ) {
        val existing = loadExistingChannels(db, playlistId, type)
        channels.forEach { channel ->
            applyDifferentialChannel(db, playlistId, channel, existing)
        }
        deleteStaleChannels(db, playlistId, existing)
    }

    private fun loadExistingChannels(
        db: SQLiteDatabase,
        playlistId: Long,
        type: StreamType?,
    ): MutableMap<String, ArrayDeque<ExistingChannel>> {
        val selection = buildString {
            append("playlist_id = ?")
            if (type != null) append(" AND stream_type = ?")
        }
        val args = if (type == null) {
            arrayOf(playlistId.toString())
        } else {
            arrayOf(playlistId.toString(), type.name)
        }
        val existing = mutableMapOf<String, ArrayDeque<ExistingChannel>>()
        db.query(
            "channels",
            arrayOf("id", "name", "group_name", "tvg_id", "stream_type", "content_hash", "favorite"),
            selection,
            args,
            null,
            null,
            "id",
        ).use { cursor ->
            while (cursor.moveToNext()) {
                val identity = channelIdentity(
                    cursor.getString(1).orEmpty(),
                    cursor.getString(2).orEmpty(),
                    cursor.getString(3).orEmpty(),
                    cursor.getString(4).orEmpty(),
                )
                existing.getOrPut(identity) { ArrayDeque() }.addLast(
                    ExistingChannel(
                        cursor.getLong(0),
                        cursor.getString(5).orEmpty(),
                        cursor.getInt(6) == 1,
                    ),
                )
            }
        }
        return existing
    }

    private fun applyDifferentialChannel(
        db: SQLiteDatabase,
        playlistId: Long,
        channel: Channel,
        existing: MutableMap<String, ArrayDeque<ExistingChannel>>,
    ) {
        val old = existing[channel.identity()]?.removeFirstOrNull()
        if (old == null) {
            insertChannel(db, playlistId, channel)
            return
        }
        val favorite = channel.favorite || old.favorite
        if (old.contentHash != channel.contentHash()) {
            db.update(
                "channels",
                channelValues(playlistId, channel, favorite),
                "id = ? AND playlist_id = ?",
                arrayOf(old.id.toString(), playlistId.toString()),
            )
        } else if (favorite != old.favorite) {
            db.update(
                "channels",
                ContentValues().apply { put("favorite", if (favorite) 1 else 0) },
                "id = ? AND playlist_id = ?",
                arrayOf(old.id.toString(), playlistId.toString()),
            )
        }
    }

    private fun deleteStaleChannels(
        db: SQLiteDatabase,
        playlistId: Long,
        existing: MutableMap<String, ArrayDeque<ExistingChannel>>,
    ) {
        existing.values.asSequence().flatMap { it.asSequence() }.forEach { stale ->
            db.delete(
                "channels",
                "id = ? AND playlist_id = ?",
                arrayOf(stale.id.toString(), playlistId.toString()),
            )
        }
    }

    private fun channelValues(
        playlistId: Long,
        channel: Channel,
        favorite: Boolean,
    ) = ContentValues().apply {
        val headers = listOf(channel.userAgent, channel.referer).joinToString("\u0000")
        put("playlist_id", playlistId)
        put("name", channel.name)
        put("encrypted_url", cipher.encrypt(channel.url))
        put("group_name", channel.group)
        put("logo", channel.logo)
        put("tvg_id", channel.tvgId)
        put("encrypted_headers", cipher.encrypt(headers))
        put("stream_type", channel.type.name)
        put("quality", channel.quality)
        put("favorite", if (favorite) 1 else 0)
        put("content_hash", channel.contentHash())
    }

    private fun Channel.contentHash(): String {
        val fields = listOf(
            name,
            url,
            group,
            logo,
            tvgId,
            userAgent,
            referer,
            type.name,
            quality,
            customHeaders.toSortedMap().entries.joinToString("\u0001") { "${it.key}=${it.value}" },
        ).joinToString("\u0000")
        return MessageDigest.getInstance("SHA-256")
            .digest(fields.toByteArray(Charsets.UTF_8))
            .joinToString("") { "%02x".format(it) }
    }

    private fun Channel.identity(): String = channelIdentity(name, group, tvgId, type.name)

    private fun channelIdentity(name: String, group: String, tvgId: String, type: String): String =
        listOf(tvgId.ifBlank { name }, group, type).joinToString("\u0000")

    private fun stableMediaKey(tvgId: String, name: String, group: String, type: String): String {
        val identity = listOf(tvgId.ifBlank { name }, group, type.uppercase()).joinToString("\u0000")
        val digest = MessageDigest.getInstance("SHA-256").digest(identity.toByteArray(Charsets.UTF_8))
        return "media:" + digest.joinToString("") { "%02x".format(it) }
    }

    private fun findSourceId(db: SQLiteDatabase, source: SourceConfig): Long? = db.query(
        "playlists", arrayOf("id", "source_type", "encrypted_source_data"), "source_type = ?", arrayOf(source.type.name), null, null, null,
    ).use { cursor ->
        while (cursor.moveToNext()) {
            if (decodeSource(cursor.getString(1), cursor.getString(2)) == source) return@use cursor.getLong(0)
        }
        null
    }

    private fun encodeSource(source: SourceConfig): String = cipher.encrypt(
        listOf(source.serverUrl, source.username, source.password, source.macAddress).joinToString("\u0000"),
    )

    private fun decodeSource(type: String, encrypted: String): SourceConfig {
        val values = cipher.decrypt(encrypted).split('\u0000')
        return SourceConfig(
            type = runCatching { SourceType.valueOf(type) }.getOrDefault(SourceType.M3U),
            serverUrl = values.getOrElse(0) { "" },
            username = values.getOrElse(1) { "" },
            password = values.getOrElse(2) { "" },
            macAddress = values.getOrElse(3) { "" },
        )
    }

    private fun playlistExists(db: SQLiteDatabase, id: Long): Boolean = db.rawQuery(
        "SELECT EXISTS(SELECT 1 FROM playlists WHERE id = ?)", arrayOf(id.toString()),
    ).use { it.moveToFirst() && it.getInt(0) == 1 }

    private fun legacyMetadata(db: SQLiteDatabase, key: String): String = db.query(
        "metadata", arrayOf("value"), "key = ?", arrayOf(key), null, null, null,
    ).use { if (it.moveToFirst()) it.getString(0).orEmpty() else "" }

    private fun android.database.Cursor.string(column: String): String =
        getString(getColumnIndexOrThrow(column)).orEmpty()

    companion object {
        private const val DATABASE_VERSION = 6
    }
}
