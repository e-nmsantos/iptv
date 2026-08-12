package pt.iptvplayer.tv.data.room

import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import androidx.room.testing.MigrationTestHelper
import androidx.sqlite.db.framework.FrameworkSQLiteOpenHelperFactory
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Before
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import pt.iptvplayer.tv.data.CatalogDatabase
import pt.iptvplayer.tv.data.SourceConfig
import pt.iptvplayer.tv.data.SourceType
import pt.iptvplayer.tv.model.Channel
import pt.iptvplayer.tv.model.Playlist

@RunWith(AndroidJUnit4::class)
class RoomCatalogDatabaseTest {
    private val context = ApplicationProvider.getApplicationContext<android.content.Context>()

    @get:Rule
    val migrationHelper = MigrationTestHelper(
        InstrumentationRegistry.getInstrumentation(),
        RoomCatalogDatabase::class.java,
        emptyList(),
        FrameworkSQLiteOpenHelperFactory(),
    )

    @Before
    fun resetDatabase() {
        context.deleteDatabase("iptv-tv.db")
    }

    @After
    fun cleanDatabase() {
        context.deleteDatabase("iptv-tv.db")
    }

    @Test
    fun roomValidatesAndReadsTheVersionSixSchema() = runBlocking {
        CatalogDatabase(context).use { legacy ->
            legacy.save(
                Playlist(
                    name = "Teste",
                    channels = listOf(Channel(name = "Canal", url = "https://example.test/live")),
                ),
                SourceConfig(SourceType.M3U, "https://example.test/list.m3u"),
            )
        }

        val room = RoomCatalogDatabase.build(context)
        try {
            assertEquals(1, room.catalogDao().observeCount(1, "LIVE", "Todos", "").first())
        } finally {
            room.close()
        }
    }

    @Test
    fun migrationFiveToSixPreservesCatalogAndCreatesEpgStorage() {
        val databaseName = "room-migration-5-6.db"
        migrationHelper.createDatabase(databaseName, 5).apply {
            execSQL(
                """INSERT INTO playlists
                    (id, name, encrypted_epg_url, source_type, encrypted_source_data, updated_at, active)
                    VALUES (1, 'Teste', '', 'M3U', '', 1, 1)""".trimIndent(),
            )
            execSQL(
                """INSERT INTO channels
                    (id, playlist_id, name, encrypted_url, group_name, logo, tvg_id,
                     encrypted_headers, stream_type, quality, favorite, content_hash)
                    VALUES (1, 1, 'Canal', '', 'Geral', '', 'canal-1', '', 'LIVE', '', 0, '')""".trimIndent(),
            )
            close()
        }

        migrationHelper.runMigrationsAndValidate(
            databaseName,
            6,
            true,
            RoomCatalogDatabase.MIGRATION_5_6,
        ).use { migrated ->
            migrated.query("SELECT COUNT(*) FROM channels").use { cursor ->
                cursor.moveToFirst()
                assertEquals(1, cursor.getInt(0))
            }
            migrated.query("SELECT COUNT(*) FROM epg_programmes").use { cursor ->
                cursor.moveToFirst()
                assertEquals(0, cursor.getInt(0))
            }
        }
    }
}
