package pt.iptvplayer.tv.data.room

import android.content.Context
import androidx.room.ColumnInfo
import androidx.room.Dao
import androidx.room.Database
import androidx.room.Entity
import androidx.room.ForeignKey
import androidx.room.Index
import androidx.room.PrimaryKey
import androidx.room.Query
import androidx.room.Room
import androidx.room.RoomDatabase
import androidx.room.migration.Migration
import androidx.sqlite.db.SupportSQLiteDatabase
import kotlinx.coroutines.flow.Flow

@Entity(tableName = "playlists")
data class RoomPlaylistEntity(
    @PrimaryKey(autoGenerate = true) val id: Long,
    val name: String,
    @ColumnInfo(name = "encrypted_epg_url") val encryptedEpgUrl: String,
    @ColumnInfo(name = "source_type") val sourceType: String,
    @ColumnInfo(name = "encrypted_source_data") val encryptedSourceData: String,
    @ColumnInfo(name = "updated_at") val updatedAt: Long,
    @ColumnInfo(defaultValue = "0") val active: Int,
)

@Entity(
    tableName = "channels",
    foreignKeys = [
        ForeignKey(
            entity = RoomPlaylistEntity::class,
            parentColumns = ["id"],
            childColumns = ["playlist_id"],
            onDelete = ForeignKey.CASCADE,
        ),
    ],
    indices = [
        Index(
            name = "channels_playlist_type_group",
            value = ["playlist_id", "stream_type", "group_name"],
        ),
        Index(
            name = "channels_differential",
            value = ["playlist_id", "stream_type", "tvg_id", "name"],
        ),
    ],
)
data class RoomChannelEntity(
    @PrimaryKey(autoGenerate = true) val id: Long,
    @ColumnInfo(name = "playlist_id") val playlistId: Long,
    val name: String,
    @ColumnInfo(name = "encrypted_url") val encryptedUrl: String,
    @ColumnInfo(name = "group_name") val groupName: String,
    val logo: String,
    @ColumnInfo(name = "tvg_id") val tvgId: String,
    @ColumnInfo(name = "encrypted_headers") val encryptedHeaders: String,
    @ColumnInfo(name = "stream_type") val streamType: String,
    val quality: String,
    @ColumnInfo(defaultValue = "0") val favorite: Int,
    @ColumnInfo(name = "content_hash", defaultValue = "''") val contentHash: String,
)

@Entity(
    tableName = "playback_progress",
    primaryKeys = ["playlist_id", "media_key"],
    foreignKeys = [
        ForeignKey(
            entity = RoomPlaylistEntity::class,
            parentColumns = ["id"],
            childColumns = ["playlist_id"],
            onDelete = ForeignKey.CASCADE,
        ),
    ],
    indices = [Index(name = "playback_progress_playlist", value = ["playlist_id"])],
)
data class RoomPlaybackProgressEntity(
    @ColumnInfo(name = "playlist_id") val playlistId: Long,
    @ColumnInfo(name = "media_key") val mediaKey: String,
    @ColumnInfo(name = "position_ms") val positionMs: Long,
    @ColumnInfo(name = "duration_ms") val durationMs: Long,
    @ColumnInfo(name = "updated_at") val updatedAt: Long,
)

@Entity(
    tableName = "epg_programmes",
    primaryKeys = ["playlist_id", "channel_id", "start_millis"],
    foreignKeys = [
        ForeignKey(
            entity = RoomPlaylistEntity::class,
            parentColumns = ["id"],
            childColumns = ["playlist_id"],
            onDelete = ForeignKey.CASCADE,
        ),
    ],
    indices = [
        Index(name = "epg_playlist_time", value = ["playlist_id", "start_millis", "stop_millis"]),
        Index(name = "epg_channel_time", value = ["playlist_id", "channel_id", "start_millis"]),
    ],
)
data class RoomEpgProgrammeEntity(
    @ColumnInfo(name = "playlist_id") val playlistId: Long,
    @ColumnInfo(name = "channel_id") val channelId: String,
    val title: String,
    @ColumnInfo(name = "start_millis") val startMillis: Long,
    @ColumnInfo(name = "stop_millis") val stopMillis: Long,
    val description: String,
    val category: String,
    @ColumnInfo(name = "catchup_url") val catchupUrl: String,
)

