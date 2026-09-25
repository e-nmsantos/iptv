package pt.iptvplayer.tv.ui

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.focusable
import androidx.compose.foundation.Image
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyListState
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.lazy.grid.GridCells
import androidx.compose.foundation.lazy.grid.GridItemSpan
import androidx.compose.foundation.lazy.grid.LazyGridState
import androidx.compose.foundation.lazy.grid.LazyVerticalGrid
import androidx.compose.foundation.lazy.grid.items
import androidx.compose.foundation.lazy.grid.itemsIndexed as gridItemsIndexed
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.produceState
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.focus.onFocusChanged
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.window.Dialog
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.tv.material3.Button
import androidx.tv.material3.MaterialTheme
import androidx.tv.material3.Text
import com.google.zxing.BarcodeFormat
import com.google.zxing.EncodeHintType
import com.google.zxing.qrcode.QRCodeWriter
import com.google.zxing.qrcode.decoder.ErrorCorrectionLevel
import kotlinx.coroutines.delay
import coil3.compose.AsyncImage
import pt.iptvplayer.tv.CatalogUiState
import pt.iptvplayer.tv.CatalogViewModel
import pt.iptvplayer.tv.model.Channel
import pt.iptvplayer.tv.model.PlaylistSummary
import pt.iptvplayer.tv.model.StreamType
import pt.iptvplayer.tv.model.projectCatalog

internal val Background = Color(0xFF07111F)
internal val Panel = Color(0xFF10243A)
internal val PanelFocused = Color(0xFF193A52)
internal val Accent = Color(0xFF41D3BD)
internal val Muted = Color(0xFFA6B4C4)
private enum class MainDestination { HOME, CATALOG, EPG, LISTS, ADD, DIAGNOSTICS }
internal enum class AddMethod { M3U_URL, XTREAM, STALKER }

@Composable
fun IptvTvApp(viewModel: CatalogViewModel, onPickDocument: () -> Unit) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    var playing by remember { mutableStateOf<Channel?>(null) }
    var playerNotice by remember { mutableStateOf<String?>(null) }
    // Lifted above the PlayerScreen/CatalogScreen toggle: CatalogScreen is fully disposed
    // while playing, so anything that must survive a play-then-back trip has to live here.
    var lastFocusedChannelId by remember { mutableStateOf<Long?>(null) }
    var destination by remember { mutableStateOf(MainDestination.HOME) }
    var viewAsList by remember { mutableStateOf(false) }
    val gridStateCache = remember { mutableMapOf<Any, LazyGridState>() }
    val listStateCache = remember { mutableMapOf<Any, LazyListState>() }
    MaterialTheme {
        if (playing != null) {
            // guideChannels holds every channel of the type currently playing (loaded fresh on
            // each play/zap below) — falls back to the catalog browser's own filtered list only
            // until that finishes loading, so the in-player guide's "Todos" always has every
            // group to show instead of just whichever one was selected before pressing play.
            val playbackChannels = remember(state.guideChannels, state.channels, playing!!.type) {
                state.guideChannels.filter { it.type == playing!!.type }
                    .ifEmpty { state.channels.filter { it.type == playing!!.type } }
            }
            PlayerScreen(
                channel = playing!!,
                channels = playbackChannels,
                notice = playerNotice,
                onToggleFavorite = { channel ->
                    viewModel.toggleFavorite(channel)
                    playing = playing?.copy(favorite = !channel.favorite)
                },
                onSaveProgress = viewModel::savePlaybackProgress,
                onSelectChannel = { candidate ->
                    lastFocusedChannelId = candidate.id
                    playerNotice = "A mudar para ${candidate.name}…"
                    viewModel.preparePlayback(
                        candidate,
                        onReady = { ready -> playerNotice = null; playing = ready; viewModel.loadGuideChannels(ready.type) },
                        onError = { playerNotice = it },
                    )
                },
                onBack = { playerNotice = null; playing = null },
            )
        } else {
            CatalogScreen(
                state = state,
                gridStateCache = gridStateCache,
                listStateCache = listStateCache,
                lastFocusedChannelId = lastFocusedChannelId,
                onFocusChannel = { id -> lastFocusedChannelId = id },
                onSelectType = viewModel::selectType,
                onSelectGroup = viewModel::selectGroup,
                onQuery = viewModel::setQuery,
                onImportUrl = viewModel::importUrl,
                onImportXtream = viewModel::importXtream,
                onImportStalker = viewModel::importStalker,
                onPickDocument = onPickDocument,
                onStartPairing = viewModel::startPairing,
                onStopPairing = viewModel::stopPairing,
                onCloseSeries = viewModel::closeSeries,
                onPlay = { channel ->
                    lastFocusedChannelId = channel.id
                    viewModel.preparePlayback(
                        channel,
                        onReady = { ready ->
                            if (ready.url.startsWith("catalog://")) {
                                viewModel.openSeries(ready)
                            } else {
                                playing = ready
                                viewModel.loadGuideChannels(ready.type)
                            }
                        },
                    )
                },
                onClearError = viewModel::clearError,
                onSelectPlaylist = viewModel::selectPlaylist,
                onRefreshPlaylist = viewModel::refreshPlaylist,
                onDeletePlaylist = viewModel::deletePlaylist,
                onLoadMore = viewModel::loadNextCatalogPage,
                onLoadLiveGuideChannels = viewModel::loadLiveGuideChannels,
                onLoadEpgWindow = viewModel::loadEpgWindow,
                destination = destination,
                onDestinationChange = { destination = it },
                viewAsList = viewAsList,
                onViewAsListChange = { viewAsList = it },
            )
        }
    }
}

