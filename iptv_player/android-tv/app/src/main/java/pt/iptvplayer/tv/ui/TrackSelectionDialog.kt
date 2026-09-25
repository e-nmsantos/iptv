package pt.iptvplayer.tv.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.focusable
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

data class TrackItem(
    val id: String,
    val label: String,
    val isSelected: Boolean,
)

@Composable
fun TrackSelectionDialog(
    title: String,
    tracks: List<TrackItem>,
    onSelectTrack: (TrackItem) -> Unit,
    onDismiss: () -> Unit,
) {
    val initialRequester = remember { FocusRequester() }
    LaunchedEffect(Unit) {
        delay(100)
        runCatching { initialRequester.requestFocus() }
    }

    Dialog(onDismissRequest = onDismiss) {
        Column(
            Modifier
                .width(420.dp)
                .background(Color(0xFF10243A), RoundedCornerShape(16.dp))
                .padding(24.dp),
        ) {
            Text(
                title,
                color = Color.White,
                fontSize = 22.sp,
                fontWeight = FontWeight.Bold,
            )
            Spacer(Modifier.height(16.dp))

            if (tracks.isEmpty()) {
                Text(
                    "Nenhuma faixa disponível.",
                    color = Color(0xFFA6B4C4),
                    fontSize = 14.sp,
                    modifier = Modifier.padding(vertical = 12.dp),
                )
            } else {
                LazyColumn(
                    modifier = Modifier.heightIn(max = 320.dp),
                    verticalArrangement = Arrangement.spacedBy(6.dp),
                ) {
                    itemsIndexed(tracks) { index, item ->
                        var isFocused by remember { mutableStateOf(false) }
                        val mod = if (index == 0) Modifier.focusRequester(initialRequester) else Modifier
                        Box(
                            mod
                                .fillMaxWidth()
                                .onFocusChanged { isFocused = it.isFocused }
                                .background(
                                    when {
                                        isFocused -> Color(0xFF41D3BD)
                                        item.isSelected -> Color(0xFF193A52)
                                        else -> Color(0xFF07111F)
                                    },
                                    RoundedCornerShape(8.dp),
                                )
                                .clickable { onSelectTrack(item) }
                                .focusable()
                                .padding(horizontal = 16.dp, vertical = 12.dp),
                        ) {
                            Row(
                                modifier = Modifier.fillMaxWidth(),
                                horizontalArrangement = Arrangement.SpaceBetween,
                                verticalAlignment = Alignment.CenterVertically,
                            ) {
                                Text(
                                    item.label,
                                    color = if (isFocused) Color.Black else Color.White,
                                    fontWeight = if (item.isSelected) FontWeight.Bold else FontWeight.Normal,
                                    fontSize = 15.sp,
                                )
                                if (item.isSelected) {
                                    Text(
                                        "✓ Ativo",
                                        color = if (isFocused) Color(0xFF07111F) else Color(0xFF41D3BD),
                                        fontWeight = FontWeight.Bold,
                                        fontSize = 13.sp,
                                    )
                                }
                            }
                        }
                    }
                }
            }

            Spacer(Modifier.height(16.dp))
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.End) {
                Button(onClick = onDismiss) {
                    Text("Fechar")
                }
            }
        }
    }
}

