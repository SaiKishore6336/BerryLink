package app.berrylink.companion.net

import app.berrylink.companion.model.AskReply
import app.berrylink.companion.model.PairResult
import app.berrylink.companion.model.StoredPairing
import app.berrylink.companion.protocol.RemoteException
import app.berrylink.companion.protocol.Wire
import app.berrylink.companion.protocol.WireMessage
import app.berrylink.companion.protocol.jsonBool
import app.berrylink.companion.protocol.jsonString
import app.berrylink.companion.security.Fingerprint
import app.berrylink.companion.security.PinnedTls
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch
import kotlinx.coroutines.withTimeout
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import okio.ByteString
import java.io.IOException
import java.util.Base64
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean

sealed interface ClientEvent {
    data object Opened : ClientEvent
    data class Authenticated(val desktopName: String) : ClientEvent
    data class ConnectionFailed(
        val message: String,
        val pinMismatch: Boolean = false,
        val authenticationFailed: Boolean = false,
    ) : ClientEvent
    data class Closed(val message: String) : ClientEvent
    data class DesktopEvent(val method: String, val message: WireMessage) : ClientEvent
}

/**
 * Authenticated WebSocket client with an exact TLS pin, bounded requests, and
 * no retry that could duplicate a sensitive pair or ask message.
 */
