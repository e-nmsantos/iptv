package pt.iptvplayer.tv.pairing

import java.io.BufferedInputStream
import java.io.BufferedOutputStream
import java.io.Closeable
import java.net.InetAddress
import java.net.ServerSocket
import java.net.Socket
import java.net.SocketTimeoutException
import java.net.URLDecoder
import java.nio.charset.StandardCharsets
import java.security.SecureRandom
import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicInteger
import org.json.JSONArray

/**
 * [pin] lets the desktop app sync with this TV after finding it on the network (mDNS):
 * `GET /sync/<pin>` returns the TV's credential-free state, `POST /sync/<pin>` merges the
 * desktop's. Five wrong PINs end the session, so the 6 digits can't be brute-forced.
 * `POST /sync/<pin>` with `source_type=playlists` carries a JSON array of the desktop's
 * playlists (M3U, Xtream, Stalker) to import in one go.
 */
data class PairingSession(
    val url: String,
    val expiresAtMillis: Long,
    val pin: String = "",
    val port: Int = 0,
)

enum class PairingSourceType { M3U, XTREAM, STALKER, SYNC, PLAYLISTS }

data class PairingPayload(
    val type: PairingSourceType,
    val serverUrl: String = "",
    val username: String = "",
    val password: String = "",
    val macAddress: String = "",
    val syncData: String = "",
    val name: String = "",
    /** Only for [PairingSourceType.PLAYLISTS]: the playlists to import, in order. */
    val playlists: List<PairingPayload> = emptyList(),
)

