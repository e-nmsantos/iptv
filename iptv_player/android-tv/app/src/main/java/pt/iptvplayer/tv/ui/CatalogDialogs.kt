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
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.grid.GridCells
import androidx.compose.foundation.lazy.grid.GridItemSpan
import androidx.compose.foundation.lazy.grid.LazyVerticalGrid
import androidx.compose.foundation.lazy.grid.items
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

@Composable
private fun PlaylistsDialog(
    playlists: List<PlaylistSummary>,
    onSelect: (Long) -> Unit,
    onRefresh: () -> Unit,
    onDelete: (Long) -> Unit,
    onAdd: () -> Unit,
    onDismiss: () -> Unit,
) {
    var pendingDelete by remember { mutableStateOf<PlaylistSummary?>(null) }
    pendingDelete?.let { playlist ->
        Dialog(onDismissRequest = { pendingDelete = null }) {
            DialogPanel {
                Text("Remover lista?", color = Color.White, fontSize = 22.sp, fontWeight = FontWeight.Bold)
                Spacer(Modifier.height(10.dp))
                Text("${playlist.name} será removida desta televisão.", color = Muted)
                Spacer(Modifier.height(18.dp))
                Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                    Button(onClick = { onDelete(playlist.id) }) { Text("Remover") }
                    Button(onClick = { pendingDelete = null }) { Text("Cancelar") }
                }
            }
        }
        return
    }
    Dialog(onDismissRequest = onDismiss) {
        Column(
            Modifier.width(680.dp).height(590.dp).background(Panel, RoundedCornerShape(16.dp)).padding(24.dp),
        ) {
            Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                Column(Modifier.weight(1f)) {
                    Text("As minhas listas", color = Color.White, fontSize = 25.sp, fontWeight = FontWeight.Bold)
                    Text("Escolhe o catálogo que queres usar", color = Muted)
                }
                Button(onClick = onAdd) { Text("＋ Adicionar") }
            }
            Spacer(Modifier.height(18.dp))
            if (playlists.isEmpty()) {
                Box(Modifier.weight(1f).fillMaxWidth(), contentAlignment = Alignment.Center) {
                    Text("Ainda não adicionaste nenhuma lista.", color = Muted)
                }
            } else {
                LazyColumn(
                    modifier = Modifier.weight(1f).fillMaxWidth(),
                    verticalArrangement = Arrangement.spacedBy(10.dp),
                ) {
                    items(playlists, key = { it.id }) { playlist ->
                        Column(
                            Modifier.fillMaxWidth()
                                .background(if (playlist.active) Color(0xFF183B4D) else Background, RoundedCornerShape(12.dp))
                                .border(if (playlist.active) 2.dp else 0.dp, Accent, RoundedCornerShape(12.dp))
                                .padding(16.dp),
                        ) {
                            Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                                Column(Modifier.weight(1f)) {
                                    Text(playlist.name, color = Color.White, fontWeight = FontWeight.Bold, fontSize = 18.sp)
                                    Text(
                                        "${playlist.sourceLabel}  •  ${playlist.channelCount} conteúdos" +
                                            if (playlist.active) "  •  ATIVA" else "",
                                        color = if (playlist.active) Accent else Muted,
                                        fontSize = 13.sp,
                                    )
                                }
                                if (!playlist.active) {
                                    Button(onClick = { onSelect(playlist.id) }) { Text("Abrir") }
                                    Spacer(Modifier.width(8.dp))
                                } else {
                                    Button(onClick = onRefresh) { Text("Atualizar") }
                                    Spacer(Modifier.width(8.dp))
                                }
                                Button(onClick = { pendingDelete = playlist }) { Text("Remover") }
                            }
                        }
                    }
                }
            }
            Spacer(Modifier.height(12.dp))
            Button(onClick = onDismiss, modifier = Modifier.fillMaxWidth()) { Text("Fechar") }
        }
    }
}

@Composable
private fun ImportDialog(
    onDismiss: () -> Unit,
    onUrl: (String) -> Unit,
    onXtream: (String, String, String) -> Unit,
    onStalker: (String, String) -> Unit,
    onFile: () -> Unit,
    onPhone: () -> Unit,
) {
    var enterUrl by remember { mutableStateOf(false) }
    var enterXtream by remember { mutableStateOf(false) }
    var enterStalker by remember { mutableStateOf(false) }
    if (enterUrl) {
        TextEntryDialog(
            title = "Endereço da lista M3U",
            initialValue = "",
            hint = "https://servidor/lista.m3u",
            onDismiss = onDismiss,
            onConfirm = onUrl,
        )
        return
    }
    if (enterXtream) {
        XtreamDialog(onDismiss = onDismiss, onConfirm = onXtream)
        return
    }
    if (enterStalker) {
        StalkerDialog(onDismiss = onDismiss, onConfirm = onStalker)
        return
    }
    Dialog(onDismissRequest = onDismiss) {
        DialogPanel {
            Text("Adicionar lista", color = Color.White, fontSize = 23.sp, fontWeight = FontWeight.Bold)
            Spacer(Modifier.height(18.dp))
            Button(onClick = onPhone, modifier = Modifier.fillMaxWidth()) { Text("Enviar pelo telemóvel (QR)") }
            Spacer(Modifier.height(10.dp))
            Button(onClick = { enterUrl = true }, modifier = Modifier.fillMaxWidth()) { Text("M3U por endereço URL") }
            Spacer(Modifier.height(10.dp))
            Button(onClick = onFile, modifier = Modifier.fillMaxWidth()) { Text("Abrir ficheiro M3U") }
            Spacer(Modifier.height(10.dp))
            Button(onClick = { enterXtream = true }, modifier = Modifier.fillMaxWidth()) { Text("Xtream Codes") }
            Spacer(Modifier.height(10.dp))
            Button(onClick = { enterStalker = true }, modifier = Modifier.fillMaxWidth()) { Text("Stalker Portal (MAC)") }
            Spacer(Modifier.height(10.dp))
            Button(onClick = onDismiss, modifier = Modifier.fillMaxWidth()) { Text("Cancelar") }
        }
    }
}