@Composable
private fun CatalogScreen(
    state: CatalogUiState,
    gridStateCache: MutableMap<Any, LazyGridState>,
    listStateCache: MutableMap<Any, LazyListState>,
    lastFocusedChannelId: Long?,
    onFocusChannel: (Long) -> Unit,
    onSelectType: (StreamType) -> Unit,
    onSelectGroup: (String) -> Unit,
    onQuery: (String) -> Unit,
    onImportUrl: (String) -> Unit,
    onImportXtream: (String, String, String) -> Unit,
    onImportStalker: (String, String) -> Unit,
    onPickDocument: () -> Unit,
    onStartPairing: () -> Unit,
    onStopPairing: () -> Unit,
    onPlay: (Channel) -> Unit,
    onCloseSeries: () -> Unit,
    onClearError: () -> Unit,
    onSelectPlaylist: (Long) -> Unit,
    onRefreshPlaylist: () -> Unit,
    onDeletePlaylist: (Long) -> Unit,
    onLoadMore: () -> Unit,
    onLoadLiveGuideChannels: () -> Unit,
    onLoadEpgWindow: (Long, Long) -> Unit,
    destination: MainDestination,
    onDestinationChange: (MainDestination) -> Unit,
    viewAsList: Boolean,
    onViewAsListChange: (Boolean) -> Unit,
) {
    var showSearch by remember { mutableStateOf(false) }
    var showPairing by remember { mutableStateOf(false) }
    var addMethod by remember { mutableStateOf<AddMethod?>(null) }
    val projection = remember(
        state.channels,
        state.seriesEpisodes,
        state.seriesTitle,
        state.selectedType,
        state.selectedGroup,
        state.query,
    ) {
        projectCatalog(
            channels = state.channels,
            seriesEpisodes = state.seriesEpisodes,
            seriesOpen = state.seriesTitle != null,
            selectedType = state.selectedType,
            selectedGroup = state.selectedGroup,
            query = state.query,
        )
    }
    val firstGroupChipFocusRequester = remember { FocusRequester() }
    val newListFocusRequester = remember { FocusRequester() }
    val addSourceFocusRequester = remember { FocusRequester() }
    // Without an explicit request, moving focus from the sidebar into these screens relies
    // entirely on Compose's default 2D focus-search heuristics, which can fail to find a good
    // landing spot (reported as focus getting "stuck" on the sidebar, or needing many presses
    // to reach "Nova lista"). Mirrors the same fix already applied to the category row below.
    LaunchedEffect(destination, state.selectedType) {
        delay(80)
        when (destination) {
            MainDestination.CATALOG -> runCatching { firstGroupChipFocusRequester.requestFocus() }
            MainDestination.LISTS -> runCatching { newListFocusRequester.requestFocus() }
            MainDestination.ADD -> runCatching { addSourceFocusRequester.requestFocus() }
            else -> Unit
        }
    }
    BackHandler(enabled = state.seriesTitle != null, onBack = onCloseSeries)
    Row(Modifier.fillMaxSize().background(Background)) {
        NavigationSidebar(
            selected = state.selectedType,
            destination = destination,
            playlistName = state.playlistName,
            playlistCount = state.playlists.size,
            onHome = { onDestinationChange(MainDestination.HOME) },
            onEpg = { onDestinationChange(MainDestination.EPG) },
            onSelect = { onDestinationChange(MainDestination.CATALOG); onSelectType(it) },
            onSearch = { showSearch = true },
            onPlaylists = { onDestinationChange(MainDestination.LISTS) },
            onImport = { onDestinationChange(MainDestination.ADD) },
            onDiagnostics = { onDestinationChange(MainDestination.DIAGNOSTICS) },
        )
        Box(
            Modifier.width(1.dp).fillMaxHeight().background(
                Brush.verticalGradient(
                    listOf(Color.Transparent, Accent.copy(alpha = 0.35f), Color.Transparent),
                ),
            ),
        )
        Box(Modifier.weight(1f).fillMaxHeight().padding(start = 28.dp, top = 22.dp, end = 28.dp, bottom = 12.dp)) {
            when (destination) {
                MainDestination.HOME -> HomeScreen(
                    state = state,
                    onPlay = onPlay,
                )
                MainDestination.EPG -> EpgScreen(
                    state = state,
                    onLoadChannels = onLoadLiveGuideChannels,
                    onLoadWindow = onLoadEpgWindow,
                    onPlay = onPlay,
                )
                MainDestination.LISTS -> PlaylistManagerScreen(
                    playlists = state.playlists,
                    busy = state.loading,
                    onSelect = { onDestinationChange(MainDestination.CATALOG); onSelectPlaylist(it) },
                    onRefresh = onRefreshPlaylist,
                    onDelete = onDeletePlaylist,
                    onAdd = { onDestinationChange(MainDestination.ADD) },
                    focusRequester = newListFocusRequester,
                )
                MainDestination.ADD -> AddPlaylistScreen(
                    busy = state.loading,
                    onPhone = { showPairing = true; onStartPairing() },
                    onM3uUrl = { addMethod = AddMethod.M3U_URL },
                    onFile = onPickDocument,
                    onXtream = { addMethod = AddMethod.XTREAM },
                    onStalker = { addMethod = AddMethod.STALKER },
                    onViewLists = { onDestinationChange(MainDestination.LISTS) },
                    focusRequester = addSourceFocusRequester,
                )
                MainDestination.DIAGNOSTICS -> DiagnosticsScreen(state)
                MainDestination.CATALOG -> Column(Modifier.fillMaxSize()) {
                    Header(
                        sectionTitle = state.seriesTitle ?: typeLabel(state.selectedType),
                        groupLabel = if (state.seriesTitle == null) state.selectedGroup.takeIf { it != "Todos" } else null,
                        query = state.query,
                        count = if (state.seriesTitle != null) state.seriesEpisodes.size else projection.visibleChannels.size,
                        loading = state.loading,
                        onBack = if (state.seriesTitle != null) onCloseSeries else null,
                        viewAsList = viewAsList,
                        onToggleView = { onViewAsListChange(!viewAsList) },
                        onClearQuery = { onQuery("") },
                    )
                    Spacer(Modifier.height(18.dp))
                    GroupRow(
                        projection.groups,
                        state.selectedGroup,
                        onSelectGroup,
                        firstGroupChipFocusRequester,
                    )
                    Spacer(Modifier.height(18.dp))
                    // Keying the scroll-state cache by (type, group, query) — not just group —
                    // means switching filters always starts at the top, while coming back to a
                    // filter already visited (including after a play-then-back trip, since the
                    // cache map itself is lifted above the PlayerScreen/CatalogScreen toggle in
                    // IptvTvApp) restores exactly where the user left off.
                    val filterKey = Triple(state.selectedType, state.selectedGroup, state.query)
                    when {
                        state.seriesLoading -> StatusMessage("A carregar episódios…")
                        state.channels.isEmpty() && state.loading -> StatusMessage("A abrir o catálogo local…")
                        state.channels.isEmpty() -> EmptyCatalog(onImport = { onDestinationChange(MainDestination.ADD) })
                        projection.visibleChannels.isEmpty() -> StatusMessage("Não há conteúdos neste filtro.")
                        else -> if (viewAsList) {
                            ChannelList(
                                projection.visibleChannels,
                                state.epg.mapValues { it.value.firstOrNull() }.filterValues { it != null }.mapValues { it.value!! },
                                state.hasMoreChannels,
                                listStateCache.getOrPut(filterKey) { LazyListState() },
                                lastFocusedChannelId,
                                onLoadMore,
                                onPlay,
                                onFocusChannel,
                            )
                        } else {
                            ChannelGrid(
                                projection.visibleChannels,
                                state.epg.mapValues { it.value.firstOrNull() }.filterValues { it != null }.mapValues { it.value!! },
                                state.selectedType,
                                state.hasMoreChannels,
                                gridStateCache.getOrPut(filterKey) { LazyGridState() },
                                lastFocusedChannelId,
                                onLoadMore,
                                onPlay,
                                onFocusChannel,
                            )
                        }
                    }
                }
            }
        }
    }
    when (addMethod) {
        AddMethod.M3U_URL -> TextEntryDialog(
            title = "Endereço da lista M3U", initialValue = "", hint = "https://servidor/lista.m3u",
            onDismiss = { addMethod = null },
            onConfirm = { addMethod = null; onImportUrl(it) },
        )
        AddMethod.XTREAM -> XtreamDialog(
            onDismiss = { addMethod = null },
            onConfirm = { server, user, password -> addMethod = null; onImportXtream(server, user, password) },
        )
        AddMethod.STALKER -> StalkerDialog(
            onDismiss = { addMethod = null },
            onConfirm = { portal, mac -> addMethod = null; onImportStalker(portal, mac) },
        )
        null -> Unit
    }
    if (showPairing) {
        PairingDialog(
            url = state.pairingUrl,
            expiresAtMillis = state.pairingExpiresAtMillis,
            message = state.pairingMessage,
            onNewCode = onStartPairing,
            onDismiss = {
                showPairing = false
                onStopPairing()
            },
        )
    }
    if (showSearch) {
        TextEntryDialog(
            title = "Pesquisar catálogo",
            initialValue = state.query,
            hint = "Canal, filme, série ou categoria",
            onDismiss = { showSearch = false },
            onConfirm = {
                showSearch = false
                onDestinationChange(MainDestination.CATALOG)
                onQuery(it)
            },
        )
    }
    state.error?.let { message ->
        MessageDialog(message = message, onDismiss = onClearError)
    }
}

