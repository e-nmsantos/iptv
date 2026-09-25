package pt.iptvplayer.tv.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.tv.material3.Text
import pt.iptvplayer.tv.BuildConfig
import pt.iptvplayer.tv.CatalogUiState

/**
 * Read-only runtime diagnostics: app version, active playlist and the sizes of the
 * locally loaded catalogue. Everything shown here comes from data already held by the
 * [CatalogUiState], so the screen never touches the network or the database directly.
 */
@Composable
internal fun DiagnosticsScreen(state: CatalogUiState) {
    val epgCount = state.epg.values.sumOf { it.size }
    Column(
        Modifier.fillMaxSize().background(Panel, RoundedCornerShape(14.dp)).padding(26.dp),
    ) {
        Text("Diagnóstico", color = Color.White, fontSize = 28.sp, fontWeight = FontWeight.Bold)
        Text(
            "Informação local sobre a instalação e o catálogo carregado.",
            color = Muted,
            fontSize = 13.sp,
            modifier = Modifier.padding(top = 4.dp),
        )
        Spacer(Modifier.height(20.dp))
        DiagnosticRow("Versão da app", BuildConfig.VERSION_NAME)
        DiagnosticRow("Versão de compilação", BuildConfig.VERSION_CODE.toString())
        DiagnosticRow("Lista ativa", state.playlistName)
        DiagnosticRow("Listas configuradas", state.playlists.size.toString())
        DiagnosticRow("Conteúdos no catálogo", state.totalChannels.toString())
        DiagnosticRow("Conteúdos carregados agora", state.channels.size.toString())
        DiagnosticRow("Categorias disponíveis", state.availableGroups.size.toString())
        DiagnosticRow("Eventos EPG carregados", epgCount.toString())
        DiagnosticRow("Favoritos", state.homeFavorites.size.toString())
        DiagnosticRow("A atualizar", if (state.loading) "Sim" else "Não")
    }
}

@Composable
private fun DiagnosticRow(label: String, value: String) {
    Row(Modifier.fillMaxWidth().padding(vertical = 8.dp)) {
        Text(label, color = Muted, fontSize = 15.sp, modifier = Modifier.weight(1f))
        Text(
            value,
            color = Color.White,
            fontSize = 15.sp,
            fontWeight = FontWeight.SemiBold,
            modifier = Modifier.padding(start = 18.dp),
        )
    }
}
