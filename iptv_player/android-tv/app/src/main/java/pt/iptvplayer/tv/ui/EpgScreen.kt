package pt.iptvplayer.tv.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.focusable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.focus.onFocusChanged
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.tv.material3.Text
import kotlinx.coroutines.delay
import pt.iptvplayer.tv.CatalogUiState
import pt.iptvplayer.tv.model.Channel
import pt.iptvplayer.tv.model.EpgProgram
import java.util.Calendar

private const val MINUTE_MS = 60_000L
private const val WINDOW_BEFORE_MIN = 30L
private const val WINDOW_AFTER_MIN = 210L // 30 + 210 = 4h total, refreshed every minute
private const val MINUTE_WIDTH_DP = 6f
private val ChannelLabelWidth = 220.dp

/**
 * Live-only EPG timeline grid: channels as rows, a shared horizontal time axis, program
 * blocks sized by duration. Independent of the main catalog browser's filter/type — always
 * shows every LIVE channel, since VOD/Séries have no EPG data.
 */
@Composable
fun EpgScreen(
    state: CatalogUiState,
    onLoadChannels: () -> Unit,
    onLoadWindow: (fromMillis: Long, toMillis: Long) -> Unit,
    onPlay: (Channel) -> Unit,
) {
    var now by remember { mutableStateOf(System.currentTimeMillis()) }
    LaunchedEffect(Unit) { onLoadChannels() }
    LaunchedEffect(Unit) {
        while (true) {
            now = System.currentTimeMillis()
            val start = now - WINDOW_BEFORE_MIN * MINUTE_MS
            onLoadWindow(start, start + (WINDOW_BEFORE_MIN + WINDOW_AFTER_MIN) * MINUTE_MS)
            delay(60_000)
        }
    }
    val windowStart = now - WINDOW_BEFORE_MIN * MINUTE_MS
    val windowEnd = windowStart + (WINDOW_BEFORE_MIN + WINDOW_AFTER_MIN) * MINUTE_MS

    val categories = remember(state.liveGuideChannels) {
        listOf("Todos") + state.liveGuideChannels.asSequence()
            .map { it.group.ifBlank { "Geral" } }.distinct().sortedBy { it.lowercase() }.toList()
    }
    var selectedCategory by remember { mutableStateOf("Todos") }
    val filteredChannels = remember(state.liveGuideChannels, selectedCategory) {
        if (selectedCategory == "Todos") state.liveGuideChannels
        else state.liveGuideChannels.filter { it.group.ifBlank { "Geral" } == selectedCategory }
    }
    val ticks = remember(windowStart, windowEnd) {
        buildList {
            val cal = Calendar.getInstance().apply {
                timeInMillis = windowStart
                set(Calendar.MINUTE, (get(Calendar.MINUTE) / 30) * 30)
                set(Calendar.SECOND, 0)
                set(Calendar.MILLISECOND, 0)
            }
            while (cal.timeInMillis < windowEnd) {
                add(cal.timeInMillis)
                cal.add(Calendar.MINUTE, 30)
            }
        }
    }
    val timeScrollState = rememberScrollState()

    Column(Modifier.fillMaxSize()) {
        Text("Guia TV", color = Color.White, fontSize = 29.sp, fontWeight = FontWeight.Bold)
        Text("Programação ao vivo", color = Muted)
        Spacer(Modifier.height(18.dp))
        if (state.liveGuideChannels.isEmpty()) {
            StatusMessage(
                if (state.epgWindowLoading) "A carregar guia…" else "Não há canais em direto nesta lista.",
            )
            return@Column
        }
        Row(Modifier.fillMaxSize()) {
            GuideCategoryRail(categories, selectedCategory, onSelectCategory = { selectedCategory = it })
            Spacer(Modifier.width(14.dp))
            Column(Modifier.weight(1f).fillMaxHeight()) {
                Row(Modifier.fillMaxWidth().height(30.dp)) {
                    Spacer(Modifier.width(ChannelLabelWidth))
                    Spacer(Modifier.width(6.dp))
                    Box(Modifier.weight(1f).fillMaxHeight().horizontalScroll(timeScrollState)) {
                        Row {
                            ticks.forEach { tickMillis ->
                                Box(
                                    Modifier.width((30 * MINUTE_WIDTH_DP).dp).fillMaxHeight(),
                                    contentAlignment = Alignment.CenterStart,
                                ) {
                                    Text(formatClock(tickMillis), color = Muted, fontSize = 11.sp, fontWeight = FontWeight.SemiBold)
                                }
                            }
                        }
                        Box(
                            Modifier
                                .offset(x = minutesToDp(now - windowStart))
                                .width(2.dp)
                                .fillMaxHeight()
                                .background(Accent),
                        )
                    }
                }
                Spacer(Modifier.height(8.dp))
                LazyColumn(verticalArrangement = Arrangement.spacedBy(6.dp)) {
                    itemsIndexed(filteredChannels, key = { _, channel -> channel.id }) { _, channel ->
                        GuideChannelRow(
                            channel = channel,
                            programmes = state.epgWindow[channel.tvgId].orEmpty(),
                            windowStart = windowStart,
                            windowEnd = windowEnd,
                            scrollState = timeScrollState,
                            onPlay = onPlay,
                        )
                    }
                }
            }
        }
    }
}