private fun typeLabel(type: StreamType): String = when (type) {
    StreamType.LIVE -> "Em direto"
    StreamType.VOD -> "Filmes"
    StreamType.SERIES -> "Séries"
}

@Composable
private fun Header(
    sectionTitle: String,
    groupLabel: String?,
    query: String = "",
    count: Int,
    loading: Boolean,
    onBack: (() -> Unit)? = null,
    viewAsList: Boolean,
    onToggleView: () -> Unit,
    onClearQuery: () -> Unit = {},
) {
    Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
        if (onBack != null) {
            Button(onClick = onBack) { Text("Voltar") }
            Spacer(Modifier.width(14.dp))
        }
        Column(Modifier.weight(1f)) {
            val titleText = when {
                query.isNotBlank() -> "$sectionTitle · Pesquisa: \"$query\""
                !groupLabel.isNullOrBlank() -> "$sectionTitle · $groupLabel"
                else -> sectionTitle
            }
            Text(
                titleText,
                color = Color.White,
                fontSize = 28.sp,
                fontWeight = FontWeight.Bold,
            )
            Text(
                "$count conteúdos" + if (loading) " · A atualizar…" else "",
                color = if (loading) Accent else Muted,
                fontSize = 14.sp,
            )
        }
        if (query.isNotBlank()) {
            Button(onClick = onClearQuery) {
                Text("✕ Limpar pesquisa")
            }
            Spacer(Modifier.width(10.dp))
        }
        Button(onClick = onToggleView) {
            Text(if (viewAsList) "Ver em grelha" else "Ver em lista")
        }
    }
}