class BerryLinkClient(
    private val onEvent: (ClientEvent) -> Unit,
) {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private val pending = ConcurrentHashMap<String, CompletableDeferred<WireMessage>>()
    private var webSocket: WebSocket? = null
    private var openSignal = CompletableDeferred<Boolean>()
    private var generation = 0
    private var authenticated = false
    private var manualClose = false
    private var expectedPin: String? = null

    val isOpen: Boolean
        get() = webSocket != null && authenticated

    fun open(host: String, port: Int, fingerprint: String, pairing: StoredPairing?): Boolean {
        closeInternal(notify = false)
        val pin = Fingerprint.normalize(fingerprint)
            ?: return false.also {
                onEvent(ClientEvent.ConnectionFailed("The saved certificate pin is invalid. Pair again."))
            }
        val token = pairing?.takeIf { it.fingerprint == pin }
        expectedPin = pin
        authenticated = false
        manualClose = false
        generation += 1
        val gen = generation
        openSignal = CompletableDeferred()

        val tls = try {
            PinnedTls.forFingerprint(pin)
        } catch (exc: Exception) {
            onEvent(ClientEvent.ConnectionFailed(exc.message ?: "Could not prepare the secure connection."))
            return false
        }
        val http = OkHttpClient.Builder()
            .sslSocketFactory(tls.socketFactory, tls.trustManager)
            .hostnameVerifier(tls.hostnameVerifier)
            .connectTimeout(12, TimeUnit.SECONDS)
            .readTimeout(0, TimeUnit.MILLISECONDS)
            .writeTimeout(30, TimeUnit.SECONDS)
            .pingInterval(20, TimeUnit.SECONDS)
            .retryOnConnectionFailure(false)
            .build()
        val url = "wss://${urlHost(host)}:$port/"
        val request = Request.Builder()
            .url(url)
            .header("User-Agent", "BerryLink/0.1 (Android)")
            .build()
        val socket = http.newWebSocket(
            request,
            object : WebSocketListener() {
                override fun onOpen(socket: WebSocket, response: Response) {
                    if (gen != generation) {
                        socket.close(1000, "Superseded")
                        return
                    }
                    openSignal.complete(true)
                    onEvent(ClientEvent.Opened)
                    if (token != null) {
                        scope.launch {
                            try {
                                val message = request(
                                    "auth",
                                    buildJsonObject {
                                        put("device_id", jsonString(token.deviceId))
                                        put("token", jsonString(token.token))
                                    },
                                    timeoutMs = 20_000,
                                )
                                if (gen != generation) return@launch
                                authenticated = true
                                val desktopName = message.text("desktop_name") ?: token.desktopName
                                onEvent(ClientEvent.Authenticated(desktopName))
                            } catch (exc: Exception) {
                                if (gen != generation) return@launch
                                val remote = exc as? RemoteException
                                onEvent(
                                    ClientEvent.ConnectionFailed(
                                        message = remote?.message ?: friendlyNetworkError(exc),
                                        authenticationFailed = true,
                                    )
                                )
                                closeInternal(notify = false)
                            }
                        }
                    }
                }

                override fun onMessage(socket: WebSocket, text: String) {
                    if (gen != generation) return
                    handleMessage(text)
                }

                override fun onMessage(socket: WebSocket, bytes: ByteString) {
                    // The protocol is JSON text only.  Ignore unsolicited binary frames.
                }

                override fun onClosing(socket: WebSocket, code: Int, reason: String) {
                    if (gen != generation) return
                    socket.close(1000, null)
                }

                override fun onClosed(socket: WebSocket, code: Int, reason: String) {
                    if (gen != generation) return
                    failPending(IOException("Desktop connection closed."))
                    webSocket = null
                    openSignal.complete(false)
                    if (!manualClose) {
                        onEvent(ClientEvent.Closed("The desktop connection closed."))
                    }
                }

                override fun onFailure(socket: WebSocket, t: Throwable, response: Response?) {
                    if (gen != generation) return
                    failPending(t)
                    webSocket = null
                    openSignal.complete(false)
                    val pinMismatch = expectedPin != null && PinnedTls.looksLikePinMismatch(t)
                    val message = if (pinMismatch) {
                        "The desktop certificate does not match the saved pin. For your safety, BerryLink will not connect."
                    } else {
                        friendlyNetworkError(t)
                    }
                    if (!manualClose) {
                        onEvent(ClientEvent.ConnectionFailed(message, pinMismatch = pinMismatch))
                    }
                }
            },
        )
        webSocket = socket
        return true
    }

    suspend fun pair(code: String, deviceName: String): PairResult {
        if (!withTimeout(15_000) { openSignal.await() }) {
            throw IOException("The secure connection to the desktop did not open.")
        }
        val message = request(
            "pair.request",
            buildJsonObject {
                put("protocol", 1)
                put("code", jsonString(code))
                put("device_name", jsonString(deviceName))
            },
            timeoutMs = 25_000,
        )
        val result = Wire.pairResult(message)
        val returnedPin = Fingerprint.normalize(result.fingerprint)
        val pinned = expectedPin
        if (returnedPin != null && pinned != null && returnedPin != pinned) {
            throw RemoteException(
                "pin_mismatch",
                "The desktop certificate changed during pairing. Nothing was saved.",
            )
        }
        authenticated = true
        return result.copy(fingerprint = pinned ?: result.fingerprint)
    }

    suspend fun pairCodeless(deviceName: String): PairResult {
        if (!withTimeout(15_000) { openSignal.await() }) {
            throw IOException("The secure connection to the desktop did not open.")
        }
        // The desktop shows an Allow/Deny prompt; owners can take their time,
        // so wait up to two minutes instead of the usual 25 s pair timeout.
        val message = request(
            "pair.request",
            buildJsonObject {
                put("protocol", 1)
                put("codeless", jsonBool(true))
                put("device_name", jsonString(deviceName))
            },
            timeoutMs = 120_000,
        )
        val result = Wire.pairResult(message)
        val returnedPin = Fingerprint.normalize(result.fingerprint)
        val pinned = expectedPin
        if (returnedPin != null && pinned != null && returnedPin != pinned) {
            throw RemoteException(
                "pin_mismatch",
                "The desktop certificate changed during pairing. Nothing was saved.",
            )
        }
        authenticated = true
        return result.copy(fingerprint = pinned ?: result.fingerprint)
    }

    suspend fun ask(text: String, audio: ByteArray?): AskReply {
        if (!authenticated) throw IOException("Not connected to a desktop.")
        val payload = buildJsonObject {
            put("text", jsonString(text))
            if (audio != null && audio.isNotEmpty()) {
                put("audio", jsonString(Base64.getEncoder().encodeToString(audio)))
                put("audio_mime", jsonString("audio/wav"))
            }
            put("include_screen", jsonBool(true))
            put("include_screenshot", jsonBool(false))
        }
        val message = request("ask", payload, timeoutMs = 140_000)
        return Wire.askReply(message)
    }

    suspend fun resetConversation() {
        if (!authenticated) return
        runCatching { request("session.reset", buildJsonObject { }, timeoutMs = 15_000) }
    }

    fun close() {
        manualClose = true
        closeInternal(notify = true)
    }

    private fun closeInternal(notify: Boolean) {
        generation += 1
        val socket = webSocket
        webSocket = null
        authenticated = false
        openSignal.complete(false)
        failPending(IOException("Connection closed."))
        try {
            socket?.close(1000, "BerryLink closing")
        } catch (_: Exception) {
        }
    }

    private fun handleMessage(text: String) {
        val message = try {
            Wire.parse(text)
        } catch (_: Exception) {
            return
        }
        when (message.kind) {
            "response" -> {
                val pendingCall = message.replyTo?.let(pending::remove)
                if (pendingCall == null) return
                if (message.ok == true) {
                    pendingCall.complete(message)
                } else {
                    pendingCall.completeExceptionally(Wire.errorFrom(message))
                }
            }
            "event" -> {
                val method = message.method ?: return
                if (method == "control.changed" || method == "emergency" || method == "sleep" || method == "cursor") {
                    onEvent(ClientEvent.DesktopEvent(method, message))
                }
            }
        }
    }

    private suspend fun request(
        method: String,
        payload: kotlinx.serialization.json.JsonObject,
        timeoutMs: Long,
    ): WireMessage {
        val socket = webSocket ?: throw IOException("Not connected to a desktop.")
        val wire = Wire.request(method, payload)
        val waiter = CompletableDeferred<WireMessage>()
        pending[wire.id] = waiter
        if (!socket.send(wire.text)) {
            pending.remove(wire.id)
            throw IOException("The desktop connection is not accepting messages.")
        }
        return try {
            withTimeout(timeoutMs) { waiter.await() }
        } finally {
            pending.remove(wire.id)
        }
    }

    private fun failPending(error: Throwable) {
        val snapshot = pending.values.toList()
        pending.clear()
        snapshot.forEach { it.completeExceptionally(error) }
    }

    private fun friendlyNetworkError(error: Throwable): String {
        val text = error.message.orEmpty()
        return when {
            "timeout" in text.lowercase() -> "The desktop did not answer in time."
            "refused" in text.lowercase() -> "Connection refused. Is BerryLink running on the desktop?"
            "unreachable" in text.lowercase() || "route" in text.lowercase() ->
                "The desktop is unreachable. Check that both devices are on the same Wi-Fi."
            error is java.net.UnknownHostException -> "The desktop address could not be resolved."
            error is javax.net.ssl.SSLException -> "The secure connection to the desktop failed."
            else -> "Could not connect to the desktop. Check the address and Wi-Fi."
        }
    }

    private fun urlHost(host: String): String {
        val clean = host.trim().trim('[', ']')
        return if (clean.contains(':')) "[$clean]" else clean
    }
}
