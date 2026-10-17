package pt.iptvplayer.tv

import pt.iptvplayer.tv.model.Channel
import pt.iptvplayer.tv.model.EpgProgram
import pt.iptvplayer.tv.model.EpgReminder
import pt.iptvplayer.tv.model.EpisodeContext
import pt.iptvplayer.tv.model.PlaylistSummary
import pt.iptvplayer.tv.model.StreamType
import pt.iptvplayer.tv.model.WatchHistoryItem

data class CatalogUiState(
    val playlistName: String = "IPTV Player TV",
    val channels: List<Channel> = emptyList(),
    val selectedType: StreamType = StreamType.LIVE,
    val selectedGroup: String = "Todos",
    val query: String = "",
    val loading: Boolean = true,
    val error: String? = null,
    val pairingUrl: String? = null,
    val pairingExpiresAtMillis: Long = 0,
    val pairingMessage: String? = null,
    val pairingPin: String? = null,
    val seriesTitle: String? = null,
    val seriesEpisodes: List<Channel> = emptyList(),
    val seriesLoading: Boolean = false,
    val playlists: List<PlaylistSummary> = emptyList(),
    val epg: Map<String, List<EpgProgram>> = emptyMap(),
    val epgLoading: Boolean = false,
    val availableGroups: List<String> = listOf("Todos"),
    val totalChannels: Int = 0,
    val hasMoreChannels: Boolean = false,
    val homeFavorites: List<Channel> = emptyList(),
    // Every channel of whatever type is currently playing, regardless of which group the
    // catalog browser had filtered to before the user pressed play — the in-player channel
    // guide's "Todos" only works if it has more than the one group's worth of channels to show.
    val guideChannels: List<Channel> = emptyList(),
    val liveGuideChannels: List<Channel> = emptyList(),
    val epgWindow: Map<String, List<EpgProgram>> = emptyMap(),
    val epgWindowLoading: Boolean = false,
    // Início rows.
    val continueWatching: List<WatchHistoryItem> = emptyList(),
    val recentLive: List<Channel> = emptyList(),
    val recentMovies: List<Channel> = emptyList(),
    val recentSeries: List<Channel> = emptyList(),
    /** The series that is open in the catalog browser, so its episodes can carry it as parent. */
    val openSeries: Channel? = null,
    /** Episode list of whatever series episode is playing — drives "Próximo episódio". */
    val episodeContext: EpisodeContext? = null,
    val reminders: List<EpgReminder> = emptyList(),
    /** A reminder whose programme has just started; shown as a banner until dismissed. */
    val dueReminder: EpgReminder? = null,
    /** Channel to open straight away after launch ("Abrir no último canal"); consumed once. */
    val startupChannel: Channel? = null,
)