@Composable
private fun NavigationSidebar(
    selected: StreamType,
    destination: MainDestination,
    playlistName: String,
    playlistCount: Int,
    onHome: () -> Unit,
    onEpg: () -> Unit,
    onSelect: (StreamType) -> Unit,
    onSearch: () -> Unit,
    onPlaylists: () -> Unit,
    onImport: () -> Unit,
    onDiagnostics: () -> Unit,
) {
    Column(
        Modifier.width(210.dp).fillMaxSize().background(Color(0xFF0B1929)).padding(22.dp),
    ) {
        Text("IPTV", color = Accent, fontSize = 13.sp, fontWeight = FontWeight.Bold)
        Text("PLAYER TV", color = Color.White, fontSize = 22.sp, fontWeight = FontWeight.Bold)
        Spacer(Modifier.height(18.dp))
        ActivePlaylistBadge(playlistName, playlistCount > 1, onPlaylists)
        Spacer(Modifier.height(20.dp))
        SidebarItem("⌂  Início", destination == MainDestination.HOME, onHome)
        SidebarItem("●  Em direto", destination == MainDestination.CATALOG && selected == StreamType.LIVE) { onSelect(StreamType.LIVE) }
        SidebarItem("▶  Filmes", destination == MainDestination.CATALOG && selected == StreamType.VOD) { onSelect(StreamType.VOD) }
        SidebarItem("▣  Séries", destination == MainDestination.CATALOG && selected == StreamType.SERIES) { onSelect(StreamType.SERIES) }
        SidebarItem("▤  Guia TV", destination == MainDestination.EPG, onEpg)
        Spacer(Modifier.height(14.dp))
        SidebarItem("☷  Listas", destination == MainDestination.LISTS, onPlaylists)
        Spacer(Modifier.weight(1f))
        SidebarItem("⌕  Pesquisar", false, onSearch)
        SidebarItem("＋  Adicionar", destination == MainDestination.ADD, onImport)
        SidebarItem("ℹ  Diagnóstico", destination == MainDestination.DIAGNOSTICS, onDiagnostics)
    }
}

@Composable
private fun SidebarItem(label: String, selected: Boolean, onClick: () -> Unit) {
    var focused by remember { mutableStateOf(false) }
    Box(
        Modifier.fillMaxWidth().padding(vertical = 4.dp)
            .graphicsLayer {
                scaleX = if (focused) 1.04f else 1f
                scaleY = if (focused) 1.04f else 1f
            }
            .background(
                when {
                    focused -> Accent
                    selected -> Color(0xFF183B4D)
                    else -> Color.Transparent
                },
                RoundedCornerShape(10.dp),
            )
            .onFocusChanged { focused = it.isFocused }
            .clickable(onClick = onClick)
            .focusable()
            .padding(horizontal = 14.dp, vertical = 13.dp),
    ) {
        Text(
            label,
            color = if (focused) Background else Color.White,
            fontWeight = if (selected || focused) FontWeight.Bold else FontWeight.Normal,
        )
    }
}

@Composable
private fun ActivePlaylistBadge(name: String, multipleAvailable: Boolean, onClick: () -> Unit) {
    var focused by remember { mutableStateOf(false) }
    Column(
        Modifier.fillMaxWidth()
            .background(if (focused) Accent else Panel, RoundedCornerShape(10.dp))
            .border(if (focused) 0.dp else 1.dp, Color(0xFF23445C), RoundedCornerShape(10.dp))
            .onFocusChanged { focused = it.isFocused }
            .clickable(onClick = onClick)
            .focusable()
            .padding(horizontal = 12.dp, vertical = 10.dp),
    ) {
        Text(
            "LISTA ATIVA",
            color = if (focused) Background else Muted,
            fontSize = 10.sp,
            fontWeight = FontWeight.Bold,
        )
        Text(
            name.ifBlank { "IPTV Player TV" },
            color = if (focused) Background else Color.White,
            fontSize = 14.sp,
            fontWeight = FontWeight.Bold,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
        )
        if (multipleAvailable) {
            Text(
                "Trocar lista",
                color = if (focused) Background else Accent,
                fontSize = 11.sp,
                fontWeight = FontWeight.SemiBold,
            )
        }
    }
}

