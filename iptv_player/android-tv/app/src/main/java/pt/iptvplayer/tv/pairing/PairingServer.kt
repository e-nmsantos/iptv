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

data class PairingSession(
    val url: String,
    val expiresAtMillis: Long,
)

enum class PairingSourceType { M3U, XTREAM, STALKER, SYNC }

data class PairingPayload(
    val type: PairingSourceType,
    val serverUrl: String = "",
    val username: String = "",
    val password: String = "",
    val macAddress: String = "",
    val syncData: String = "",
)

class PairingServer(
    private val advertisedAddress: InetAddress,
    private val ttlMillis: Long = 5 * 60 * 1000L,
    private val now: () -> Long = System::currentTimeMillis,
    private val exportData: String = "",
) : Closeable {
    private val executor = Executors.newSingleThreadExecutor { runnable ->
        Thread(runnable, "iptv-pairing-server").apply { isDaemon = true }
    }
    private val closed = AtomicBoolean(false)
    private val consumed = AtomicBoolean(false)
    private var serverSocket: ServerSocket? = null

    fun start(onPayloadReceived: (PairingPayload) -> Unit, onExpired: () -> Unit = {}): PairingSession {
        check(serverSocket == null) { "O emparelhamento já está ativo." }
        val token = ByteArray(16).also(SecureRandom()::nextBytes).joinToString("") { "%02x".format(it) }
        val socket = ServerSocket(0, 4, InetAddress.getByName("0.0.0.0")).apply {
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
        executor.execute {
            try {
                while (!closed.get() && !consumed.get() && now() < expiresAt) {
                    try {
                        socket.accept().use { client -> handle(client, path, onPayloadReceived) }
                    } catch (_: SocketTimeoutException) {
                        // Wake periodically to enforce expiry.
                    }
                }
                if (!closed.get() && !consumed.get() && now() >= expiresAt) onExpired()
            } finally {
                close()
            }
        }
        return PairingSession("http://$host:${socket.localPort}$path", expiresAt)
    }

    private fun handle(socket: Socket, path: String, onPayloadReceived: (PairingPayload) -> Unit) {
        socket.soTimeout = 5_000
        val input = BufferedInputStream(socket.getInputStream())
        val output = BufferedOutputStream(socket.getOutputStream())
        val request = readRequest(input) ?: return respond(output, 400, "Pedido inválido.", "text/plain; charset=utf-8")
        if (request.path != path) return respond(output, 404, "Não encontrado.", "text/plain; charset=utf-8")
        when (request.method) {
            "GET" -> respond(output, 200, page(path), "text/html; charset=utf-8")
            "POST" -> {
                val form = parseForm(request.body)
                val payload = validatePayload(form)
                if (payload == null) {
                    respond(output, 400, resultPage("Dados inválidos", "Confirma o tipo de ligação e preenche todos os campos."), "text/html; charset=utf-8")
                    return
                }
                if (!consumed.compareAndSet(false, true)) {
                    respond(output, 409, resultPage("Código já utilizado", "Cria um novo código na televisão."), "text/html; charset=utf-8")
                    return
                }
                respond(output, 200, resultPage("Lista enviada", "Podes voltar à televisão."), "text/html; charset=utf-8")
                onPayloadReceived(payload)
            }
            else -> respond(output, 405, "Método não permitido.", "text/plain; charset=utf-8", "Allow: GET, POST\r\n")
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
        return Request(
            method = requestLine[0].uppercase(),
            path = requestLine[1].substringBefore('?'),
            body = bodyBytes.toString(StandardCharsets.UTF_8),
        )
    }

    private fun parseForm(body: String): Map<String, String> = body.split('&').mapNotNull { field ->
        val separator = field.indexOf('=')
        if (separator < 0) return@mapNotNull null
        val key = URLDecoder.decode(field.substring(0, separator), StandardCharsets.UTF_8.name())
        val value = URLDecoder.decode(field.substring(separator + 1), StandardCharsets.UTF_8.name())
        key to value
    }.toMap()

    private fun validPlaylistUrl(value: String): Boolean =
        value.length in 8..4096 && runCatching {
            val uri = java.net.URI(value)
            uri.scheme?.lowercase() in setOf("http", "https") && !uri.host.isNullOrBlank()
        }.getOrDefault(false)

    private fun validatePayload(form: Map<String, String>): PairingPayload? {
        val type = when (form["source_type"]?.lowercase()) {
            "m3u" -> PairingSourceType.M3U
            "xtream" -> PairingSourceType.XTREAM
            "stalker" -> PairingSourceType.STALKER
            "sync" -> PairingSourceType.SYNC
            else -> return null
        }
        if (type == PairingSourceType.SYNC) {
            val syncData = form["sync_data"].orEmpty().trim()
            if (syncData.length !in 20..MAX_SYNC_CHARS || !syncData.startsWith('{')) return null
            return PairingPayload(type = type, syncData = syncData)
        }
        val serverUrl = form["url"].orEmpty().trim()
        if (!validPlaylistUrl(normalizeServerUrl(serverUrl, type))) return null
        val username = form["username"].orEmpty().trim()
        val password = form["password"].orEmpty()
        val mac = form["mac"].orEmpty().trim()
        if (type == PairingSourceType.XTREAM && (username.isBlank() || password.isBlank())) return null
        if (type == PairingSourceType.STALKER && !Regex("^(?:[0-9A-Fa-f]{2}[:-]?){5}[0-9A-Fa-f]{2}$").matches(mac)) return null
        return PairingPayload(type, normalizeServerUrl(serverUrl, type), username, password, mac)
    }

    private fun normalizeServerUrl(value: String, type: PairingSourceType): String {
        if (value.startsWith("http://") || value.startsWith("https://")) return value
        return (if (type == PairingSourceType.STALKER) "http://" else "https://") + value
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
            400 -> "Bad Request"
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
        output.write(payload)
        output.flush()
    }

    private fun page(path: String): String = """<!doctype html>
        <html lang="pt"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
        <title>IPTV Player TV</title><style>body{font-family:system-ui;background:#07111f;color:#fff;margin:0;padding:20px}main{max-width:620px;margin:auto}section{background:#10243a;padding:22px;border-radius:18px;margin:14px 0}label{display:block;margin:13px 0 7px}input,textarea,button{box-sizing:border-box;width:100%;padding:14px;border:0;border-radius:10px;font-size:16px}textarea{min-height:120px}button{margin-top:14px;background:#41d3bd;color:#07111f;font-weight:700}.note{color:#a6b4c4;font-size:14px;line-height:1.45}h2{margin-top:0}</style></head>
        <body><main><h1>Enviar ligação para a TV</h1><p class="note">Escolhe o tipo fornecido pelo teu serviço. A ligação é direta para a televisão, usa HTTP local e deve ser usada apenas numa rede doméstica de confiança. Outros dispositivos na rede podem intercetar os dados.</p>
        <section><h2>M3U / M3U8</h2><form method="post" action="$path"><input type="hidden" name="source_type" value="m3u"><label>Endereço da lista</label><input name="url" type="url" maxlength="4096" required placeholder="https://servidor/lista.m3u"><button type="submit">Enviar M3U</button></form></section>
        <section><h2>Xtream Codes</h2><form method="post" action="$path"><input type="hidden" name="source_type" value="xtream"><label>Servidor</label><input name="url" maxlength="4096" required placeholder="http://servidor:porta"><label>Utilizador</label><input name="username" maxlength="256" required autocomplete="username"><label>Palavra-passe</label><input name="password" type="password" maxlength="512" required autocomplete="current-password"><button type="submit">Enviar Xtream</button></form></section>
        <section><h2>Stalker Portal</h2><form method="post" action="$path"><input type="hidden" name="source_type" value="stalker"><label>Portal</label><input name="url" maxlength="4096" required placeholder="http://servidor:porta/c/"><label>Endereço MAC</label><input name="mac" maxlength="17" required placeholder="00:1A:79:00:00:00"><button type="submit">Enviar Stalker</button></form></section>
        <section><h2>Sincronização do computador</h2><p class="note">Cola aqui o estado do desktop. A união mantém favoritos e usa os pontos de retoma recebidos; não contém credenciais nem URLs.</p><form method="post" action="$path"><input type="hidden" name="source_type" value="sync"><textarea name="sync_data" maxlength="$MAX_SYNC_CHARS" required></textarea><button type="submit">Sincronizar para a TV</button></form></section>
        ${if (exportData.isBlank()) "" else "<section><h2>Enviar estado da TV</h2><p class=\"note\">Copia este conteúdo e importa-o no desktop.</p><textarea readonly>${htmlEscape(exportData)}</textarea></section>"}
        </main></body></html>""".trimIndent()

    private fun resultPage(title: String, message: String): String = """<!doctype html>
        <html lang="pt"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>$title</title>
        <style>body{font-family:system-ui;background:#07111f;color:#fff;padding:28px}main{max-width:560px;margin:auto;background:#10243a;padding:24px;border-radius:18px}p{color:#a6b4c4}</style></head><body><main><h1>$title</h1><p>$message</p></main></body></html>"""

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
    }
}
