package pt.iptvplayer.tv

import android.app.Application
import android.net.Uri
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.flow.collectLatest
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import pt.iptvplayer.tv.data.CatalogDatabase
import pt.iptvplayer.tv.data.CatalogRepository
import pt.iptvplayer.tv.data.PlayerPreferences
import pt.iptvplayer.tv.data.PlayerSettings
import pt.iptvplayer.tv.data.room.RoomCatalogDatabase
import pt.iptvplayer.tv.model.Channel
import pt.iptvplayer.tv.model.EpgProgram
import pt.iptvplayer.tv.model.EpgReminder
import pt.iptvplayer.tv.model.EpisodeContext
import pt.iptvplayer.tv.model.WatchHistoryItem
import pt.iptvplayer.tv.model.PlaylistSummary
import pt.iptvplayer.tv.model.StreamType
import pt.iptvplayer.tv.pairing.PairingCoordinator
import pt.iptvplayer.tv.pairing.PairingPayload
import pt.iptvplayer.tv.pairing.PairingSourceType

class CatalogViewModel(application: Application) : AndroidViewModel(application) {
    private val roomDatabase = RoomCatalogDatabase.build(application)
    private val repository = CatalogRepository(CatalogDatabase(application), roomDatabase)
    private val pairing = PairingCoordinator(application, viewModelScope)
    private var playbackJob: Job? = null
    private var catalogJob: Job? = null
    private var epgWindowJob: Job? = null
    private var currentEpgUrl: String = ""
    private val requestedCatalogs = mutableSetOf<StreamType>()
    private var loadedLimit = CatalogRepository.PAGE_SIZE
    private val mutableState = MutableStateFlow(CatalogUiState())
    val state: StateFlow<CatalogUiState> = mutableState.asStateFlow()
    private val preferences = PlayerPreferences(application)
    val playerSettings: StateFlow<PlayerSettings> = preferences.settings
    private val notifiedReminders = mutableSetOf<Pair<String, Long>>()
    private var startupChannelChecked = false

    init {
        viewModelScope.launch {
            runCatching {
                val summaries = repository.playlists()
                mutableState.update { it.copy(playlists = summaries, loading = summaries.isNotEmpty()) }
                if (summaries.isEmpty()) null else repository.load() to summaries
            }
                .onSuccess { result ->
                    if (result == null) {
                        mutableState.update { it.copy(loading = false) }
                        return@onSuccess
                    }
                    val (playlist, summaries) = result
                    applyPlaylist(playlist, summaries)
                }
                .onFailure(::showError)
        }
        viewModelScope.launch {
            while (true) {
                checkDueReminders()
                delay(15_000)
            }
        }
    }

    fun updateSettings(transform: (PlayerSettings) -> PlayerSettings) = preferences.update(transform)

    fun consumeStartupChannel() = mutableState.update { it.copy(startupChannel = null) }

    fun selectType(type: StreamType) {
        mutableState.update {
            it.copy(
            selectedType = type,
            selectedGroup = "Todos",
            query = "",
            seriesTitle = null,
            seriesEpisodes = emptyList(),
            )
        }
        loadCatalogPage(reset = true, fetchProviderIfEmpty = type != StreamType.LIVE)
    }

    fun selectGroup(group: String) {
        mutableState.update { it.copy(selectedGroup = group) }
        loadCatalogPage(reset = true)
    }

    fun setQuery(query: String) {
        mutableState.update { it.copy(query = query, selectedGroup = "Todos") }
        loadCatalogPage(reset = true)
        mutableState.update { it.copy(query = query) }
    }

    fun loadNextCatalogPage() {
        if (!mutableState.value.hasMoreChannels) return
        loadedLimit += CatalogRepository.PAGE_SIZE
        loadCatalogPage(reset = false)
        // Catálogo completo carregado em memória por tipo
    }
    fun clearError() = mutableState.update { it.copy(error = null) }