class PairingServer(
    private val advertisedAddress: InetAddress,
    private val ttlMillis: Long = 5 * 60 * 1000L,
    private val now: () -> Long = System::currentTimeMillis,
    private val exportData: String = "",
) : Closeable {
    private val executor = Executors.newFixedThreadPool(4) { runnable ->
        Thread(runnable, "iptv-pairing-worker").apply { isDaemon = true }
    }
    private val closed = AtomicBoolean(false)
    private val consumed = AtomicBoolean(false)
    private val failedPins = AtomicInteger(0)
    private var serverSocket: ServerSocket? = null
    private var syncPath = ""

    fun start(onPayloadReceived: (PairingPayload) -> Unit, onExpired: () -> Unit = {}): PairingSession {
        check(serverSocket == null) { "O emparelhamento já está ativo." }
        val token = ByteArray(16).also(SecureRandom()::nextBytes).joinToString("") { "%02x".format(it) }
        val socket = ServerSocket(0, 8, InetAddress.getByName("0.0.0.0")).apply {
            soTimeout = 1_000
            reuseAddress = true
        }
        serverSocket = socket
        val expiresAt = now() + ttlMillis
        val host = if (advertisedAddress is java.net.Inet6Address) {
            "[${advertisedAddress.hostAddress}]"
        } else {
            advertisedAddress.hostAddress
        }
        val path = "/pair/$token"
        val pin = (SecureRandom().nextInt(900_000) + 100_000).toString()
        syncPath = "/sync/$pin"
        Thread({
            try {
                while (!closed.get() && !consumed.get() && failedPins.get() < MAX_PIN_ATTEMPTS && now() < expiresAt) {
                    try {
                        val client = socket.accept()
                        executor.execute {
                            // An uncaught exception on any thread kills the whole app on
                            // Android, and a phone that stalls, disconnects mid-request or
                            // sends a malformed %-escape must only cost that one request.
                            try {
                                client.use { handle(it, path, onPayloadReceived) }
                            } catch (_: Exception) {
                            }
                        }
                    } catch (_: SocketTimeoutException) {
                        // Wake periodically to enforce expiry.
                    }
                }
                if (!closed.get() && !consumed.get() && now() >= expiresAt) onExpired()
            } finally {
                close()
            }
        }, "iptv-pairing-acceptor").apply { isDaemon = true }.start()
        return PairingSession("http://$host:${socket.localPort}$path", expiresAt, pin, socket.localPort)
    }

    private fun handle(socket: Socket, path: String, onPayloadReceived: (PairingPayload) -> Unit) {
        socket.soTimeout = 5_000
        val input = BufferedInputStream(socket.getInputStream())
        val output = BufferedOutputStream(socket.getOutputStream())
        val request = readRequest(input) ?: return respond(output, 400, "Pedido inválido.", "text/plain; charset=utf-8")
        if (request.path.endsWith(".ico") || request.path.endsWith(".png")) {
            return respond(output, 204, "", "image/x-icon")
        }
        if (request.path.startsWith("/sync/")) return handleDesktopSync(request, output, onPayloadReceived)
        if (request.path != path) return respond(output, 404, "Não encontrado.", "text/plain; charset=utf-8")
        when (request.method) {
            "GET" -> respond(output, 200, page(path), "text/html; charset=utf-8")
            "POST" -> {
                val form = parseForm(request.body)
                val payload = validatePayload(form)
                if (payload == null) {
                    respond(output, 400, resultPage("Dados inválidos", "Confirma o tipo de ligação e preenche todos os campos obrigatórios."), "text/html; charset=utf-8")
                    return
                }
                if (!consumed.compareAndSet(false, true)) {
                    respond(output, 409, resultPage("Código já utilizado", "Cria um novo código na televisão."), "text/html; charset=utf-8")
                    return
                }
                respond(output, 200, resultPage("Lista enviada", "A carregar canais na televisão. Podes fechar esta página."), "text/html; charset=utf-8")
                onPayloadReceived(payload)
            }
            else -> respond(output, 405, "Método não permitido.", "text/plain; charset=utf-8", "Allow: GET, POST\r\n")
        }
    }

    private fun handleDesktopSync(
        request: Request,
        output: BufferedOutputStream,
        onPayloadReceived: (PairingPayload) -> Unit,
    ) {
        val json = "application/json; charset=utf-8"
        if (request.path != syncPath) {
            failedPins.incrementAndGet()
            return respond(output, 403, """{"error":"PIN incorreto"}""", json)
        }
        when (request.method) {
            "GET" -> respond(output, 200, exportData.ifBlank { """{"schema_version":1,"favorites":[],"progress":{}}""" }, json)
            "POST" -> {
                val form = parseForm(request.body)
                val payload = if (form["source_type"].equals("playlists", ignoreCase = true)) {
                    parsePlaylistBatch(form["playlists"].orEmpty())
                } else {
                    validatePayload(form)?.takeIf { it.type == PairingSourceType.SYNC }
                }
                if (payload == null) {
                    return respond(output, 400, """{"error":"Dados de sincronização inválidos"}""", json)
                }
                if (!consumed.compareAndSet(false, true)) {
                    return respond(output, 409, """{"error":"Código já utilizado"}""", json)
                }
                respond(output, 200, """{"ok":true}""", json)
                onPayloadReceived(payload)
            }
            else -> respond(output, 405, """{"error":"Método não permitido"}""", json, "Allow: GET, POST\r\n")
        }
    }

    private data class Request(val method: String, val path: String, val body: String)

    private fun readRequest(input: BufferedInputStream): Request? {
        val headerBytes = ArrayList<Byte>()
        var marker = 0
        while (headerBytes.size < MAX_HEADER_BYTES) {
            val value = input.read()
            if (value < 0) return null
            headerBytes += value.toByte()
            marker = when {
                marker == 0 && value == '\r'.code -> 1
                marker == 1 && value == '\n'.code -> 2
                marker == 2 && value == '\r'.code -> 3
                marker == 3 && value == '\n'.code -> 4
                value == '\r'.code -> 1
                else -> 0
            }
            if (marker == 4) break
        }
        if (marker != 4) return null
        val header = headerBytes.toByteArray().toString(StandardCharsets.ISO_8859_1)
        val lines = header.split("\r\n")
        val requestLine = lines.firstOrNull()?.split(' ') ?: return null
        if (requestLine.size < 2) return null
        val contentLength = lines.asSequence()
            .mapNotNull { line ->
                val parts = line.split(':', limit = 2)
                if (parts.size == 2 && parts[0].equals("Content-Length", true)) parts[1].trim().toIntOrNull() else null
            }
            .firstOrNull() ?: 0
        if (contentLength !in 0..MAX_BODY_BYTES) return null
        val bodyBytes = ByteArray(contentLength)
        var offset = 0
        while (offset < contentLength) {
            val count = input.read(bodyBytes, offset, contentLength - offset)
            if (count < 0) return null
            offset += count
        }
        val rawPath = requestLine[1].substringBefore('?')
        val normalizedPath = when {
            rawPath.startsWith("http://", ignoreCase = true) || rawPath.startsWith("https://", ignoreCase = true) -> {
                val slashIndex = rawPath.indexOf('/', rawPath.indexOf("://") + 3)
                if (slashIndex >= 0) rawPath.substring(slashIndex) else "/"
            }
            else -> rawPath
        }
        return Request(
            method = requestLine[0].uppercase(),
            path = normalizedPath,
            body = bodyBytes.toString(StandardCharsets.UTF_8),
        )
    }

    private fun parseForm(body: String): Map<String, String> = body.split('&').mapNotNull { field ->
        val separator = field.indexOf('=')
        if (separator < 0) return@mapNotNull null
        // A malformed %-escape drops just that field, so validation answers 400.
        runCatching {
            val key = URLDecoder.decode(field.substring(0, separator), StandardCharsets.UTF_8.name())
            val value = URLDecoder.decode(field.substring(separator + 1), StandardCharsets.UTF_8.name())
            key to value
        }.getOrNull()
    }.toMap()

    private fun validPlaylistUrl(value: String): Boolean {
        if (value.length !in 8..4096) return false
        val clean = value.substringBefore('|').trim()
        val lower = clean.lowercase()
        if (!lower.startsWith("http://") && !lower.startsWith("https://")) return false
        val afterScheme = clean.substring(clean.indexOf("://") + 3)
        val hostPart = afterScheme.substringBefore('/').substringBefore(':').substringBefore('?')
        return hostPart.isNotBlank() && !hostPart.contains(' ')
    }

    private fun validatePayload(form: Map<String, String>): PairingPayload? {
        val type = when (form["source_type"]?.lowercase()) {
            "m3u" -> PairingSourceType.M3U
            "xtream" -> PairingSourceType.XTREAM
            "stalker" -> PairingSourceType.STALKER
            "sync" -> PairingSourceType.SYNC
            else -> return null
        }
        val name = form["name"].orEmpty().trim()
        if (type == PairingSourceType.SYNC) {
            val syncData = form["sync_data"].orEmpty().trim()
            if (syncData.length !in 20..MAX_SYNC_CHARS || !syncData.startsWith('{')) return null
            return PairingPayload(type = type, syncData = syncData, name = name)
        }
        val serverUrl = form["url"].orEmpty().trim()
        if (!validPlaylistUrl(normalizeServerUrl(serverUrl, type))) return null
        val username = form["username"].orEmpty().trim()
        val password = form["password"].orEmpty()
        val mac = form["mac"].orEmpty().trim()
        if (type == PairingSourceType.XTREAM && (username.isBlank() || password.isBlank())) return null
        if (type == PairingSourceType.STALKER && !Regex("^(?:[0-9A-Fa-f]{2}[:-]?){5}[0-9A-Fa-f]{2}$").matches(mac)) return null
        return PairingPayload(type, normalizeServerUrl(serverUrl, type), username, password, mac, name = name)
    }

    /** Entries that fail the same checks as the phone form are dropped; none valid is a 400. */
    private fun parsePlaylistBatch(raw: String): PairingPayload? {
        val array = runCatching { JSONArray(raw) }.getOrNull() ?: return null
        val entries = (0 until minOf(array.length(), MAX_BATCH_PLAYLISTS)).mapNotNull { index ->
            val item = array.optJSONObject(index) ?: return@mapNotNull null
            val form = listOf("source_type", "name", "url", "username", "password", "mac")
                .associateWith { key -> item.optString(key, "") }
            validatePayload(form)?.takeIf { it.type != PairingSourceType.SYNC }
        }
        return if (entries.isEmpty()) null else PairingPayload(PairingSourceType.PLAYLISTS, playlists = entries)
    }

    private fun normalizeServerUrl(value: String, type: PairingSourceType): String {
        if (value.startsWith("http://", ignoreCase = true) || value.startsWith("https://", ignoreCase = true)) return value
        return (if (type == PairingSourceType.STALKER || type == PairingSourceType.XTREAM) "http://" else "https://") + value
    }

    private fun respond(
        output: BufferedOutputStream,
        status: Int,
        body: String,
        contentType: String,
        extraHeaders: String = "",
    ) {
        val payload = body.toByteArray(StandardCharsets.UTF_8)
        val reason = when (status) {
            200 -> "OK"
            204 -> "No Content"
            400 -> "Bad Request"
            403 -> "Forbidden"
            404 -> "Not Found"
            405 -> "Method Not Allowed"
            409 -> "Conflict"
            else -> "Error"
        }
        output.write(
            ("HTTP/1.1 $status $reason\r\n" +
                "Content-Type: $contentType\r\n" +
                "Content-Length: ${payload.size}\r\n" +
                "Cache-Control: no-store\r\n" +
                "Content-Security-Policy: default-src 'none'; style-src 'unsafe-inline'; form-action 'self'\r\n" +
                "X-Content-Type-Options: nosniff\r\n" +
                "X-Frame-Options: DENY\r\n" +
                extraHeaders + "Connection: close\r\n\r\n").toByteArray(StandardCharsets.US_ASCII),
        )
        if (payload.isNotEmpty()) {
            output.write(payload)
        }
        output.flush()
    }

    private fun page(path: String): String = """<!doctype html>
        <html lang="pt"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
        <title>IPTV Player TV</title><style>body{font-family:system-ui;background:#0e0e10;color:#fff;margin:0;padding:20px}main{max-width:620px;margin:auto}section{background:#1c1c1f;padding:22px;border-radius:18px;margin:14px 0}label{display:block;margin:13px 0 7px}input,textarea,button{box-sizing:border-box;width:100%;padding:14px;border:0;border-radius:10px;font-size:16px}textarea{min-height:120px}button{margin-top:14px;background:#e8455a;color:#fff;font-weight:700}.note{color:#a8a8ad;font-size:14px;line-height:1.45}h2{margin-top:0}</style></head>
        <body><main><h1>Enviar ligação para a TV</h1><p class="note">Escolhe o tipo fornecido pelo teu serviço. A ligação é direta para a televisão, usa HTTP local e deve ser usada apenas numa rede doméstica de confiança.</p>
        <section><h2>M3U / M3U8</h2><form method="post" action="$path"><input type="hidden" name="source_type" value="m3u"><label>Nome da lista (opcional)</label><input name="name" maxlength="100" placeholder="Ex: Minha Lista IPTV"><label>Endereço da lista</label><input name="url" type="text" autocapitalize="none" autocomplete="off" spellcheck="false" maxlength="4096" required placeholder="https://servidor/lista.m3u"><button type="submit">Enviar M3U</button></form></section>
        <section><h2>Xtream Codes</h2><form method="post" action="$path"><input type="hidden" name="source_type" value="xtream"><label>Nome da lista (opcional)</label><input name="name" maxlength="100" placeholder="Ex: Minha Conta Xtream"><label>Servidor</label><input name="url" type="text" autocapitalize="none" autocomplete="off" spellcheck="false" maxlength="4096" required placeholder="http://servidor:porta"><label>Utilizador</label><input name="username" maxlength="256" required autocomplete="username"><label>Palavra-passe</label><input name="password" type="password" maxlength="512" required autocomplete="current-password"><button type="submit">Enviar Xtream</button></form></section>
        <section><h2>Stalker Portal</h2><form method="post" action="$path"><input type="hidden" name="source_type" value="stalker"><label>Nome da lista (opcional)</label><input name="name" maxlength="100" placeholder="Ex: Meu Portal Stalker"><label>Portal</label><input name="url" type="text" autocapitalize="none" autocomplete="off" spellcheck="false" maxlength="4096" required placeholder="http://servidor:porta/c/"><label>Endereço MAC</label><input name="mac" maxlength="17" required placeholder="00:1A:79:00:00:00"><button type="submit">Enviar Stalker</button></form></section>
        <section><h2>Sincronização do computador</h2><p class="note">Cola aqui o estado do desktop. A união mantém favoritos e usa os pontos de retoma recebidos; não contém credenciais nem URLs.</p><form method="post" action="$path"><input type="hidden" name="source_type" value="sync"><textarea name="sync_data" maxlength="$MAX_SYNC_CHARS" required></textarea><button type="submit">Sincronizar para a TV</button></form></section>
        ${if (exportData.isBlank()) "" else "<section><h2>Enviar estado da TV</h2><p class=\"note\">Copia este conteúdo e importa-o no desktop.</p><textarea readonly>${htmlEscape(exportData)}</textarea></section>"}
        </main></body></html>""".trimIndent()

    private fun resultPage(title: String, message: String): String = """<!doctype html>
        <html lang="pt"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>$title</title>
        <style>body{font-family:system-ui;background:#0e0e10;color:#fff;padding:28px}main{max-width:560px;margin:auto;background:#1c1c1f;padding:24px;border-radius:18px}p{color:#a8a8ad}</style></head><body><main><h1>$title</h1><p>$message</p></main></body></html>"""

    private fun htmlEscape(value: String): String = value
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace("\"", "&quot;")

    override fun close() {
        if (closed.compareAndSet(false, true)) {
            runCatching { serverSocket?.close() }
            executor.shutdownNow()
        }
    }

    companion object {
        private const val MAX_HEADER_BYTES = 16 * 1024
        private const val MAX_BODY_BYTES = 512 * 1024
        private const val MAX_SYNC_CHARS = 150 * 1024
        private const val MAX_PIN_ATTEMPTS = 5
        private const val MAX_BATCH_PLAYLISTS = 50
    }
}
