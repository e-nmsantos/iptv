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
import kotlinx.coroutines.launch
import pt.iptvplayer.tv.data.CatalogDatabase
import pt.iptvplayer.tv.data.CatalogRepository
import pt.iptvplayer.tv.data.room.RoomCatalogDatabase
import pt.iptvplayer.tv.model.Channel
import pt.iptvplayer.tv.model.EpgProgram
import pt.iptvplayer.tv.model.PlaylistSummary
import pt.iptvplayer.tv.model.StreamType
import pt.iptvplayer.tv.pairing.PairingCoordinator
import pt.iptvplayer.tv.pairing.PairingPayload
import pt.iptvplayer.tv.pairing.PairingSourceType

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
)

class CatalogViewModel(application: Application) : AndroidViewModel(application) {
    private val roomDatabase = RoomCatalogDatabase.build(application)
    private val repository = CatalogRepository(CatalogDatabase(application), roomDatabase)
    private val pairing = PairingCoordinator(application, viewModelScope)
    private var playbackJob: Job? = null
    private var catalogJob: Job? = null
    private var currentEpgUrl: String = ""
    private val requestedCatalogs = mutableSetOf<StreamType>()
    private var loadedLimit = CatalogRepository.PAGE_SIZE
    private val mutableState = MutableStateFlow(CatalogUiState())
    val state: StateFlow<CatalogUiState> = mutableState.asStateFlow()

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
    }

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
    }

    fun loadNextCatalogPage() {
        if (!mutableState.value.hasMoreChannels) return
        loadedLimit += CatalogRepository.PAGE_SIZE
        loadCatalogPage(reset = false)
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
        }
    }

    fun selectPlaylist(id: Long) {
        if (mutableState.value.playlists.firstOrNull { it.id == id }?.active == true) return
        mutableState.update { it.copy(loading = true, error = null) }
        viewModelScope.launch {
            runCatching { repository.selectPlaylist(id) }
                .onSuccess { applyPlaylist(it, repository.playlists()) }
                .onFailure(::showError)
        }
    }

    fun refreshPlaylist() {
        mutableState.update { it.copy(loading = true, error = null) }
        viewModelScope.launch {
            runCatching { repository.refresh() }
                .onSuccess { applyPlaylist(it, repository.playlists()) }
                .onFailure(::showError)
        }
    }

    fun deletePlaylist(id: Long) {
        mutableState.update { it.copy(loading = true, error = null) }
        viewModelScope.launch {
            runCatching { repository.deletePlaylist(id) }
                .onSuccess { applyPlaylist(it, repository.playlists()) }
                .onFailure(::showError)
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
            it.copy(seriesTitle = channel.name, seriesEpisodes = emptyList(), seriesLoading = true, selectedGroup = "Todos")
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
        it.copy(seriesTitle = null, seriesEpisodes = emptyList(), seriesLoading = false, selectedGroup = "Todos")
    }

    fun preparePlayback(
        channel: Channel,
        onReady: (Channel) -> Unit,
        onError: (String) -> Unit = {},
    ) {
        playbackJob?.cancel()
        mutableState.update { it.copy(loading = true, error = null) }
        playbackJob = viewModelScope.launch {
            try {
                val ready = repository.preparePlayback(channel)
                mutableState.update { it.copy(loading = false) }
                onReady(ready)
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
            it.copy(pairingUrl = null, pairingExpiresAtMillis = 0, pairingMessage = null)
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

    private fun refreshHome() {
        viewModelScope.launch {
            runCatching { repository.favorites() }
                .onSuccess { favorites -> mutableState.update { it.copy(homeFavorites = favorites) } }
        }
    }

    private fun loadCatalogPage(reset: Boolean, fetchProviderIfEmpty: Boolean = false) {
        catalogJob?.cancel()
        val snapshot = mutableState.value
        if (reset) loadedLimit = CatalogRepository.PAGE_SIZE
        if (!reset && !snapshot.hasMoreChannels) return
        mutableState.update { it.copy(loading = true, error = null) }
        catalogJob = viewModelScope.launch {
            runCatching {
                var page = repository.observeCatalogPage(
                    snapshot.selectedType,
                    snapshot.selectedGroup,
                    snapshot.query,
                    loadedLimit,
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
                        snapshot.selectedGroup,
                        snapshot.query,
                        loadedLimit,
                    ).first()
                }
                page
            }.onSuccess { page ->
                mutableState.update { state ->
                    state.copy(
                        channels = page.channels,
                        availableGroups = page.groups,
                        totalChannels = page.total,
                        hasMoreChannels = page.hasMore,
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

    private fun showError(error: Throwable) = mutableState.update {
        it.copy(loading = false, error = error.message ?: "Ocorreu um erro inesperado.")
    }

    override fun onCleared() {
        pairing.close()
        catalogJob?.cancel()
        roomDatabase.close()
        super.onCleared()
    }
}