@Composable
private fun HomeScreen(state: CatalogUiState, onPlay: (Channel) -> Unit) {
    // The active playlist's identity already lives permanently in the sidebar badge, so this
    // screen doesn't repeat it (that used to surface raw technical identifiers for some
    // sources, e.g. a Stalker portal's MAC address, as if it were a friendly greeting).
    val liveNow = remember(state.channels) { state.channels.filter { it.type == StreamType.LIVE }.take(20) }
    Column(Modifier.fillMaxSize()) {
        Text("Início", color = Color.White, fontSize = 30.sp, fontWeight = FontWeight.Bold)
        Spacer(Modifier.height(26.dp))
        Text("Favoritos", color = Color.White, fontSize = 22.sp, fontWeight = FontWeight.Bold)
        Spacer(Modifier.height(12.dp))
        if (state.homeFavorites.isEmpty()) {
            Box(
                Modifier.fillMaxWidth().height(84.dp).background(Panel, RoundedCornerShape(16.dp)).padding(horizontal = 22.dp),
                contentAlignment = Alignment.CenterStart,
            ) {
                Text(
                    "Marca os teus canais preferidos como favoritos durante a reprodução para os veres aqui.",
                    color = Muted,
                )
            }
        } else {
            LazyRow(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                items(state.homeFavorites, key = { it.id }) { channel ->
                    HomeChannelCard(channel, state.epg[channel.tvgId]?.firstOrNull(), onPlay)
                }
            }
        }
        if (liveNow.isNotEmpty()) {
            Spacer(Modifier.height(28.dp))
            Text("Em direto agora", color = Color.White, fontSize = 22.sp, fontWeight = FontWeight.Bold)
            Spacer(Modifier.height(12.dp))
            LazyRow(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                items(liveNow, key = { it.id }) { channel ->
                    HomeChannelCard(channel, state.epg[channel.tvgId]?.firstOrNull(), onPlay)
                }
            }
        }
    }
}

@Composable
private fun HomeChannelCard(
    channel: Channel,
    programme: pt.iptvplayer.tv.model.EpgProgram?,
    onPlay: (Channel) -> Unit,
) {
    var focused by remember { mutableStateOf(false) }
    Column(
        Modifier.width(245.dp).height(128.dp)
            .onFocusChanged { focused = it.isFocused }
            .background(if (focused) PanelFocused else Panel, RoundedCornerShape(14.dp))
            .border(if (focused) 3.dp else 0.dp, Accent, RoundedCornerShape(14.dp))
            .clickable { onPlay(channel) }.focusable().padding(16.dp),
    ) {
        Text(channel.name, color = Color.White, fontWeight = FontWeight.Bold, maxLines = 1)
        Spacer(Modifier.height(8.dp))
        Text(programme?.title ?: channel.group, color = if (programme == null) Muted else Accent, maxLines = 2)
    }
}

@Composable
private fun GroupRow(
    groups: List<String>,
    selected: String,
    onSelect: (String) -> Unit,
    firstChipFocusRequester: FocusRequester? = null,
) {
    LazyRow(horizontalArrangement = Arrangement.spacedBy(9.dp)) {
        itemsIndexed(groups, key = { _, item -> item }) { index, group ->
            FocusChip(
                group,
                selected == group,
                modifier = if (index == 0 && firstChipFocusRequester != null) {
                    Modifier.focusRequester(firstChipFocusRequester)
                } else {
                    Modifier
                },
            ) { onSelect(group) }
        }
    }
}

@Composable
private fun FocusChip(label: String, selected: Boolean, modifier: Modifier = Modifier, onClick: () -> Unit) {
    var focused by remember { mutableStateOf(false) }
    val color = when {
        focused -> Accent
        selected -> Color(0xFF245C68)
        else -> Panel
    }
    Box(
        modifier
            .onFocusChanged { focused = it.isFocused }
            .background(color, RoundedCornerShape(10.dp))
            .border(if (focused) 2.dp else 0.dp, Color.White, RoundedCornerShape(10.dp))
            .clickable(onClick = onClick)
            .focusable()
            .padding(horizontal = 18.dp, vertical = 10.dp),
    ) {
        Text(label, color = if (focused) Background else Color.White, fontWeight = FontWeight.SemiBold)
    }
}

// Restoring focus: a screen-entry effect (keyed on the hoisted `state` identity, which is
// only ever a fresh object per (filter, play-then-back) entry — see the filterKey-scoped
// cache in CatalogScreen) scrolls to and focuses whichever channel id was last focused
// *before* this filter/screen was left, rather than fighting the user's live scrolling by
// reacting to every subsequent focus change.
@Composable
private fun ChannelGrid(
    channels: List<Channel>,
    epg: Map<String, pt.iptvplayer.tv.model.EpgProgram>,
    type: StreamType,
    hasMore: Boolean,
    gridState: LazyGridState,
    initialFocusChannelId: Long?,
    onLoadMore: () -> Unit,
    onPlay: (Channel) -> Unit,
    onFocusChannel: (Long) -> Unit,
) {
    val restoreFocusId = remember(gridState) { initialFocusChannelId }
    val restoreIndex = remember(gridState, channels) {
        restoreFocusId?.let { id -> channels.indexOfFirst { it.id == id } } ?: -1
    }
    val restoreRequester = remember(gridState) { FocusRequester() }
    LaunchedEffect(gridState, channels.isNotEmpty()) {
        if (restoreIndex >= 0) {
            gridState.scrollToItem((restoreIndex - 4).coerceAtLeast(0))
            delay(80)
            runCatching { restoreRequester.requestFocus() }
        }
    }
    LazyVerticalGrid(
        state = gridState,
        columns = GridCells.Adaptive(if (type == StreamType.LIVE) 270.dp else 175.dp),
        horizontalArrangement = Arrangement.spacedBy(16.dp),
        verticalArrangement = Arrangement.spacedBy(18.dp),
        modifier = Modifier.padding(horizontal = 3.dp),
    ) {
        gridItemsIndexed(channels, key = { _, it -> "${it.id}:${it.url.hashCode()}" }) { index, channel ->
            val itemModifier = if (index == restoreIndex) Modifier.focusRequester(restoreRequester) else Modifier
            if (type == StreamType.LIVE) {
                LiveChannelCard(channel, epg[channel.tvgId]?.title.orEmpty(), onPlay, itemModifier, onFocusChannel)
            } else {
                PosterChannelCard(channel, onPlay, itemModifier, onFocusChannel)
            }
        }
        if (hasMore) {
            item(span = { GridItemSpan(maxLineSpan) }) {
                Button(onClick = onLoadMore, modifier = Modifier.fillMaxWidth()) {
                    Text("Carregar mais conteúdos")
                }
            }
        }
    }
}

