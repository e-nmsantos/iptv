package pt.iptvplayer.tv.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.itemsIndexed
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
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.window.Dialog
import androidx.tv.material3.Button
import androidx.tv.material3.Text
import kotlinx.coroutines.delay
import pt.iptvplayer.tv.data.OnlineSubtitle
import pt.iptvplayer.tv.data.OnlineSubtitlesClient

@Composable
fun TvOnlineSubtitleSearchDialog(
    queryTitle: String,
    onSelectSubtitle: (OnlineSubtitle) -> Unit,
    onDismiss: () -> Unit,
) {
    var loading by remember { mutableStateOf(true) }
    var subtitles by remember { mutableStateOf<List<OnlineSubtitle>>(emptyList()) }
    val initialRequester = remember { FocusRequester() }

    LaunchedEffect(queryTitle) {
        loading = true
        subtitles = OnlineSubtitlesClient.search(queryTitle)
        loading = false
        delay(100)
        runCatching { initialRequester.requestFocus() }
    }

    Dialog(onDismissRequest = onDismiss) {
        Column(
            Modifier
                .width(480.dp)
                .background(Color(0xFF10243A), RoundedCornerShape(16.dp))
                .padding(24.dp),
        ) {
            Text(
                "🔍 Legendas Online",
                color = Color.White,
                fontSize = 20.sp,
                fontWeight = FontWeight.Bold,
            )
            Text(
                queryTitle,
                color = Color(0xFFA6B4C4),
                fontSize = 13.sp,
                modifier = Modifier.padding(top = 2.dp, bottom = 12.dp),
            )

            if (loading) {
                Text(
                    "A pesquisar legendas online...",
                    color = Color(0xFF41D3BD),
                    fontSize = 14.sp,
                    modifier = Modifier.padding(vertical = 16.dp),
                )
            } else if (subtitles.isEmpty()) {
                Text(
                    "Nenhuma legenda encontrada para este título.",
                    color = Color(0xFFA6B4C4),
                    fontSize = 14.sp,
                    modifier = Modifier.padding(vertical = 16.dp),
                )
            } else {
                LazyColumn(
                    modifier = Modifier.heightIn(max = 300.dp),
                    verticalArrangement = Arrangement.spacedBy(6.dp),
                ) {
                    itemsIndexed(subtitles) { index, item ->
                        var isFocused by remember { mutableStateOf(false) }
                        val mod = if (index == 0) Modifier.focusRequester(initialRequester) else Modifier
                        Box(
                            mod
                                .fillMaxWidth()
                                .onFocusChanged { isFocused = it.isFocused }
                                .background(
                                    if (isFocused) Color(0xFF41D3BD) else Color(0xFF07111F),
                                    RoundedCornerShape(8.dp),
                                )
                                .clickable { onSelectSubtitle(item) }
                                .padding(horizontal = 14.dp, vertical = 10.dp),
                        ) {
                            Row(
                                modifier = Modifier.fillMaxWidth(),
                                horizontalArrangement = Arrangement.SpaceBetween,
                                verticalAlignment = Alignment.CenterVertically,
                            ) {
                                Text(
                                    item.releaseName,
                                    color = if (isFocused) Color.Black else Color.White,
                                    fontSize = 13.sp,
                                    fontWeight = FontWeight.Medium,
                                    modifier = Modifier.weight(1f),
                                )
                                Text(
                                    "[${item.language}]",
                                    color = if (isFocused) Color(0xFF05332A) else Color(0xFF41D3BD),
                                    fontSize = 12.sp,
                                    fontWeight = FontWeight.Bold,
                                    modifier = Modifier.padding(start = 8.dp),
                                )
                            }
                        }
                    }
                }
            }

            Spacer(Modifier.height(14.dp))
            Button(onClick = onDismiss, modifier = Modifier.align(Alignment.End)) {
                Text("Fechar")
            }
        }
    }
}