data class RoomCatalogRow(
    val id: Long,
    val name: String,
    @ColumnInfo(name = "group_name") val groupName: String,
    val logo: String,
    @ColumnInfo(name = "tvg_id") val tvgId: String,
    @ColumnInfo(name = "stream_type") val streamType: String,
    val quality: String,
    val favorite: Int,
)

@Dao
interface RoomCatalogDao {
    @Query(
        """SELECT id, name, group_name, logo, tvg_id, stream_type, quality, favorite
           FROM channels
           WHERE playlist_id = :playlistId AND stream_type = :type
             AND (:groupName = 'Todos' OR group_name = :groupName)
             AND (:query = '' OR instr(lower(name), lower(:query)) > 0
                  OR instr(lower(group_name), lower(:query)) > 0)
           ORDER BY name COLLATE NOCASE, id
           LIMIT :limit OFFSET :offset""",
    )
    fun observePage(
        playlistId: Long,
        type: String,
        groupName: String,
        query: String,
        offset: Int,
        limit: Int,
    ): Flow<List<RoomCatalogRow>>

    @Query(
        """SELECT COUNT(*) FROM channels
           WHERE playlist_id = :playlistId AND stream_type = :type
             AND (:groupName = 'Todos' OR group_name = :groupName)
             AND (:query = '' OR instr(lower(name), lower(:query)) > 0
                  OR instr(lower(group_name), lower(:query)) > 0)""",
    )
    fun observeCount(
        playlistId: Long,
        type: String,
        groupName: String,
        query: String,
    ): Flow<Int>

    @Query(
        """SELECT DISTINCT group_name FROM channels
           WHERE playlist_id = :playlistId AND stream_type = :type
           ORDER BY group_name COLLATE NOCASE""",
    )
    fun observeGroups(playlistId: Long, type: String): Flow<List<String>>

    @Query(
        """SELECT * FROM epg_programmes
           WHERE playlist_id = :playlistId AND stop_millis > :fromMillis AND start_millis < :toMillis
           ORDER BY channel_id, start_millis""",
    )
    fun observeEpg(playlistId: Long, fromMillis: Long, toMillis: Long): Flow<List<RoomEpgProgrammeEntity>>

    @Query(
        """SELECT id, name, group_name, logo, tvg_id, stream_type, quality, favorite
           FROM channels WHERE playlist_id = :playlistId AND favorite = 1
           ORDER BY name COLLATE NOCASE LIMIT :limit""",
    )
    fun observeFavorites(playlistId: Long, limit: Int = 100): Flow<List<RoomCatalogRow>>
}

@Database(
    entities = [
        RoomPlaylistEntity::class,
        RoomChannelEntity::class,
        RoomPlaybackProgressEntity::class,
        RoomEpgProgrammeEntity::class,
    ],
    version = 6,
    exportSchema = true,
)
abstract class RoomCatalogDatabase : RoomDatabase() {
    abstract fun catalogDao(): RoomCatalogDao

    companion object {
        fun build(context: Context): RoomCatalogDatabase = Room.databaseBuilder(
            context.applicationContext,
            RoomCatalogDatabase::class.java,
            "iptv-tv.db",
        ).addMigrations(MIGRATION_5_6).build()

        val MIGRATION_5_6 = object : Migration(5, 6) {
            override fun migrate(db: SupportSQLiteDatabase) {
                db.execSQL(
                    """CREATE TABLE IF NOT EXISTS epg_programmes (
                        playlist_id INTEGER NOT NULL,
                        channel_id TEXT NOT NULL,
                        title TEXT NOT NULL,
                        start_millis INTEGER NOT NULL,
                        stop_millis INTEGER NOT NULL,
                        description TEXT NOT NULL DEFAULT '',
                        category TEXT NOT NULL DEFAULT '',
                        catchup_url TEXT NOT NULL DEFAULT '',
                        PRIMARY KEY (playlist_id, channel_id, start_millis),
                        FOREIGN KEY (playlist_id) REFERENCES playlists(id) ON DELETE CASCADE
                    )""".trimIndent(),
                )
                db.execSQL("CREATE INDEX IF NOT EXISTS epg_playlist_time ON epg_programmes(playlist_id, start_millis, stop_millis)")
                db.execSQL("CREATE INDEX IF NOT EXISTS epg_channel_time ON epg_programmes(playlist_id, channel_id, start_millis)")
            }
        }
    }
}