@Composable
private fun GuideCategoryRail(categories: List<String>, selected: String, onSelectCategory: (String) -> Unit) {
    val listState = rememberLazyListState()
    LaunchedEffect(selected, categories.size) {
        val index = categories.indexOf(selected)
        if (index >= 0) listState.scrollToItem((index - 2).coerceAtLeast(0))
    }
    Column(
        Modifier.width(ChannelLabelWidth).fillMaxHeight().background(Panel, RoundedCornerShape(12.dp)).padding(10.dp),
    ) {
        Text("CATEGORIAS", color = Accent, fontSize = 11.sp, fontWeight = FontWeight.Bold)
        Spacer(Modifier.height(10.dp))
        LazyColumn(state = listState, verticalArrangement = Arrangement.spacedBy(5.dp)) {
            itemsIndexed(categories, key = { _, item -> item }) { _, category ->
                var focused by remember { mutableStateOf(false) }
                val isSelected = category == selected
                Box(
                    Modifier.fillMaxWidth()
                        .onFocusChanged { focused = it.isFocused }
                        .background(
                            when { focused -> Accent; isSelected -> Color(0xFF183B4D); else -> Color.Transparent },
                            RoundedCornerShape(8.dp),
                        )
                        .clickable { onSelectCategory(category) }
                        .focusable()
                        .padding(horizontal = 10.dp, vertical = 11.dp),
                ) {
                    Text(
                        category,
                        color = if (focused) Background else if (isSelected) Color.White else Muted,
                        fontWeight = if (isSelected) FontWeight.Bold else FontWeight.Normal,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                    )
                }
            }
        }
    }
}

private data class GuideBlock(val programme: EpgProgram?, val startMillis: Long, val stopMillis: Long)

@Composable
private fun GuideChannelRow(
    channel: Channel,
    programmes: List<EpgProgram>,
    windowStart: Long,
    windowEnd: Long,
    scrollState: androidx.compose.foundation.ScrollState,
    onPlay: (Channel) -> Unit,
) {
    // Gaps in the EPG data become blank filler blocks so every row's total width matches the
    // shared time axis exactly, regardless of missing programme data for parts of the window.
    val blocks = remember(programmes, windowStart, windowEnd) {
        buildList {
            var cursor = windowStart
            programmes.sortedBy { it.startMillis }.forEach { programme ->
                val start = programme.startMillis.coerceAtLeast(windowStart)
                val stop = programme.stopMillis.coerceAtMost(windowEnd)
                if (stop <= start) return@forEach
                if (start > cursor) add(GuideBlock(null, cursor, start))
                add(GuideBlock(programme, start, stop))
                cursor = stop
            }
            if (cursor < windowEnd) add(GuideBlock(null, cursor, windowEnd))
        }
    }
    Row(Modifier.fillMaxWidth().height(66.dp), verticalAlignment = Alignment.CenterVertically) {
        Row(
            Modifier.width(ChannelLabelWidth).fillMaxHeight().background(Panel, RoundedCornerShape(9.dp)).padding(10.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text(channel.name, color = Color.White, fontSize = 13.sp, fontWeight = FontWeight.SemiBold, maxLines = 1, overflow = TextOverflow.Ellipsis)
        }
        Spacer(Modifier.width(6.dp))
        Row(Modifier.weight(1f).fillMaxHeight().horizontalScroll(scrollState)) {
            blocks.forEach { block ->
                val widthDp = minutesToDp(block.stopMillis - block.startMillis)
                if (block.programme == null) {
                    Box(Modifier.width(widthDp).fillMaxHeight().padding(horizontal = 2.dp))
                } else {
                    var focused by remember { mutableStateOf(false) }
                    Box(
                        Modifier.width(widthDp).fillMaxHeight()
                            .padding(horizontal = 2.dp)
                            .onFocusChanged { focused = it.isFocused }
                            .background(if (focused) Accent else PanelFocused, RoundedCornerShape(7.dp))
                            .clickable { onPlay(channel) }
                            .focusable()
                            .padding(8.dp),
                    ) {
                        Text(
                            block.programme.title,
                            color = if (focused) Background else Color.White,
                            fontSize = 12.sp,
                            maxLines = 2,
                            overflow = TextOverflow.Ellipsis,
                        )
                    }
                }
            }
        }
    }
}

private fun minutesToDp(durationMillis: Long) =
    (durationMillis.coerceAtLeast(0) / MINUTE_MS.toFloat() * MINUTE_WIDTH_DP).dp

private fun formatClock(millis: Long): String {
    val calendar = Calendar.getInstance().apply { timeInMillis = millis }
    return "%02d:%02d".format(calendar.get(Calendar.HOUR_OF_DAY), calendar.get(Calendar.MINUTE))
}