@Composable
private fun ChannelList(
    channels: List<Channel>,
    epg: Map<String, pt.iptvplayer.tv.model.EpgProgram>,
    hasMore: Boolean,
    listState: LazyListState,
    initialFocusChannelId: Long?,
    onLoadMore: () -> Unit,
    onPlay: (Channel) -> Unit,
    onFocusChannel: (Long) -> Unit,
) {
    val restoreFocusId = remember(listState) { initialFocusChannelId }
    val restoreIndex = remember(listState, channels) {
        restoreFocusId?.let { id -> channels.indexOfFirst { it.id == id } } ?: -1
    }
    val restoreRequester = remember(listState) { FocusRequester() }
    LaunchedEffect(listState, channels.isNotEmpty()) {
        if (restoreIndex >= 0) {
            listState.scrollToItem((restoreIndex - 2).coerceAtLeast(0))
            delay(80)
            runCatching { restoreRequester.requestFocus() }
        }
    }
    LazyColumn(
        state = listState,
        verticalArrangement = Arrangement.spacedBy(8.dp),
        modifier = Modifier.padding(horizontal = 3.dp),
    ) {
        itemsIndexed(channels, key = { _, it -> "${it.id}:${it.url.hashCode()}" }) { index, channel ->
            val itemModifier = if (index == restoreIndex) Modifier.focusRequester(restoreRequester) else Modifier
            ChannelListItem(channel, epg[channel.tvgId]?.title.orEmpty(), onPlay, itemModifier, onFocusChannel)
        }
        if (hasMore) {
            item {
                Button(onClick = onLoadMore, modifier = Modifier.fillMaxWidth()) {
                    Text("Carregar mais conteúdos")
                }
            }
        }
    }
}