    fun toggleFavorite(channel: Channel) {
        val favorite = !channel.favorite
        viewModelScope.launch {
            runCatching { repository.setFavorite(channel, favorite) }
                .onSuccess { updated ->
                    repository.refreshRoom()
                    mutableState.update { state ->
                        state.copy(
                            channels = state.channels.map { if (it.id == updated.id) it.copy(favorite = favorite) else it },
                            seriesEpisodes = state.seriesEpisodes.map {
                                if (it.id == updated.id && updated.id > 0) it.copy(favorite = favorite) else it
                            },
                        )
                    }
                    refreshHome()
                }
                .onFailure(::showError)
        }
    }

    fun savePlaybackProgress(channel: Channel, positionMs: Long, durationMs: Long) {
        viewModelScope.launch(Dispatchers.IO) {
            runCatching { repository.savePlaybackPosition(channel, positionMs, durationMs) }
            refreshHome()
        }
    }

    /** Next episode after [current] in the series being watched, if any. */
    fun nextEpisode(current: Channel): Channel? {
        val episodes = mutableState.value.episodeContext?.episodes ?: return null
        val index = episodes.indexOfFirst { sameEpisode(it, current) }
        return if (index >= 0) episodes.getOrNull(index + 1) else null
    }

    /** Queues the episode after [finished] in "Continuar a ver" when it isn't auto-played. */
    fun queueNextEpisode(finished: Channel) {
        val next = nextEpisode(finished) ?: return
        val parent = mutableState.value.episodeContext?.series?.takeIf { it.url.startsWith("catalog://") }
        viewModelScope.launch {
            runCatching { repository.recordPlayback(next, parent, upNext = true) }
            refreshHome()
        }
    }

    fun removeFromContinueWatching(item: WatchHistoryItem) {
        viewModelScope.launch {
            runCatching { repository.removeFromContinueWatching(item) }
            refreshHome()
        }
    }

    fun toggleReminder(channel: Channel, programme: EpgProgram) {
        viewModelScope.launch {
            runCatching {
                val existing = mutableState.value.reminders.firstOrNull {
                    it.tvgId == programme.channelId && it.startMillis == programme.startMillis
                }
                if (existing != null) {
                    repository.removeReminder(existing)
                } else {
                    repository.addReminder(
                        EpgReminder(channel, programme.channelId, programme.title, programme.startMillis, programme.stopMillis),
                    )
                }
                repository.reminders()
            }.onSuccess { reminders -> mutableState.update { it.copy(reminders = reminders) } }
                .onFailure(::showError)
        }
    }

    fun dismissDueReminder() = mutableState.update { it.copy(dueReminder = null) }

    private suspend fun checkDueReminders() {
        val now = System.currentTimeMillis()
        val reminders = runCatching { repository.reminders() }.getOrNull() ?: return
        val due = reminders.firstOrNull { reminder ->
            reminder.startMillis - REMINDER_LEAD_MS <= now && now < reminder.stopMillis &&
                notifiedReminders.add(reminder.tvgId to reminder.startMillis)
        }
        mutableState.update { it.copy(reminders = reminders, dueReminder = due ?: it.dueReminder) }
    }

    fun selectPlaylist(id: Long) {
        if (mutableState.value.playlists.firstOrNull { it.id == id }?.active == true) return
        mutableState.update { it.copy(loading = true, error = null) }
        launch {
            applyPlaylist(repository.selectPlaylist(id), repository.playlists())
        }
    }

    fun refreshPlaylist() {
        mutableState.update { it.copy(loading = true, error = null) }
        launch {
            applyPlaylist(repository.refresh(), repository.playlists())
        }
    }

    fun deletePlaylist(id: Long) {
        mutableState.update { it.copy(loading = true, error = null) }
        launch {
            applyPlaylist(repository.deletePlaylist(id), repository.playlists())
        }
    }

    fun importUrl(url: String) = import { repository.importUrl(url) }

    fun importXtream(server: String, username: String, password: String) = import {
        repository.importXtream(server, username, password)
    }

    fun importStalker(portal: String, macAddress: String) = import {
        repository.importStalker(portal, macAddress)
    }

    fun importDocument(uri: Uri) = import {
        repository.importDocument(getApplication<Application>().contentResolver, uri)
    }

