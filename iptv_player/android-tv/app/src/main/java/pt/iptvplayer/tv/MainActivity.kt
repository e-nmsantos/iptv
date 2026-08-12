package pt.iptvplayer.tv

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.result.contract.ActivityResultContracts
import androidx.activity.viewModels
import pt.iptvplayer.tv.ui.IptvTvApp

class MainActivity : ComponentActivity() {
    private val viewModel: CatalogViewModel by viewModels()
    private val documentPicker = registerForActivityResult(ActivityResultContracts.OpenDocument()) { uri ->
        uri?.let(viewModel::importDocument)
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContent {
            IptvTvApp(
                viewModel = viewModel,
                onPickDocument = { documentPicker.launch(arrayOf("audio/x-mpegurl", "application/x-mpegURL", "text/plain", "*/*")) },
            )
        }
    }
}
