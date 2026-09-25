package pt.iptvplayer.tv

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.result.contract.ActivityResultContracts
import androidx.activity.viewModels
import coil3.ImageLoader
import coil3.SingletonImageLoader
import coil3.memory.MemoryCache
import coil3.request.allowRgb565
import coil3.request.crossfade
import pt.iptvplayer.tv.ui.IptvTvApp

class MainActivity : ComponentActivity() {
    private val viewModel: CatalogViewModel by viewModels()
    private val documentPicker = registerForActivityResult(ActivityResultContracts.OpenDocument()) { uri ->
        uri?.let(viewModel::importDocument)
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()

        // Configure memory-optimized image loader for Android TV
        SingletonImageLoader.setSafe { context ->
            ImageLoader.Builder(context)
                .memoryCache {
                    MemoryCache.Builder()
                        .maxSizePercent(context, 0.15)
                        .build()
                }
                .crossfade(true)
                .allowRgb565(true)
                .build()
        }

        setContent {
            IptvTvApp(
                viewModel = viewModel,
                onPickDocument = { documentPicker.launch(arrayOf("audio/x-mpegurl", "application/x-mpegURL", "text/plain", "*/*")) },
            )
        }
    }
}