    fun startPairing() {
        viewModelScope.launch {
            val exportData = runCatching { repository.exportDeviceSync() }.getOrDefault("")
            pairing.start(
                exportData = exportData,
                onPayload = { payload ->
                    import(successPairingMessage = "Dados recebidos com sucesso.") {
                        importPayload(payload)
                    }
                },
                onStatus = { status ->
                    mutableState.update {
                        it.copy(
                            pairingUrl = status.url,
                            pairingExpiresAtMillis = status.expiresAtMillis,
                            pairingMessage = status.message,
                            pairingPin = status.pin,
                            error = null,
                        )
                    }
                },
                onError = ::showError,
            )
        }
    }

    fun openSeries(channel: Channel) {
        mutableState.update {
            it.copy(
                seriesTitle = channel.name,
                seriesEpisodes = emptyList(),
                seriesLoading = true,
                selectedGroup = "Todos",
                openSeries = channel,
            )
        }
        viewModelScope.launch {
            runCatching { repository.loadSeriesEpisodes(channel) }
                .onSuccess { episodes ->
                    mutableState.update {
                        it.copy(
                            seriesEpisodes = episodes,
                            seriesLoading = false,
                            error = if (episodes.isEmpty()) "Esta série não tem episódios disponíveis." else null,
                        )
                    }
                }
                .onFailure {
                    mutableState.update { state -> state.copy(seriesLoading = false) }
                    showError(it)
                }
        }
    }

    fun closeSeries() = mutableState.update {
        it.copy(seriesTitle = null, seriesEpisodes = emptyList(), seriesLoading = false, selectedGroup = "Todos", openSeries = null)
    }

    /**
     * Resolves [channel] for playback and remembers it in the watch history. [parent] is the
     * series of an episode resumed from Início, whose episode list is then fetched so
     * "Próximo episódio" keeps working outside the series screen.
     */
    fun preparePlayback(
        channel: Channel,
        onReady: (Channel) -> Unit,
        onError: (String) -> Unit = {},
        parent: Channel? = null,
    ) {
        playbackJob?.cancel()
        mutableState.update { it.copy(loading = true, error = null) }
        playbackJob = viewModelScope.launch {
            try {
                val ready = repository.preparePlayback(channel)
                mutableState.update { it.copy(loading = false) }
                onReady(ready)
                if (!ready.url.startsWith("catalog://")) {
                    val seriesParent = updateEpisodeContext(channel, parent)
                    runCatching { repository.recordPlayback(channel, seriesParent) }
                    refreshHome()
                }
            } catch (_: CancellationException) {
                // A new zapping request superseded this one.
            } catch (error: Throwable) {
                val message = error.message ?: "Não foi possível abrir este conteúdo."
                showError(error)
                onError(message)
            }
        }
    }

    fun stopPairing() {
        pairing.stop()
        playbackJob?.cancel()
        mutableState.update {
            it.copy(pairingUrl = null, pairingExpiresAtMillis = 0, pairingMessage = null, pairingPin = null)
        }
    }

    private fun import(
        successPairingMessage: String? = null,
        block: suspend () -> pt.iptvplayer.tv.model.Playlist,
    ) {
        mutableState.update { it.copy(loading = true, error = null) }
        viewModelScope.launch {
            runCatching { block() }
                .onSuccess { playlist ->
                    requestedCatalogs.clear()
                    val pairingMessage = successPairingMessage ?: mutableState.value.pairingMessage
                    applyPlaylist(playlist, repository.playlists(), pairingMessage)
                }
                .onFailure { error ->
                    if (successPairingMessage != null) {
                        mutableState.update {
                            it.copy(
                                loading = false,
                                pairingMessage = "Não foi possível importar: ${error.message ?: "erro desconhecido"}",
                            )
                        }
                    } else {
                        showError(error)
                    }
                }
        }
    }

    private suspend fun importPayload(payload: PairingPayload): pt.iptvplayer.tv.model.Playlist =
        when (payload.type) {
            PairingSourceType.M3U -> repository.importUrl(payload.serverUrl)
            PairingSourceType.XTREAM -> repository.importXtream(payload.serverUrl, payload.username, payload.password)
            PairingSourceType.STALKER -> repository.importStalker(payload.serverUrl, payload.macAddress)
            PairingSourceType.SYNC -> repository.importDeviceSync(payload.syncData)
        }

