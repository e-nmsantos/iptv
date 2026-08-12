package pt.iptvplayer.tv.pairing

import android.content.Context
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch

data class PairingStatus(
    val url: String? = null,
    val expiresAtMillis: Long = 0,
    val message: String? = null,
)

/** Owns pairing lifecycle so catalogue state does not manage sockets directly. */
class PairingCoordinator(
    context: Context,
    private val scope: CoroutineScope,
) : AutoCloseable {
    private val addressResolver = NetworkAddressResolver(context.applicationContext)
    private var job: Job? = null
    @Volatile private var server: PairingServer? = null

    fun start(
        exportData: String = "",
        onPayload: (PairingPayload) -> Unit,
        onStatus: (PairingStatus) -> Unit,
        onError: (Throwable) -> Unit,
    ) {
        stop()
        job = scope.launch(Dispatchers.IO) {
            val address = addressResolver.currentIpv4Address()
            if (address == null) {
                onError(IllegalStateException("Liga a televisão a uma rede Wi-Fi ou Ethernet antes de criar o QR code."))
                return@launch
            }
            val candidate = PairingServer(address, exportData = exportData)
            runCatching {
                val session = candidate.start(
                    onPayloadReceived = { payload ->
                        onStatus(PairingStatus(message = "Dados recebidos. A ligar…"))
                        onPayload(payload)
                    },
                    onExpired = {
                        onStatus(PairingStatus(message = "O código expirou. Cria um novo código."))
                    },
                )
                if (!isActive) {
                    candidate.close()
                    return@runCatching
                }
                server = candidate
                onStatus(PairingStatus(session.url, session.expiresAtMillis))
            }.onFailure {
                candidate.close()
                onError(it)
            }
        }
    }

    fun stop() {
        job?.cancel()
        job = null
        server?.close()
        server = null
    }

    override fun close() = stop()
}