@Composable
internal fun XtreamDialog(onDismiss: () -> Unit, onConfirm: (String, String, String) -> Unit) {
    var server by remember { mutableStateOf("") }
    var username by remember { mutableStateOf("") }
    var password by remember { mutableStateOf("") }
    Dialog(onDismissRequest = onDismiss) {
        DialogPanel {
            Text("Xtream Codes", color = Color.White, fontSize = 22.sp, fontWeight = FontWeight.Bold)
            Spacer(Modifier.height(12.dp))
            LabeledInput("Servidor", "http://servidor:porta", server) { server = it }
            LabeledInput("Utilizador", "Utilizador", username) { username = it }
            LabeledInput("Palavra-passe", "Palavra-passe", password, password = true) { password = it }
            if (server.trim().startsWith("http://", ignoreCase = true)) {
                Text(
                    "Aviso: HTTP envia o utilizador e a palavra-passe sem proteção de transporte.",
                    color = Color(0xFFFFB36B),
                    fontSize = 13.sp,
                )
                Spacer(Modifier.height(8.dp))
            }
            Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                Button(onClick = {
                    if (server.isNotBlank() && username.isNotBlank() && password.isNotBlank()) {
                        onConfirm(server.trim(), username.trim(), password)
                    }
                }) { Text("Ligar") }
                Button(onClick = onDismiss) { Text("Cancelar") }
            }
        }
    }
}

@Composable
internal fun StalkerDialog(onDismiss: () -> Unit, onConfirm: (String, String) -> Unit) {
    var portal by remember { mutableStateOf("") }
    var mac by remember { mutableStateOf("") }
    Dialog(onDismissRequest = onDismiss) {
        DialogPanel {
            Text("Stalker Portal", color = Color.White, fontSize = 22.sp, fontWeight = FontWeight.Bold)
            Spacer(Modifier.height(12.dp))
            LabeledInput("Portal", "http://servidor:porta/c/", portal) { portal = it }
            LabeledInput("Endereço MAC", "00:1A:79:00:00:00", mac) { mac = it }
            if (portal.isNotBlank() && !portal.trim().startsWith("https://", ignoreCase = true)) {
                Text(
                    "Aviso: este endereço será usado por HTTP; o MAC e a sessão podem ser intercetados.",
                    color = Color(0xFFFFB36B),
                    fontSize = 13.sp,
                )
                Spacer(Modifier.height(8.dp))
            }
            Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                Button(onClick = {
                    if (portal.isNotBlank() && mac.isNotBlank()) onConfirm(portal.trim(), mac.trim())
                }) { Text("Ligar") }
                Button(onClick = onDismiss) { Text("Cancelar") }
            }
        }
    }
}

@Composable
private fun LabeledInput(
    label: String,
    hint: String,
    value: String,
    password: Boolean = false,
    onValueChange: (String) -> Unit,
) {
    Text(label, color = Muted, fontSize = 14.sp)
    Spacer(Modifier.height(5.dp))
    Box(Modifier.fillMaxWidth().background(Color.White, RoundedCornerShape(8.dp)).padding(12.dp)) {
        if (value.isBlank()) Text(hint, color = Color.Gray)
        BasicTextField(
            value = value,
            onValueChange = onValueChange,
            singleLine = true,
            visualTransformation = if (password) PasswordVisualTransformation() else androidx.compose.ui.text.input.VisualTransformation.None,
            textStyle = androidx.compose.ui.text.TextStyle(color = Background, fontSize = 16.sp),
            cursorBrush = Brush.verticalGradient(listOf(Accent, Accent)),
            modifier = Modifier.fillMaxWidth(),
        )
    }
    Spacer(Modifier.height(11.dp))
}