    private fun applyPlaylist(
        playlist: pt.iptvplayer.tv.model.Playlist,
        playlists: List<PlaylistSummary>,
        pairingMessage: String? = mutableState.value.pairingMessage,
    ) {
        requestedCatalogs.clear()
        currentEpgUrl = playlist.epgUrl
        mutableState.update {
            it.copy(
                playlistName = playlist.name,
                channels = emptyList(),
                playlists = playlists,
                selectedType = StreamType.LIVE,
                selectedGroup = "Todos",
                query = "",
                loading = true,
                seriesTitle = null,
                seriesEpisodes = emptyList(),
                pairingMessage = pairingMessage,
                epg = emptyMap(),
                availableGroups = listOf("Todos"),
                totalChannels = 0,
                hasMoreChannels = false,
            )
        }
        loadCatalogPage(reset = true)
        refreshHome()
    }

    /** Returns the series [channel] is an episode of, keeping [CatalogUiState.episodeContext] in step. */
    private fun updateEpisodeContext(channel: Channel, explicitParent: Channel?): Channel? {
        val snapshot = mutableState.value
        if (channel.type != StreamType.SERIES) {
            mutableState.update { it.copy(episodeContext = null) }
            return null
        }
        val openSeries = snapshot.openSeries
        if (openSeries != null && snapshot.seriesEpisodes.any { sameEpisode(it, channel) }) {
            mutableState.update { it.copy(episodeContext = EpisodeContext(openSeries, snapshot.seriesEpisodes)) }
            return openSeries
        }
        val current = snapshot.episodeContext
        if (current != null && current.episodes.any { sameEpisode(it, channel) }) {
            return current.series.takeIf { it.url.startsWith("catalog://") }
        }
        if (explicitParent != null) {
            mutableState.update { it.copy(episodeContext = null) }
            viewModelScope.launch {
                runCatching { repository.loadSeriesEpisodes(explicitParent) }.onSuccess { episodes ->
                    if (episodes.any { sameEpisode(it, channel) }) {
                        mutableState.update { it.copy(episodeContext = EpisodeContext(explicitParent, episodes)) }
                    }
                }
            }
            return explicitParent
        }
        // Plain M3U series have no provider-side series object: their episodes are simply the
        // entries of the same group, which is also how the catalog lists them.
        val siblings = snapshot.guideChannels.ifEmpty { snapshot.channels }
            .filter { it.type == StreamType.SERIES && it.group == channel.group }
        mutableState.update {
            it.copy(
                episodeContext = if (siblings.size > 1) {
                    EpisodeContext(Channel(name = channel.group, url = "group://${channel.group}", type = StreamType.SERIES), siblings)
                } else {
                    null
                },
            )
        }
        return null
    }

    private fun sameEpisode(left: Channel, right: Channel): Boolean = when {
        left.tvgId.isNotBlank() && right.tvgId.isNotBlank() -> left.tvgId == right.tvgId
        left.id != 0L && right.id != 0L -> left.id == right.id
        else -> left.name == right.name && left.group == right.group
    }

    fun refreshHome() {
        viewModelScope.launch {
            runCatching {
                HomeRows(
                    favorites = repository.favorites(),
                    continueWatching = repository.continueWatching(),
                    recentLive = repository.recentLive(),
                    recentMovies = repository.recentlyAdded(StreamType.VOD),
                    recentSeries = repository.recentlyAdded(StreamType.SERIES),
                )
            }.onSuccess { rows ->
                mutableState.update {
                    it.copy(
                        homeFavorites = rows.favorites,
                        continueWatching = rows.continueWatching,
                        recentLive = rows.recentLive,
                        recentMovies = rows.recentMovies,
                        recentSeries = rows.recentSeries,
                    )
                }
                if (!startupChannelChecked) {
                    startupChannelChecked = true
                    if (preferences.settings.value.resumeLastChannelOnStart) {
                        rows.recentLive.firstOrNull()?.let { last -> mutableState.update { it.copy(startupChannel = last) } }
                    }
                }
            }
        }
    }

    private data class HomeRows(
        val favorites: List<Channel>,
        val continueWatching: List<WatchHistoryItem>,
        val recentLive: List<Channel>,
        val recentMovies: List<Channel>,
        val recentSeries: List<Channel>,
    )

