package app.berrylink.companion.model

data class DiscoveredDesktop(
    val serviceName: String,
    val displayName: String,
    val host: String,
    val port: Int,
    val fingerprint: String,
)

data class StoredPairing(
    val deviceId: String,
    val token: String,
    val desktopName: String,
    val host: String,
    val port: Int,
    val fingerprint: String,
) {
    val endpoint: String
        get() = "$host:$port"
}

data class PairResult(
    val deviceId: String,
    val token: String,
    val desktopName: String,
    val fingerprint: String,
)

data class AskReply(
    val reply: String,
    val provider: String,
    val model: String,
    val mood: String,
    val toolsUsed: List<String>,
    val effects: List<String>,
    val notice: String?,
)

/** Normalized desktop cursor position in [-1, 1] on each axis. */
data class GazePoint(
    val x: Float,
    val y: Float,
)

enum class LinkPhase {
    OFFLINE,
    CONNECTING,
    CONNECTED,
    PAIRING,
    ERROR,
}

enum class BerryActivity {
    IDLE,
    LISTENING,
    THINKING,
    SPEAKING,
    HAPPY,
    SLEEPING,
    ERROR,
}

data class UiState(
    val paired: StoredPairing? = null,
    val phase: LinkPhase = LinkPhase.OFFLINE,
    val connectionDetail: String = "Not connected",
    val discovered: List<DiscoveredDesktop> = emptyList(),
    val discovering: Boolean = false,
    val discoveryMessage: String = "Searching your Wi-Fi…",
    val activity: BerryActivity = BerryActivity.IDLE,
    val recording: Boolean = false,
    val recordingSeconds: Float = 0f,
    val inputLevel: Float = 0f,
    val busy: Boolean = false,
    val reply: String = "",
    val replyProvider: String? = null,
    val notice: String? = null,
    val error: String? = null,
    /** Last typed ask kept on this screen so a failed ask can be retried with one tap. */
    val lastAsk: String = "",
    val pairingBusy: Boolean = false,
    val pairingError: String? = null,
    val pairingCodeError: String? = null,
    val ttsEnabled: Boolean = true,
    val reconnectAttempt: Int = 0,
    val certificateBlocked: Boolean = false,
    val retryBlocked: Boolean = false,
    /** Why a previously-saved pairing could not be loaded (null = nothing wrong). */
    val pairingLoadIssue: String? = null,
    val cursorGaze: GazePoint? = null,
    /** Live on-device speech-to-text wording while holding the face (may be blank). */
    val speechText: String = "",
)