@Composable
internal fun PairingDialog(
    url: String?,
    expiresAtMillis: Long,
    message: String?,
    onNewCode: () -> Unit,
    onDismiss: () -> Unit,
) {
    val secondsLeft by produceState(0L, expiresAtMillis) {
        while (expiresAtMillis > 0) {
            value = ((expiresAtMillis - System.currentTimeMillis()) / 1000).coerceAtLeast(0)
            if (value == 0L) break
            delay(1_000)
        }
    }
    Dialog(onDismissRequest = onDismiss) {
        DialogPanel {
            Text("Enviar pelo telemóvel", color = Color.White, fontSize = 23.sp, fontWeight = FontWeight.Bold)
            Spacer(Modifier.height(10.dp))
            when {
                url != null -> {
                    Text("Lê o código com a câmara do telemóvel ligado à mesma rede.", color = Muted)
                    Spacer(Modifier.height(14.dp))
                    Box(
                        Modifier.fillMaxWidth(),
                        contentAlignment = Alignment.Center,
                    ) {
                        Image(
                            bitmap = rememberQrBitmap(url),
                            contentDescription = "QR code de emparelhamento",
                            modifier = Modifier.size(270.dp).background(Color.White).padding(10.dp),
                        )
                    }
                    Spacer(Modifier.height(10.dp))
                    Text("Válido durante ${secondsLeft / 60}:${(secondsLeft % 60).toString().padStart(2, '0')}", color = Accent)
                    Text("Usa uma rede doméstica de confiança.", color = Muted, fontSize = 13.sp)
                }
                message != null -> {
                    Text(message, color = if (message.contains("sucesso")) Accent else Muted, fontSize = 18.sp)
                    Spacer(Modifier.height(14.dp))
                    if (!message.contains("sucesso")) {
                        Button(onClick = onNewCode, modifier = Modifier.fillMaxWidth()) { Text("Criar novo código") }
                        Spacer(Modifier.height(10.dp))
                    }
                }
                else -> Text("A preparar ligação local…", color = Muted)
            }
            Button(onClick = onDismiss, modifier = Modifier.fillMaxWidth()) { Text("Fechar") }
        }
    }
}

@Composable
private fun rememberQrBitmap(content: String): androidx.compose.ui.graphics.ImageBitmap = remember(content) {
    val matrix = QRCodeWriter().encode(
        content,
        BarcodeFormat.QR_CODE,
        512,
        512,
        mapOf(
            EncodeHintType.MARGIN to 1,
            EncodeHintType.ERROR_CORRECTION to ErrorCorrectionLevel.M,
            EncodeHintType.CHARACTER_SET to "UTF-8",
        ),
    )
    val pixels = IntArray(matrix.width * matrix.height) { index ->
        val x = index % matrix.width
        val y = index / matrix.width
        if (matrix[x, y]) android.graphics.Color.BLACK else android.graphics.Color.WHITE
    }
    android.graphics.Bitmap.createBitmap(
        pixels,
        matrix.width,
        matrix.height,
        android.graphics.Bitmap.Config.ARGB_8888,
    ).asImageBitmap()
}

@Composable
internal fun TextEntryDialog(
    title: String,
    initialValue: String,
    hint: String,
    onDismiss: () -> Unit,
    onConfirm: (String) -> Unit,
) {
    var value by remember(initialValue) { mutableStateOf(initialValue) }
    val focusRequester = remember { FocusRequester() }
    Dialog(onDismissRequest = onDismiss) {
        DialogPanel {
            Text(title, color = Color.White, fontSize = 22.sp, fontWeight = FontWeight.Bold)
            Spacer(Modifier.height(15.dp))
            Box(
                Modifier.fillMaxWidth().background(Color.White, RoundedCornerShape(8.dp)).padding(14.dp),
            ) {
                if (value.isBlank()) Text(hint, color = Color.Gray)
                BasicTextField(
                    value = value,
                    onValueChange = { value = it },
                    singleLine = true,
                    textStyle = androidx.compose.ui.text.TextStyle(color = Background, fontSize = 17.sp),
                    cursorBrush = Brush.verticalGradient(listOf(Accent, Accent)),
                    modifier = Modifier.fillMaxWidth().focusRequester(focusRequester),
                )
            }
            Spacer(Modifier.height(15.dp))
            Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                Button(onClick = { if (value.isNotBlank()) onConfirm(value.trim()) }) { Text("Confirmar") }
                Button(onClick = onDismiss) { Text("Cancelar") }
            }
        }
    }
    LaunchedEffect(Unit) { focusRequester.requestFocus() }
}

@Composable
internal fun MessageDialog(message: String, onDismiss: () -> Unit) {
    Dialog(onDismissRequest = onDismiss) {
        DialogPanel {
            Text("Não foi possível importar", color = Color.White, fontSize = 22.sp, fontWeight = FontWeight.Bold)
            Spacer(Modifier.height(12.dp))
            Text(message, color = Muted)
            Spacer(Modifier.height(18.dp))
            Button(onClick = onDismiss) { Text("Fechar") }
        }
    }
}

@Composable
internal fun DialogPanel(content: @Composable ColumnScope.() -> Unit) {
    Column(
        Modifier.width(520.dp).background(Panel, RoundedCornerShape(16.dp)).padding(24.dp),
        content = content,
    )
}