    private fun loadCatalogPage(reset: Boolean, fetchProviderIfEmpty: Boolean = false) {
        catalogJob?.cancel()
        val snapshot = mutableState.value
        mutableState.update { it.copy(loading = true, error = null) }
        catalogJob = viewModelScope.launch {
            runCatching {
                var page = repository.observeCatalogPage(
                    snapshot.selectedType,
                    "Todos",
                    "",
                    Int.MAX_VALUE,
                ).first()
                if (
                    reset && page.total == 0 && fetchProviderIfEmpty &&
                    requestedCatalogs.add(snapshot.selectedType)
                ) {
                    repository.loadAdditionalCatalog(
                        snapshot.selectedType,
                        snapshot.playlistName,
                        emptyList(),
                    )
                    repository.refreshRoom()
                    page = repository.observeCatalogPage(
                        snapshot.selectedType,
                        "Todos",
                        "",
                        Int.MAX_VALUE,
                    ).first()
                }
                page
            }.onSuccess { page ->
                mutableState.update { state ->
                    state.copy(
                        channels = page.channels,
                        availableGroups = page.groups,
                        totalChannels = page.total,
                        hasMoreChannels = false,
                        loading = false,
                    )
                }
                if (reset && currentEpgUrl.isNotBlank() && page.channels.isNotEmpty()) {
                    refreshEpg(
                        pt.iptvplayer.tv.model.Playlist(
                            snapshot.playlistName,
                            page.channels,
                            currentEpgUrl,
                        ),
                    )
                }
            }.onFailure { error ->
                if (error !is CancellationException) showError(error)
            }
        }
    }

    private fun refreshEpg(playlist: pt.iptvplayer.tv.model.Playlist) {
        if (playlist.epgUrl.isBlank()) return
        mutableState.update { it.copy(epgLoading = true) }
        viewModelScope.launch {
            runCatching { repository.refreshEpg(playlist) }
                .onSuccess { epg -> mutableState.update { it.copy(epg = epg, epgLoading = false) } }
                .onFailure { mutableState.update { it.copy(epgLoading = false) } }
        }
    }

    private fun launch(block: suspend () -> Unit) = viewModelScope.launch {
        runCatching { block() }.onFailure { error ->
            if (error !is CancellationException) showError(error)
        }
    }

    private fun showError(error: Throwable) = mutableState.update {
        it.copy(loading = false, error = error.message ?: "Ocorreu um erro inesperado.")
    }

    /** Loaded whenever playback starts/zaps, so the in-player guide's "Todos" has every group to show. */
    fun loadGuideChannels(type: StreamType) {
        viewModelScope.launch {
            runCatching { repository.observeCatalogPage(type, "Todos", "", limit = Int.MAX_VALUE).first() }
                .onSuccess { page -> mutableState.update { it.copy(guideChannels = page.channels) } }
        }
    }

    /** Loaded on-demand when "Guia TV" opens — independent of whatever the catalog browser last filtered to. */
    fun loadLiveGuideChannels() {
        viewModelScope.launch {
            runCatching { repository.observeLiveGuideChannels().first() }
                .onSuccess { page -> mutableState.update { it.copy(liveGuideChannels = page.channels) } }
        }
    }

    fun loadEpgWindow(fromMillis: Long, toMillis: Long) {
        epgWindowJob?.cancel()
        mutableState.update { it.copy(epgWindowLoading = true) }
        epgWindowJob = viewModelScope.launch {
            runCatching { repository.observeEpgWindow(fromMillis, toMillis).first() }
                .onSuccess { window -> mutableState.update { it.copy(epgWindow = window, epgWindowLoading = false) } }
                .onFailure { mutableState.update { it.copy(epgWindowLoading = false) } }
        }
    }

    private companion object {
        /** Reminders fire a minute early so the channel is tuned before the programme starts. */
        const val REMINDER_LEAD_MS = 60_000L
    }

    override fun onCleared() {
        pairing.close()
        catalogJob?.cancel()
        epgWindowJob?.cancel()
        roomDatabase.close()
        super.onCleared()
    }
}