@Composable
private fun ChannelListItem(
    channel: Channel,
    currentProgram: String,
    onPlay: (Channel) -> Unit,
    modifier: Modifier = Modifier,
    onFocused: (Long) -> Unit = {},
) {
    var focused by remember { mutableStateOf(false) }
    Row(
        modifier
            .fillMaxWidth()
            .graphicsLayer {
                scaleX = if (focused) 1.02f else 1f
                scaleY = if (focused) 1.02f else 1f
            }
            .onFocusChanged { focused = it.isFocused; if (it.isFocused) onFocused(channel.id) }
            .background(if (focused) PanelFocused else Panel, RoundedCornerShape(13.dp))
            .border(if (focused) 2.dp else 0.dp, Accent, RoundedCornerShape(13.dp))
            .clickable { onPlay(channel) }
            .focusable()
            .padding(horizontal = 18.dp, vertical = 14.dp),
        verticalAlignment = Alignment.CenterVertically
    ) {
        Column(Modifier.weight(1f)) {
            Text(
                channel.name,
                color = Color.White,
                fontWeight = if (focused) FontWeight.Bold else FontWeight.Normal,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
            if (currentProgram.isNotBlank()) {
                Text(currentProgram, color = Muted, fontSize = 12.sp, maxLines = 1, overflow = TextOverflow.Ellipsis)
            }
        }
        if (channel.quality.isNotBlank()) {
            Spacer(Modifier.width(12.dp))
            Text(
                channel.quality,
                color = Accent,
                fontSize = 11.sp,
                fontWeight = FontWeight.Bold
            )
        }
        if (channel.favorite) {
            Spacer(Modifier.width(10.dp))
            Text("★", color = Accent, fontSize = 18.sp)
        }
    }
}

@Composable
private fun LiveChannelCard(
    channel: Channel,
    currentProgram: String,
    onPlay: (Channel) -> Unit,
    modifier: Modifier = Modifier,
    onFocused: (Long) -> Unit = {},
) {
    var focused by remember { mutableStateOf(false) }
    Row(
        modifier
            .height(96.dp)
            .graphicsLayer {
                scaleX = if (focused) 1.035f else 1f
                scaleY = if (focused) 1.035f else 1f
            }
            .onFocusChanged { focused = it.isFocused; if (it.isFocused) onFocused(channel.id) }
            .background(if (focused) PanelFocused else Panel, RoundedCornerShape(13.dp))
            .border(if (focused) 3.dp else 0.dp, Accent, RoundedCornerShape(13.dp))
            .clickable { onPlay(channel) }
            .focusable()
            .padding(13.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Box(
            Modifier.size(64.dp).background(Color(0xFF0A1624), RoundedCornerShape(10.dp)),
            contentAlignment = Alignment.Center,
        ) {
            if (channel.logo.isNotBlank()) {
                AsyncImage(
                    model = channel.logo,
                    contentDescription = null,
                    contentScale = ContentScale.Fit,
                    modifier = Modifier.fillMaxSize().padding(6.dp),
                )
            } else {
                Text(channel.name.take(2).uppercase(), color = Color.White, fontWeight = FontWeight.Bold)
            }
        }
        Spacer(Modifier.width(13.dp))
        Column(Modifier.weight(1f)) {
            Text(
                channel.name,
                color = Color.White,
                fontWeight = FontWeight.SemiBold,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
            Text(channel.group, color = Muted, fontSize = 12.sp, maxLines = 1, overflow = TextOverflow.Ellipsis)
            if (currentProgram.isNotBlank()) {
                Text(currentProgram, color = Accent, fontSize = 11.sp, maxLines = 1, overflow = TextOverflow.Ellipsis)
            }
        }
        if (channel.quality.isNotBlank()) {
            Text(channel.quality, color = Accent, fontSize = 11.sp, fontWeight = FontWeight.Bold)
        }
        if (channel.favorite) Text("★", color = Accent, fontSize = 18.sp)
    }
}

@Composable
private fun PosterChannelCard(
    channel: Channel,
    onPlay: (Channel) -> Unit,
    modifier: Modifier = Modifier,
    onFocused: (Long) -> Unit = {},
) {
    var focused by remember { mutableStateOf(false) }
    Column(
        modifier
            .graphicsLayer {
                scaleX = if (focused) 1.055f else 1f
                scaleY = if (focused) 1.055f else 1f
            }
            .onFocusChanged { focused = it.isFocused; if (it.isFocused) onFocused(channel.id) }
            .background(if (focused) PanelFocused else Panel, RoundedCornerShape(13.dp))
            .border(if (focused) 3.dp else 0.dp, Accent, RoundedCornerShape(13.dp))
            .clickable { onPlay(channel) }
            .focusable()
            .padding(7.dp),
    ) {
        Box(
            Modifier.fillMaxWidth().height(205.dp).background(Color(0xFF0A1624), RoundedCornerShape(9.dp)),
            contentAlignment = Alignment.Center,
        ) {
            if (channel.logo.isNotBlank()) {
                AsyncImage(
                    model = channel.logo,
                    contentDescription = null,
                    contentScale = ContentScale.Crop,
                    modifier = Modifier.fillMaxSize(),
                )
            } else {
                Text(channel.name.take(2).uppercase(), color = Accent, fontSize = 30.sp, fontWeight = FontWeight.Bold)
            }
            if (channel.quality.isNotBlank()) {
                Text(
                    channel.quality,
                    color = Background,
                    fontSize = 10.sp,
                    fontWeight = FontWeight.Bold,
                    modifier = Modifier.align(Alignment.TopEnd).background(Accent, RoundedCornerShape(5.dp)).padding(5.dp),
                )
            }
            if (channel.favorite) {
                Text(
                    "★",
                    color = Accent,
                    fontSize = 20.sp,
                    modifier = Modifier.align(Alignment.TopStart).padding(6.dp),
                )
            }
        }
        Text(
            channel.name,
            color = Color.White,
            fontWeight = FontWeight.SemiBold,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
            modifier = Modifier.padding(start = 5.dp, top = 9.dp, end = 5.dp),
        )
        Text(
            channel.group,
            color = Muted,
            fontSize = 11.sp,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
            modifier = Modifier.padding(horizontal = 5.dp, vertical = 3.dp),
        )
    }
}

@Composable
private fun EmptyCatalog(onImport: () -> Unit) {
    Column(
        Modifier.fillMaxSize(),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Center,
    ) {
        Text("A tua televisão está pronta.", color = Color.White, fontSize = 26.sp, fontWeight = FontWeight.Bold)
        Spacer(Modifier.height(8.dp))
        Text("Adiciona uma lista M3U por URL ou ficheiro.", color = Muted)
        Spacer(Modifier.height(20.dp))
        Button(onClick = onImport) { Text("Adicionar primeira lista") }
    }
}

@Composable
internal fun StatusMessage(message: String) {
    Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
        Text(message, color = Muted, fontSize = 20.sp)
    }
}

@Composable
private fun PlaylistManagerScreen(
    playlists: List<PlaylistSummary>,
    busy: Boolean,
    onSelect: (Long) -> Unit,
    onRefresh: () -> Unit,
    onDelete: (Long) -> Unit,
    onAdd: () -> Unit,
    focusRequester: FocusRequester? = null,
) {
    var pendingDelete by remember { mutableStateOf<PlaylistSummary?>(null) }
    Column(Modifier.fillMaxSize()) {
        Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Text("As minhas listas", color = Color.White, fontSize = 29.sp, fontWeight = FontWeight.Bold)
                Text("Escolhe uma lista guardada ou atualiza apenas quando precisares.", color = Muted)
            }
            Button(
                onClick = onAdd,
                modifier = if (focusRequester != null) Modifier.focusRequester(focusRequester) else Modifier,
            ) { Text("＋ Nova lista") }
        }
        Spacer(Modifier.height(22.dp))
        if (busy) {
            Text("A processar… Podes continuar neste ecrã.", color = Accent, fontWeight = FontWeight.SemiBold)
            Spacer(Modifier.height(12.dp))
        }
        if (playlists.isEmpty()) {
            Column(
                Modifier.fillMaxSize().background(Panel, RoundedCornerShape(16.dp)),
                horizontalAlignment = Alignment.CenterHorizontally,
                verticalArrangement = Arrangement.Center,
            ) {
                Text("Ainda não existem listas guardadas", color = Color.White, fontSize = 22.sp)
                Spacer(Modifier.height(8.dp))
                Text("Adiciona M3U, Xtream Codes ou Stalker Portal.", color = Muted)
                Spacer(Modifier.height(18.dp))
                Button(onClick = onAdd) { Text("Adicionar lista") }
            }
        } else {
            LazyColumn(verticalArrangement = Arrangement.spacedBy(12.dp)) {
                items(playlists, key = { it.id }) { playlist ->
                    Row(
                        Modifier.fillMaxWidth()
                            .background(if (playlist.active) Color(0xFF183B4D) else Panel, RoundedCornerShape(14.dp))
                            .border(if (playlist.active) 2.dp else 0.dp, Accent, RoundedCornerShape(14.dp))
                            .padding(18.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Box(
                            Modifier.size(54.dp).background(Background, RoundedCornerShape(12.dp)),
                            contentAlignment = Alignment.Center,
                        ) { Text(playlist.sourceLabel.take(1), color = Accent, fontSize = 22.sp, fontWeight = FontWeight.Bold) }
                        Spacer(Modifier.width(16.dp))
                        Column(Modifier.weight(1f)) {
                            Text(playlist.name, color = Color.White, fontSize = 19.sp, fontWeight = FontWeight.Bold)
                            Text(
                                "${playlist.sourceLabel}  •  ${playlist.channelCount} conteúdos" + if (playlist.active) "  •  ATIVA" else "",
                                color = if (playlist.active) Accent else Muted,
                            )
                        }
                        if (playlist.active) Button(onClick = onRefresh, enabled = !busy) { Text("Atualizar") }
                        else Button(onClick = { onSelect(playlist.id) }, enabled = !busy) { Text("Abrir") }
                        Spacer(Modifier.width(10.dp))
                        Button(onClick = { pendingDelete = playlist }, enabled = !busy) { Text("Remover") }
                    }
                }
            }
        }
    }
    pendingDelete?.let { playlist ->
        Dialog(onDismissRequest = { pendingDelete = null }) {
            DialogPanel {
                Text("Remover lista?", color = Color.White, fontSize = 22.sp, fontWeight = FontWeight.Bold)
                Spacer(Modifier.height(10.dp))
                Text("${playlist.name} será removida desta televisão.", color = Muted)
                Spacer(Modifier.height(18.dp))
                Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                    Button(onClick = { pendingDelete = null; onDelete(playlist.id) }) { Text("Remover") }
                    Button(onClick = { pendingDelete = null }) { Text("Cancelar") }
                }
            }
        }
    }
}

