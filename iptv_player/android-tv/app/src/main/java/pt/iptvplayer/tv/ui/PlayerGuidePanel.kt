package pt.iptvplayer.tv.ui

import android.view.KeyEvent
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.focusable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.focus.onFocusChanged
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.input.key.onPreviewKeyEvent
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.tv.material3.Text
import coil3.compose.AsyncImage
import kotlinx.coroutines.delay
import pt.iptvplayer.tv.model.Channel

internal fun sameChannel(left: Channel, right: Channel): Boolean = when {
    left.id != 0L && right.id != 0L -> left.id == right.id
    left.tvgId.isNotBlank() && right.tvgId.isNotBlank() -> left.tvgId == right.tvgId
    else -> left.name == right.name && left.group == right.group
}

@Composable
internal fun ChannelGuide(
    channels: List<Channel>,
    current: Channel,
    selectedCategory: String,
    onSelectCategory: (String) -> Unit,
    onSelect: (Channel) -> Unit,
    onClose: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val categories = remember(channels) {
        listOf("Todos") + channels.asSequence().map { it.group.ifBlank { "Geral" } }
            .distinct().sortedBy { it.lowercase() }.toList()
    }
    val filteredChannels = remember(channels, selectedCategory) {
        if (selectedCategory == "Todos") channels else channels.filter { it.group == selectedCategory }
    }
    val currentIndex = filteredChannels.indexOfFirst { sameChannel(it, current) }.coerceAtLeast(0)
    val listState = rememberLazyListState()
    val categoryListState = rememberLazyListState()
    val currentRequester = remember { FocusRequester() }
    LaunchedEffect(selectedCategory, currentIndex, filteredChannels.size) {
        if (filteredChannels.isNotEmpty()) {
            listState.scrollToItem((currentIndex - 2).coerceAtLeast(0))
            delay(80)
            runCatching { currentRequester.requestFocus() }
        }
    }
    LaunchedEffect(selectedCategory, categories.size) {
        val selectedIndex = categories.indexOf(selectedCategory)
        if (selectedIndex >= 0) categoryListState.scrollToItem((selectedIndex - 2).coerceAtLeast(0))
    }
    Row(modifier.background(PlayerPanel)) {
        Column(
            Modifier.width(210.dp).fillMaxHeight().background(Color(0xFF071421)).padding(14.dp),
        ) {
            Text("CATEGORIAS", color = PlayerAccent, fontSize = 12.sp, fontWeight = FontWeight.Bold)
            Text("Botão vermelho: adicionar/remover favorito", color = PlayerMuted, fontSize = 11.sp)
            Spacer(Modifier.height(12.dp))
            LazyColumn(state = categoryListState, verticalArrangement = Arrangement.spacedBy(6.dp)) {
                itemsIndexed(categories, key = { _, item -> item }) { _, category ->
                    var focused by remember { mutableStateOf(false) }
                    val selected = selectedCategory == category
                    Box(
                        Modifier.fillMaxWidth()
                            .onFocusChanged { focused = it.isFocused }
                            .background(
                                when { focused -> PlayerFocused; selected -> Color(0xFF183B4D); else -> Color.Transparent },
                                RoundedCornerShape(9.dp),
                            )
                            .border(if (focused) 2.dp else 0.dp, PlayerAccent, RoundedCornerShape(9.dp))
                            .clickable { onSelectCategory(category) }.focusable()
                            .padding(horizontal = 12.dp, vertical = 13.dp),
                    ) {
                        Text(
                            category,
                            color = if (selected || focused) Color.White else PlayerMuted,
                            fontWeight = if (selected) FontWeight.Bold else FontWeight.Normal,
                            maxLines = 1,
                            overflow = TextOverflow.Ellipsis,
                        )
                    }
                }
            }
        }
        Column(Modifier.weight(1f).fillMaxHeight().padding(16.dp)) {
        Text("CANAIS", color = PlayerAccent, fontSize = 12.sp, fontWeight = FontWeight.Bold)
        Text(selectedCategory, color = Color.White, fontSize = 24.sp, fontWeight = FontWeight.Bold, maxLines = 1, overflow = TextOverflow.Ellipsis)
        Text("${filteredChannels.size} canais", color = PlayerMuted, fontSize = 13.sp)
        Spacer(Modifier.height(16.dp))
        if (filteredChannels.isEmpty()) {
            Text("Não há canais nesta categoria.", color = PlayerMuted)
        } else {
            LazyColumn(state = listState, verticalArrangement = Arrangement.spacedBy(7.dp)) {
                itemsIndexed(filteredChannels, key = { index, item -> "${item.id}:${item.tvgId}:$index" }) { index, item ->
                    val selected = sameChannel(item, current)
                    var focused by remember { mutableStateOf(false) }
                    Row(
                        Modifier.fillMaxWidth().height(72.dp)
                            .then(if (index == currentIndex) Modifier.focusRequester(currentRequester) else Modifier)
                            .onPreviewKeyEvent { event ->
                                if (
                                    event.nativeKeyEvent.action == KeyEvent.ACTION_DOWN &&
                                    event.nativeKeyEvent.keyCode == KeyEvent.KEYCODE_DPAD_RIGHT
                                ) {
                                    onClose()
                                    true
                                } else false
                            }
                            .onFocusChanged { focused = it.isFocused }
                            .background(
                                when { focused -> PlayerFocused; selected -> Color(0xFF183B4D); else -> Color.Transparent },
                                RoundedCornerShape(10.dp),
                            )
                            .border(if (focused) 2.dp else 0.dp, PlayerAccent, RoundedCornerShape(10.dp))
                            .clickable { onSelect(item) }.focusable().padding(horizontal = 10.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Box(
                            Modifier.size(48.dp).background(Color(0xFF07111F), RoundedCornerShape(8.dp)),
                            contentAlignment = Alignment.Center,
                        ) {
                            if (item.logo.isNotBlank()) AsyncImage(
                                model = item.logo,
                                contentDescription = null,
                                contentScale = ContentScale.Fit,
                                modifier = Modifier.fillMaxSize().padding(4.dp),
                            ) else Text(item.name.take(2).uppercase(), color = PlayerAccent, fontSize = 12.sp)
                        }
                        Spacer(Modifier.width(11.dp))
                        Column(Modifier.weight(1f)) {
                            Text(item.name, color = Color.White, maxLines = 1, overflow = TextOverflow.Ellipsis, fontWeight = if (selected) FontWeight.Bold else FontWeight.Normal)
                            Text(item.group, color = PlayerMuted, fontSize = 11.sp, maxLines = 1, overflow = TextOverflow.Ellipsis)
                        }
                        if (item.favorite) Text("★", color = PlayerAccent, fontSize = 15.sp)
                        if (selected) Text("●", color = PlayerAccent, fontSize = 12.sp)
                    }
                }
            }
        }
        }
    }
}
