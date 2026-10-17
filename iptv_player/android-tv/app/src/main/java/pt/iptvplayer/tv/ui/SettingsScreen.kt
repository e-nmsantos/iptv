package pt.iptvplayer.tv.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.focusable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
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
import androidx.tv.material3.Text
import kotlinx.coroutines.delay
import pt.iptvplayer.tv.data.DecoderPreference
import pt.iptvplayer.tv.data.PlayerSettings
import pt.iptvplayer.tv.data.TimeshiftBuffer

@Composable
internal fun SettingsScreen(
    settings: PlayerSettings,
    onUpdate: ((PlayerSettings) -> PlayerSettings) -> Unit,
) {
    val firstRequester = remember { FocusRequester() }
    LaunchedEffect(Unit) {
        delay(80)
        runCatching { firstRequester.requestFocus() }
    }
    Column(Modifier.fillMaxSize()) {
        Text("Definições", color = Color.White, fontSize = 29.sp, fontWeight = FontWeight.Bold)
        Text("OK altera a opção. As alterações aplicam-se ao próximo canal que abrires.", color = Muted)
        Spacer(Modifier.height(22.dp))
        LazyColumn(verticalArrangement = Arrangement.spacedBy(10.dp)) {
            item { SettingsHeader("Reprodução") }
            item {
                SettingRow(
                    title = "Descodificação de áudio e vídeo",
                    value = settings.decoder.label,
                    description = settings.decoder.description,
                    modifier = Modifier.focusRequester(firstRequester),
                ) {
                    onUpdate { it.copy(decoder = it.decoder.next()) }
                }
            }
            item {
                SettingRow(
                    title = "Pausa em direto",
                    value = settings.timeshift.label,
                    description = "Memória usada para continuar a receber o canal enquanto está em pausa. " +
                        "A duração depende da qualidade do canal.",
                ) {
                    onUpdate { it.copy(timeshift = it.timeshift.next()) }
                }
            }
            item {
                SettingRow(
                    title = "Estatísticas da stream",
                    value = onOff(settings.showStreamStats),
                    description = "Resolução, codecs, descodificador, débito e buffer sobre o vídeo (também com o botão azul).",
                ) {
                    onUpdate { it.copy(showStreamStats = !it.showStreamStats) }
                }
            }
            item { SettingsHeader("Séries e canais") }
            item {
                SettingRow(
                    title = "Reproduzir o próximo episódio automaticamente",
                    value = onOff(settings.autoplayNextEpisode),
                    description = "No fim de um episódio, o seguinte começa após 10 segundos.",
                ) {
                    onUpdate { it.copy(autoplayNextEpisode = !it.autoplayNextEpisode) }
                }
            }
            item {
                SettingRow(
                    title = "Abrir no último canal visto",
                    value = onOff(settings.resumeLastChannelOnStart),
                    description = "Ao iniciar a app, começa logo a reproduzir o último canal em direto.",
                ) {
                    onUpdate { it.copy(resumeLastChannelOnStart = !it.resumeLastChannelOnStart) }
                }
            }
            item { SettingsHeader("Comando") }
            item {
                Column(
                    Modifier.fillMaxWidth().background(Panel, RoundedCornerShape(14.dp)).padding(18.dp),
                    verticalArrangement = Arrangement.spacedBy(6.dp),
                ) {
                    ShortcutLine("0–9", "Mudar para o canal com esse número")
                    ShortcutLine("▲ ▼  /  CH+ CH−", "Canal seguinte / anterior")
                    ShortcutLine("OK  /  ◀", "Guia de canais")
                    ShortcutLine("▶ (direita)", "Opções do canal: pausa, áudio, legendas, estatísticas")
                    ShortcutLine("⏯", "Pausar e retomar o direto")
                    ShortcutLine("Botão verde / ⟲ Último", "Voltar ao canal anterior")
                    ShortcutLine("INFO", "Programa atual e seguinte")
                    ShortcutLine("Vermelho · Amarelo · Azul", "Favorito · Faixa de áudio · Estatísticas")
                }
            }
        }
    }
}

@Composable
private fun SettingsHeader(title: String) {
    Text(
        title.uppercase(),
        color = Accent,
        fontSize = 12.sp,
        fontWeight = FontWeight.Bold,
        modifier = Modifier.padding(top = 10.dp, bottom = 2.dp),
    )
}

@Composable
private fun SettingRow(
    title: String,
    value: String,
    description: String,
    modifier: Modifier = Modifier,
    onClick: () -> Unit,
) {
    var focused by remember { mutableStateOf(false) }
    Row(
        modifier.fillMaxWidth()
            .onFocusChanged { focused = it.isFocused }
            .background(if (focused) PanelFocused else Panel, RoundedCornerShape(14.dp))
            .border(if (focused) 2.dp else 0.dp, if (focused) Accent else Color.Transparent, RoundedCornerShape(14.dp))
            .clickable(onClick = onClick)
            .focusable()
            .padding(horizontal = 20.dp, vertical = 16.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Column(Modifier.weight(1f)) {
            Text(title, color = Color.White, fontSize = 17.sp, fontWeight = FontWeight.SemiBold)
            Text(description, color = Muted, fontSize = 13.sp)
        }
        Spacer(Modifier.width(18.dp))
        Text(
            value,
            color = if (focused) Background else Accent,
            fontWeight = FontWeight.Bold,
            modifier = Modifier.background(if (focused) Accent else TvColors.Selected, RoundedCornerShape(9.dp))
                .padding(horizontal = 14.dp, vertical = 8.dp),
        )
    }
}

@Composable
private fun ShortcutLine(keys: String, action: String) {
    Row {
        Text(keys, color = Color.White, fontWeight = FontWeight.SemiBold, fontSize = 14.sp, modifier = Modifier.width(240.dp))
        Text(action, color = Muted, fontSize = 14.sp)
    }
}

private fun onOff(value: Boolean) = if (value) "Ligado" else "Desligado"

private fun DecoderPreference.next() = DecoderPreference.entries[(ordinal + 1) % DecoderPreference.entries.size]

private fun TimeshiftBuffer.next() = TimeshiftBuffer.entries[(ordinal + 1) % TimeshiftBuffer.entries.size]