@Composable
private fun AddPlaylistScreen(
    busy: Boolean,
    onPhone: () -> Unit,
    onM3uUrl: () -> Unit,
    onFile: () -> Unit,
    onXtream: () -> Unit,
    onStalker: () -> Unit,
    onViewLists: () -> Unit,
    focusRequester: FocusRequester? = null,
) {
    Column(Modifier.fillMaxSize()) {
        Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Text("Adicionar uma lista", color = Color.White, fontSize = 29.sp, fontWeight = FontWeight.Bold)
                Text("Escolhe como queres ligar. Os dados ficam guardados nesta televisão.", color = Muted)
            }
            Button(onClick = onViewLists) { Text("Ver listas") }
        }
        Spacer(Modifier.height(22.dp))
        if (busy) {
            Box(
                Modifier.fillMaxWidth().background(Color(0xFF183B4D), RoundedCornerShape(12.dp)).padding(16.dp),
            ) { Text("A validar, importar e guardar a lista…", color = Accent, fontWeight = FontWeight.Bold) }
            Spacer(Modifier.height(14.dp))
        }
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(14.dp)) {
            AddSourceCard(
                "▦", "Telemóvel por QR", "A forma mais simples: introduz os dados no telemóvel.", !busy, onPhone,
                if (focusRequester != null) Modifier.weight(1f).focusRequester(focusRequester) else Modifier.weight(1f),
            )
            AddSourceCard("XC", "Xtream Codes", "Servidor, utilizador e palavra-passe.", !busy, onXtream, Modifier.weight(1f))
        }
        Spacer(Modifier.height(14.dp))
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(14.dp)) {
            AddSourceCard("MAC", "Stalker Portal", "Portal e endereço MAC do dispositivo.", !busy, onStalker, Modifier.weight(1f))
            AddSourceCard("URL", "Endereço M3U", "Liga diretamente a uma lista M3U ou M3U8.", !busy, onM3uUrl, Modifier.weight(1f))
        }
        Spacer(Modifier.height(14.dp))
        Row(Modifier.fillMaxWidth()) {
            AddSourceCard("FILE", "Ficheiro M3U", "Abre um ficheiro guardado localmente.", !busy, onFile, Modifier.weight(1f))
            Spacer(Modifier.weight(1f).padding(start = 14.dp))
        }
    }
}

@Composable
private fun AddSourceCard(
    icon: String,
    title: String,
    description: String,
    enabled: Boolean,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
) {
    var focused by remember { mutableStateOf(false) }
    Row(
        modifier.height(126.dp)
            .graphicsLayer { scaleX = if (focused) 1.025f else 1f; scaleY = if (focused) 1.025f else 1f }
            .onFocusChanged { focused = it.isFocused }
            .background(if (focused) PanelFocused else Panel, RoundedCornerShape(15.dp))
            .border(if (focused) 3.dp else 0.dp, Accent, RoundedCornerShape(15.dp))
            .clickable(enabled = enabled, onClick = onClick).focusable(enabled)
            .padding(18.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Box(Modifier.size(58.dp).background(Background, RoundedCornerShape(12.dp)), contentAlignment = Alignment.Center) {
            Text(icon, color = Accent, fontWeight = FontWeight.Bold)
        }
        Spacer(Modifier.width(16.dp))
        Column {
            Text(title, color = Color.White, fontSize = 19.sp, fontWeight = FontWeight.Bold)
            Spacer(Modifier.height(4.dp))
            Text(description, color = Muted, fontSize = 13.sp, maxLines = 2)
        }
    }
}
