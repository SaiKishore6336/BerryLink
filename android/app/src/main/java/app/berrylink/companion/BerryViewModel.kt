package app.berrylink.companion

import android.app.Application
import android.content.Intent
import android.media.AudioManager
import android.media.ToneGenerator
import android.os.Build
import android.os.Bundle
import android.os.SystemClock
import android.speech.RecognitionListener
import android.speech.RecognizerIntent
import android.speech.SpeechRecognizer
import android.speech.tts.TextToSpeech
import android.speech.tts.UtteranceProgressListener
import android.speech.tts.Voice
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import app.berrylink.companion.audio.WavRecorder
import app.berrylink.companion.discovery.NsdDiscovery
import app.berrylink.companion.model.BerryActivity
import app.berrylink.companion.model.DiscoveredDesktop
import app.berrylink.companion.model.GazePoint
import app.berrylink.companion.model.LinkPhase
import app.berrylink.companion.model.StoredPairing
import app.berrylink.companion.model.UiState
import app.berrylink.companion.net.BerryLinkClient
import app.berrylink.companion.net.ClientEvent
import app.berrylink.companion.protocol.RemoteException
import app.berrylink.companion.security.Fingerprint
import app.berrylink.companion.security.SecureStore
import android.util.Log
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import java.io.IOException
import java.util.Locale
import kotlin.math.pow
import kotlin.math.roundToInt

class BerryViewModel(application: Application) : AndroidViewModel(application) {
    private val TAG = "BerryLink"
    private val store = SecureStore(application)
    private val recorder = WavRecorder()
    private val client = BerryLinkClient(::onClientEvent)
    private val discovery = NsdDiscovery(
        application,
        onChanged = ::onDiscovered,
        onStatus = ::onDiscoveryStatus,
    )
    private val _state = MutableStateFlow(
        UiState(
            paired = store.loadPairing(),
            ttsEnabled = store.speakReplies(),
        )
    )
    val state: StateFlow<UiState> = _state.asStateFlow()
    // Nothing-saved is a normal fresh install; any other load problem is surfaced
    // to the user (and to us) instead of silently looking like no pairing exists.
    private val pairingLoadIssue = if (_state.value.paired == null) store.lastLoadIssue else null

    private var reconnectJob: Job? = null
    private var initialConnectJob: Job? = null
    private var recordingTicker: Job? = null
    private var recordingStartedAt = 0L
    // On-device speech-to-text (no desktop credits): the phone transcribes the
    // hold and sends TEXT to the desktop. Falls back to the WAV recorder when
    // the device has no recognition service.
    private var speechRecognizer: SpeechRecognizer? = null
    private var usingSpeechRecognition = false
    private var awaitingSpeechResults = false
    private var speakJob: Job? = null
    private var tts: TextToSpeech? = null
    private var ttsReady = false
    private var ttsInitDone = false
    private var pendingSpeech: String? = null
    private val tone: ToneGenerator? = runCatching {
        ToneGenerator(AudioManager.STREAM_MUSIC, 45)
    }.getOrNull()

    init {
        _state.value.paired?.let {
            Log.d(TAG, "app start: saved pairing present device=${it.deviceId} ${it.host}:${it.port}")
        } ?: Log.d(TAG, "app start: NO saved pairing")
        if (pairingLoadIssue != null) {
            Log.w(TAG, "app start: saved pairing unusable — $pairingLoadIssue")
            // Orphaned metadata (token can't be decrypted) is worse than a clean
            // slate; clear it so the next successful pairing is unambiguous.
            store.clearPairing()
            _state.update { it.copy(pairingLoadIssue = pairingLoadIssue) }
        }
        val saved = _state.value.paired
        if (saved != null) {
            _state.update {
                it.copy(
                    phase = LinkPhase.CONNECTING,
                    connectionDetail = "Connecting to ${saved.desktopName}…",
                )
            }
            discovery.start()
            initialConnectJob = viewModelScope.launch {
                delay(900)
                connectSaved(manual = true)
            }
        } else {
            discovery.start()
        }
        viewModelScope.launch {
            recorder.amplitude.collect { level ->
                _state.update { if (it.recording) it.copy(inputLevel = level) else it }
            }
        }
        initTts()
    }

    // --------------------------------------------------------------- actions

    fun refreshDiscovery() {
        _state.update {
            it.copy(
                discovering = true,
                discoveryMessage = "Looking for BerryLink desktops…",
            )
        }
        discovery.refresh()
    }

    fun stopDiscovery() {
        discovery.stop()
        _state.update { it.copy(discovering = false) }
    }

    fun reconnect() {
        reconnectJob?.cancel()
        reconnectJob = null
        initialConnectJob?.cancel()
        initialConnectJob = null
        _state.update { it.copy(retryBlocked = false, certificateBlocked = false) }
        connectSaved(manual = true)
    }

    /**
     * One-tap connect to a discovered desktop when a saved pairing already
     * matches its certificate. Returns false when there is no matching saved
     * pairing, so the caller can fall back to the pairing sheet instead.
     */
    fun connectToDesktop(desktop: DiscoveredDesktop): Boolean {
        val saved = _state.value.paired
        val pin = Fingerprint.normalize(desktop.fingerprint)
        if (saved == null || pin == null || pin != saved.fingerprint) return false
        if (_state.value.phase == LinkPhase.CONNECTED) return true
        if (_state.value.busy || _state.value.recording) return false
        if (_state.value.phase == LinkPhase.PAIRING) return false
        // The discovered address is fresher than the saved one.
        val effective = saved.copy(host = desktop.host, port = desktop.port)
        if (desktop.host != saved.host || desktop.port != saved.port) {
            runCatching { store.updateEndpoint(desktop.host, desktop.port) }
            _state.update { it.copy(paired = effective) }
        }
        reconnectJob?.cancel()
        reconnectJob = null
        initialConnectJob?.cancel()
        initialConnectJob = null
        // A deliberate tap may retry even after an earlier auth rejection.
        _state.update {
            it.copy(
                phase = LinkPhase.CONNECTING,
                connectionDetail = "Connecting securely to ${effective.desktopName}…",
                error = null,
                retryBlocked = false,
                certificateBlocked = false,
                activity = if (it.activity == BerryActivity.ERROR) BerryActivity.IDLE else it.activity,
            )
        }
        val started = client.open(desktop.host, desktop.port, pin, effective)
        if (!started) {
            _state.update {
                it.copy(
                    phase = LinkPhase.ERROR,
                    connectionDetail = "Could not start a secure connection",
                    error = "Could not start the secure connection. Check the saved certificate pin.",
                    activity = BerryActivity.ERROR,
                )
            }
        }
        return true
    }

    fun forgetDesktop() {
        reconnectJob?.cancel()
        reconnectJob = null
        initialConnectJob?.cancel()
        initialConnectJob = null
        client.close()
        store.clearPairing()
        _state.update {
            UiState(
                paired = null,
                phase = LinkPhase.OFFLINE,
                connectionDetail = "Not paired",
                discovered = it.discovered,
                discovering = true,
                discoveryMessage = "Looking for BerryLink desktops…",
                reply = "",
                activity = BerryActivity.IDLE,
                ttsEnabled = it.ttsEnabled,
            )
        }
        discovery.start()
    }

    fun pairDesktop(desktop: DiscoveredDesktop, rawCode: String): Boolean {
        val code = rawCode.filter(Char::isDigit)
        if (code.length != 6) {
            _state.update { it.copy(pairingError = "Enter the six-digit code shown on the desktop.") }
            return false
        }
        val pin = Fingerprint.normalize(desktop.fingerprint)
        if (pin == null) {
            _state.update { it.copy(pairingError = "The desktop certificate pin is missing. Enter it manually.") }
            return false
        }
        if (_state.value.pairingBusy) return false
        reconnectJob?.cancel()
        reconnectJob = null
        initialConnectJob?.cancel()
        initialConnectJob = null
        _state.update {
            it.copy(
                phase = LinkPhase.PAIRING,
                pairingBusy = true,
                pairingError = null,
                error = null,
                connectionDetail = "Pairing securely with ${desktop.displayName}…",
            )
        }
        viewModelScope.launch {
            try {
                client.close()
                val opened = client.open(desktop.host, desktop.port, pin, null)
                if (!opened) throw IOException("Could not open the secure connection.")
                val result = client.pair(code, deviceName())
                val saved = StoredPairing(
                    deviceId = result.deviceId,
                    token = result.token,
                    desktopName = result.desktopName.ifBlank { desktop.displayName },
                    host = desktop.host,
                    port = desktop.port,
                    fingerprint = pin,
                )
                store.savePairing(saved)
                discovery.stop()
                _state.update {
                    it.copy(
                        paired = saved,
                        phase = LinkPhase.CONNECTED,
                        connectionDetail = "Connected to ${saved.desktopName}",
                        pairingBusy = false,
                        pairingError = null,
                        busy = false,
                        discovering = false,
                        certificateBlocked = false,
                        retryBlocked = false,
                        reconnectAttempt = 0,
                        notice = "Paired with ${saved.desktopName}. Hold the face and talk.",
                        reply = "",
                        replyProvider = null,
                        error = null,
                        activity = BerryActivity.HAPPY,
                    )
                }
                chirp(ToneGenerator.TONE_PROP_ACK)
                scheduleHappyToIdle()
            } catch (exc: Exception) {
                client.close()
                val message = userMessage(exc)
                _state.update {
                    it.copy(
                        phase = if (it.paired != null) LinkPhase.ERROR else LinkPhase.OFFLINE,
                        pairingBusy = false,
                        pairingError = message,
                        error = message,
                        connectionDetail = "Pairing failed",
                        activity = BerryActivity.ERROR,
                    )
                }
                chirp(ToneGenerator.TONE_PROP_BEEP2)
                if (_state.value.paired == null) discovery.start()
            }
        }
        return true
    }

    /** One-tap connect: pair with no code; the desktop owner just presses Allow. */
    fun pairCodelessDesktop(desktop: DiscoveredDesktop): Boolean {
        val pin = Fingerprint.normalize(desktop.fingerprint)
        if (pin == null) {
            _state.update { it.copy(pairingError = "The desktop certificate pin is missing. Enter it manually.") }
            return false
        }
        if (_state.value.pairingBusy) return false
        reconnectJob?.cancel()
        reconnectJob = null
        initialConnectJob?.cancel()
        initialConnectJob = null
        _state.update {
            it.copy(
                phase = LinkPhase.PAIRING,
                pairingBusy = true,
                pairingError = null,
                error = null,
                connectionDetail = "Connecting to ${desktop.displayName} — confirm on the desktop screen…",
            )
        }
        viewModelScope.launch {
            try {
                client.close()
                val opened = client.open(desktop.host, desktop.port, pin, null)
                if (!opened) throw IOException("Could not open the secure connection.")
                val result = client.pairCodeless(deviceName())
                val saved = StoredPairing(
                    deviceId = result.deviceId,
                    token = result.token,
                    desktopName = result.desktopName.ifBlank { desktop.displayName },
                    host = desktop.host,
                    port = desktop.port,
                    fingerprint = pin,
                )
                store.savePairing(saved)
                discovery.stop()
                _state.update {
                    it.copy(
                        paired = saved,
                        phase = LinkPhase.CONNECTED,
                        connectionDetail = "Connected to ${saved.desktopName}",
                        pairingBusy = false,
                        pairingError = null,
                        busy = false,
                        discovering = false,
                        certificateBlocked = false,
                        retryBlocked = false,
                        reconnectAttempt = 0,
                        notice = "Paired with ${saved.desktopName}. Hold the face and talk.",
                        reply = "",
                        replyProvider = null,
                        error = null,
                        activity = BerryActivity.HAPPY,
                    )
                }
                chirp(ToneGenerator.TONE_PROP_ACK)
                scheduleHappyToIdle()
            } catch (exc: Exception) {
                client.close()
                val message = userMessage(exc)
                _state.update {
                    it.copy(
                        phase = if (it.paired != null) LinkPhase.ERROR else LinkPhase.OFFLINE,
                        pairingBusy = false,
                        pairingError = message,
                        error = message,
                        connectionDetail = "Connect failed",
                        activity = BerryActivity.ERROR,
                    )
                }
                chirp(ToneGenerator.TONE_PROP_BEEP2)
                if (_state.value.paired == null) discovery.start()
            }
        }
        return true
    }

    /**
     * The big Connect button: discover the desktop this phone is standing next
     * to and join it. Already-paired phones just reconnect; fresh phones use
     * one-tap pairing (desktop allows with a single tap).
     */
    fun connectNearest() {
        val current = _state.value
        if (current.pairingBusy || current.busy) return
        if (current.paired != null) {
            reconnect()
            return
        }
        _state.update {
            it.copy(
                phase = LinkPhase.CONNECTING,
                connectionDetail = "Looking for BerryLink on this Wi-Fi…",
                discovering = true,
                pairingError = null,
            )
        }
        refreshDiscovery()
        viewModelScope.launch {
            repeat(12) {  // ~6 s of discovery polling
                delay(500)
                val state = _state.value
                if (state.phase == LinkPhase.PAIRING || state.phase == LinkPhase.CONNECTED) return@launch
                val found = state.discovered.firstOrNull()
                if (found != null) {
                    if (state.paired != null) {
                        connectToDesktop(found)
                    } else {
                        pairCodelessDesktop(found)
                    }
                    return@launch
                }
            }
            _state.update {
                it.copy(
                    phase = LinkPhase.OFFLINE,
                    connectionDetail = "No BerryLink found nearby.",
                    discovering = false,
                    pairingError = "No BerryLink desktop showed up. Is the desktop app open and on the same Wi-Fi?",
                )
            }
        }
    }

    fun startRecording(): Boolean {
        if (_state.value.recording) return false
        if (_state.value.busy) return false
        if (_state.value.phase != LinkPhase.CONNECTED) return false
        val speechReady = startSpeechRecognition()
        if (!speechReady && !recorder.start()) {
            _state.update {
                it.copy(error = "Microphone unavailable. Check the microphone permission and try again.")
            }
            return false
        }
        // Berry won't listen to himself talking over the hold.
        runCatching { tts?.stop() }
        usingSpeechRecognition = speechReady
        awaitingSpeechResults = false
        recordingStartedAt = SystemClock.elapsedRealtime()
        _state.update {
            it.copy(
                recording = true,
                recordingSeconds = 0f,
                inputLevel = 0f,
                speechText = "",
                busy = false,
                activity = BerryActivity.LISTENING,
                error = null,
                notice = null,
            )
        }
        chirp(ToneGenerator.TONE_PROP_ACK)
        recordingTicker?.cancel()
        recordingTicker = viewModelScope.launch {
            while (_state.value.recording) {
                val seconds = (SystemClock.elapsedRealtime() - recordingStartedAt) / 1000f
                _state.update { it.copy(recordingSeconds = seconds) }
                if (seconds >= 60f) {
                    finishRecordingAndAsk()
                    break
                }
                delay(100)
            }
        }
        return true
    }

    /**
     * Begin listening on the device's speech recognition engine (free, works
     * offline on many phones). Returns false when the device has none so the
     * caller falls back to recording raw audio.
     */
    private fun startSpeechRecognition(): Boolean {
        if (!SpeechRecognizer.isRecognitionAvailable(getApplication())) return false
        val created = runCatching {
            SpeechRecognizer.createSpeechRecognizer(getApplication())
        }.getOrNull() ?: return false
        created.setRecognitionListener(speechListener)
        val intent = Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH).apply {
            putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
            putExtra(RecognizerIntent.EXTRA_PARTIAL_RESULTS, true)
            putExtra(RecognizerIntent.EXTRA_MAX_RESULTS, 1)
        }
        val started = runCatching { created.startListening(intent) }.isSuccess
        if (!started) {
            runCatching { created.destroy() }
            return false
        }
        speechRecognizer = created
        return true
    }

    private fun destroySpeechRecognizer() {
        runCatching { speechRecognizer?.cancel() }
        runCatching { speechRecognizer?.destroy() }
        speechRecognizer = null
        usingSpeechRecognition = false
        awaitingSpeechResults = false
    }

    /** The live recognition callbacks; results drive the same ask pipeline. */
    private val speechListener = object : RecognitionListener {
        override fun onReadyForSpeech(params: Bundle?) {
            _state.update { it.copy(activity = BerryActivity.LISTENING, error = null) }
        }

        override fun onBeginningOfSpeech() {}

        override fun onRmsChanged(rmsdB: Float) {
            // -2 dB is silence in this API; +10 dB is loud speech.
            val level = ((rmsdB + 2f) / 10f).coerceIn(0f, 1f)
            _state.update { if (it.recording) it.copy(inputLevel = level) else it }
        }

        override fun onBufferReceived(buffer: ByteArray?) {}

        override fun onEndOfSpeech() {}

        override fun onError(error: Int) {
            if (!usingSpeechRecognition) return
            when (error) {
                SpeechRecognizer.ERROR_NO_MATCH,
                SpeechRecognizer.ERROR_SPEECH_TIMEOUT,
                SpeechRecognizer.ERROR_NETWORK_TIMEOUT,
                SpeechRecognizer.ERROR_NETWORK,
                -> finishSpeechWithText("")
                else -> {
                    // The recognizer died (busy/server/client error): fall back
                    // to the WAV recorder so the hold keeps working.
                    destroySpeechRecognizer()
                    fallbackToRecorder()
                }
            }
        }

        override fun onResults(results: Bundle?) {
            val text = results
                ?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)
                ?.firstOrNull()?.trim().orEmpty()
            finishSpeechWithText(text)
        }

        override fun onPartialResults(partialResults: Bundle?) {
            val text = partialResults
                ?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)
                ?.firstOrNull()?.trim().orEmpty()
            if (text.isNotEmpty()) {
                _state.update { it.copy(speechText = text.take(120)) }
            }
        }

        override fun onEvent(eventType: Int, params: Bundle?) {}
    }

    /** Stop the live hold and submit whatever was recognised ("" means nothing heard). */
    private fun finishSpeechWithText(text: String) {
        destroySpeechRecognizer()
        _state.update {
            it.copy(
                recording = false,
                recordingSeconds = 0f,
                inputLevel = 0f,
                speechText = "",
            )
        }
        if (_state.value.phase != LinkPhase.CONNECTED) {
            _state.update {
                it.copy(activity = BerryActivity.ERROR, error = "The desktop is offline. Reconnect before talking.")
            }
            return
        }
        if (text.isEmpty()) {
            _state.update {
                it.copy(
                    activity = BerryActivity.IDLE,
                    error = "Didn't catch anything. Hold a little longer and speak clearly.",
                )
            }
            chirp(ToneGenerator.TONE_PROP_BEEP2)
            return
        }
        chirp(ToneGenerator.TONE_PROP_BEEP)
        // The understood phrase drives everything, including "go to sleep":
        // the AI folds the face into the sleeping mood by itself.
        submitAsk(text = text, audio = null)
    }

    /** The recognizer failed mid-hold: switch the same hold to the recorder. */
    private fun fallbackToRecorder() {
        recordingTicker?.cancel()
        if (!recorder.start()) {
            _state.update {
                it.copy(
                    recording = false,
                    recordingSeconds = 0f,
                    inputLevel = 0f,
                    speechText = "",
                    activity = BerryActivity.IDLE,
                    error = "Speech recognition failed and the microphone could not start.",
                )
            }
            return
        }
        recordingStartedAt = SystemClock.elapsedRealtime()
        awaitingSpeechResults = false
        recordingTicker = viewModelScope.launch {
            while (_state.value.recording) {
                val seconds = (SystemClock.elapsedRealtime() - recordingStartedAt) / 1000f
                _state.update { it.copy(recordingSeconds = seconds) }
                if (seconds >= 60f) {
                    finishRecordingAndAsk()
                    break
                }
                delay(100)
            }
        }
    }

    fun cancelRecording() {
        if (!_state.value.recording) return
        recordingTicker?.cancel()
        recordingTicker = null
        destroySpeechRecognizer()
        recorder.cancel()
        _state.update {
            it.copy(
                recording = false,
                recordingSeconds = 0f,
                inputLevel = 0f,
                speechText = "",
                activity = BerryActivity.IDLE,
            )
        }
    }

    fun finishRecordingAndAsk() {
        if (!_state.value.recording) return
        if (usingSpeechRecognition) {
            recordingTicker?.cancel()
            recordingTicker = null
            if (awaitingSpeechResults) return
            awaitingSpeechResults = true
            runCatching { speechRecognizer?.stopListening() }
            // Wait briefly: results usually land well under a second. If the
            // engine goes silent, an empty transcript is submitted.
            viewModelScope.launch {
                delay(3500)
                if (awaitingSpeechResults && usingSpeechRecognition) {
                    finishSpeechWithText(
                        _state.value.speechText,
                    )
                }
            }
            return
        }
        recordingTicker?.cancel()
        recordingTicker = null
        val audio = recorder.stop()
        _state.update {
            it.copy(
                recording = false,
                recordingSeconds = 0f,
                inputLevel = 0f,
                speechText = "",
            )
        }
        if (audio == null) {
            _state.update {
                it.copy(
                    activity = BerryActivity.IDLE,
                    error = "That recording was too short or the microphone returned no audio. Hold a little longer.",
                )
            }
            chirp(ToneGenerator.TONE_PROP_BEEP2)
            return
        }
        if (_state.value.phase != LinkPhase.CONNECTED) {
            _state.update {
                it.copy(activity = BerryActivity.ERROR, error = "The desktop is offline. Reconnect before talking.")
            }
            return
        }
        chirp(ToneGenerator.TONE_PROP_BEEP)
        // Voice-driven sleep: if the clip says "go to sleep" (or goodnight),
        // the AI on the desktop calls go_to_sleep or answers with the sleepy
        // mood, which folds Berry straight into a nap. No special gesture.
        submitAsk(text = "", audio = audio.wav)
    }

    /** Tap-to-wake while napping; a gentle smile, then back to idle. */
    fun wakeFromSleep() {
        if (_state.value.activity != BerryActivity.SLEEPING) return
        _state.update {
            it.copy(
                activity = BerryActivity.HAPPY,
                notice = "Good sleep! Hold to talk.",
                reply = "",
                error = null,
            )
        }
        chirp(ToneGenerator.TONE_PROP_ACK)
        scheduleHappyToIdle()
    }

    /** Fold the face for a desktop-driven nap (the go_to_sleep tool / sleep event). */
    private fun putBerryToBed(notice: String) {
        _state.update {
            it.copy(
                activity = BerryActivity.SLEEPING,
                notice = notice,
                reply = "",
                replyProvider = null,
                error = null,
                busy = false,
            )
        }
    }

    fun askText(raw: String): Boolean {
        val text = raw.trim()
        if (text.isEmpty()) return false
        if (_state.value.phase != LinkPhase.CONNECTED) {
            _state.update { it.copy(error = "Connect to your desktop before asking.") }
            return false
        }
        if (_state.value.busy || _state.value.recording) return false
        submitAsk(text = text, audio = null)
        return true
    }

    /** Re-send the last failed/timed-out typed ask; no-op when there is nothing to retry. */
    fun retryLastAsk(): Boolean {
        val last = _state.value.lastAsk
        return last.isNotBlank() && askText(last)
    }

    fun resetConversation() {
        viewModelScope.launch {
            runCatching { client.resetConversation() }
            _state.update { it.copy(reply = "", replyProvider = null, notice = "Fresh conversation started.") }
        }
    }

    fun setTtsEnabled(enabled: Boolean) {
        store.setSpeakReplies(enabled)
        _state.update { it.copy(ttsEnabled = enabled) }
        if (!enabled) {
            speakJob?.cancel()
            tts?.stop()
            _state.update { it.copy(activity = BerryActivity.IDLE) }
        }
    }

    fun dismissError() {
        _state.update { it.copy(error = null, activity = if (it.activity == BerryActivity.ERROR) BerryActivity.IDLE else it.activity) }
    }

    fun clearPairingError() {
        _state.update { it.copy(pairingError = null) }
    }

    // --------------------------------------------------------------- network

    private fun connectSaved(manual: Boolean) {
        val saved = _state.value.paired
        if (saved == null) {
            Log.d(TAG, "connectSaved: no saved pairing, skipping")
            return
        }
        if (_state.value.retryBlocked) {
            Log.d(TAG, "connectSaved: retryBlocked, skipping")
            return
        }
        if (_state.value.phase == LinkPhase.CONNECTED || _state.value.phase == LinkPhase.PAIRING) return
        val match = _state.value.discovered.firstOrNull {
            Fingerprint.normalize(it.fingerprint) == saved.fingerprint
        }
        val host = match?.host ?: saved.host
        val port = match?.port ?: saved.port
        Log.d(
            TAG,
            "connectSaved: manual=$manual saved=${saved.host}:${saved.port} " +
                "discoveredMatch=${match != null} trying=$host:$port",
        )
        val endpointChanged = host != saved.host || port != saved.port
        val effective = if (endpointChanged) saved.copy(host = host, port = port) else saved
        if (endpointChanged) {
            runCatching { store.updateEndpoint(host, port) }
            _state.update { it.copy(paired = effective) }
        }
        if (!_state.value.discovering) discovery.start()
        _state.update {
            it.copy(
                phase = LinkPhase.CONNECTING,
                connectionDetail = "Connecting securely to ${effective.desktopName}…",
                error = if (manual) null else it.error,
                activity = if (it.activity == BerryActivity.ERROR) BerryActivity.IDLE else it.activity,
            )
        }
        val started = client.open(host, port, effective.fingerprint, effective)
        if (!started) {
            _state.update {
                it.copy(
                    phase = LinkPhase.ERROR,
                    connectionDetail = "Could not start a secure connection",
                    error = "Could not start the secure connection. Check the saved certificate pin.",
                    activity = BerryActivity.ERROR,
                )
            }
        }
    }

    private fun onClientEvent(event: ClientEvent) {
        when (event) {
            ClientEvent.Opened -> {
                _state.update {
                    if (it.phase == LinkPhase.PAIRING) {
                        it.copy(connectionDetail = "Verifying the pairing code…")
                    } else {
                        it.copy(connectionDetail = "Authenticating…")
                    }
                }
            }
            is ClientEvent.Authenticated -> {
                reconnectJob?.cancel()
                reconnectJob = null
                discovery.stop()
                Log.d(TAG, "Authenticated to ${event.desktopName}")
                _state.update {
                    it.copy(
                        phase = LinkPhase.CONNECTED,
                        connectionDetail = "Connected to ${event.desktopName}",
                        discovering = false,
                        certificateBlocked = false,
                        retryBlocked = false,
                        reconnectAttempt = 0,
                        error = null,
                        cursorGaze = null,
                        activity = if (it.busy || it.recording) it.activity else BerryActivity.IDLE,
                    )
                }
            }
            is ClientEvent.ConnectionFailed -> {
                if (_state.value.pairingBusy) {
                    // The pair coroutine owns the visible error and cleanup.
                    return
                }
                Log.d(
                    TAG,
                    "ConnectionFailed: msg=${event.message} pinMismatch=${event.pinMismatch} " +
                        "authFailed=${event.authenticationFailed} phase=${_state.value.phase}",
                )
                val blocked = event.pinMismatch || event.authenticationFailed
                _state.update {
                    it.copy(
                        phase = LinkPhase.ERROR,
                        connectionDetail = if (blocked) "Connection blocked for safety" else "Offline",
                        error = event.message,
                        certificateBlocked = event.pinMismatch,
                        retryBlocked = blocked,
                        activity = if (event.pinMismatch || event.authenticationFailed) {
                            BerryActivity.ERROR
                        } else {
                            BerryActivity.IDLE
                        },
                        cursorGaze = null,
                    )
                }
                if (blocked) {
                    chirp(ToneGenerator.TONE_PROP_BEEP2)
                } else {
                    if (!_state.value.discovering) discovery.start()
                    scheduleReconnect()
                }
            }
            is ClientEvent.Closed -> {
                if (_state.value.pairingBusy) return
                _state.update {
                    it.copy(
                        phase = LinkPhase.OFFLINE,
                        connectionDetail = "Desktop disconnected",
                        activity = if (it.busy || it.recording) it.activity else BerryActivity.IDLE,
                        cursorGaze = null,
                    )
                }
                if (!_state.value.discovering) discovery.start()
                scheduleReconnect()
            }
            is ClientEvent.DesktopEvent -> handleDesktopEvent(event)
        }
    }

    private fun handleDesktopEvent(event: ClientEvent.DesktopEvent) {
        when (event.method) {
            // The PC cursor is streamed continuously while paired.  It is the
            // phone's default gaze; the local touch override in the face UI
            // only wins while a finger is actually down.
            "cursor" -> {
                val x = event.message.number("x") ?: return
                val y = event.message.number("y") ?: return
                _state.update {
                    it.copy(
                        cursorGaze = GazePoint(
                            x.coerceIn(-1.0f, 1.0f),
                            y.coerceIn(-1.0f, 1.0f),
                        )
                    )
                }
            }
            "sleep" -> {
                // The desktop asked Berry to nap (e.g. its AI chose go_to_sleep
                // or the user said goodnight). Fold the face locally.
                putBerryToBed(notice = "Zzz… Berry is asleep. Tap him to wake him up.")
            }
            "emergency", "control.changed" -> {
                val active = event.message.boolean("active")
                    ?: event.message.boolean("emergency_stop")
                    ?: false
                val incoming = event.message.text("message")
                if (active) {
                    _state.update {
                        it.copy(
                            activity = BerryActivity.ERROR,
                            error = incoming ?: "Emergency stop is active on the desktop.",
                        )
                    }
                } else if (event.method == "emergency") {
                    _state.update {
                        it.copy(
                            error = null,
                            activity = if (it.activity == BerryActivity.ERROR) BerryActivity.IDLE else it.activity,
                        )
                    }
                }
            }
        }
    }

    private fun scheduleReconnect() {
        val saved = _state.value.paired ?: return
        if (_state.value.retryBlocked || _state.value.certificateBlocked) return
        if (reconnectJob?.isActive == true) return
        reconnectJob = viewModelScope.launch {
            delay(1400)
            if (_state.value.phase == LinkPhase.CONNECTED || _state.value.paired == null) return@launch
            val attempt = _state.value.reconnectAttempt + 1
            val waitMs = (1500.0 * 1.7.pow((attempt - 1).coerceAtMost(5))).roundToInt().coerceAtMost(20_000)
            _state.update {
                it.copy(
                    reconnectAttempt = attempt,
                    connectionDetail = "Reconnecting in ${(waitMs + 999) / 1000}s…",
                )
            }
            delay(waitMs.toLong())
            if (_state.value.phase == LinkPhase.CONNECTED || _state.value.paired == null) return@launch
            connectSaved(manual = false)
        }
    }

    private fun submitAsk(text: String, audio: ByteArray?) {
        if (_state.value.busy) return
        _state.update {
            it.copy(
                busy = true,
                activity = BerryActivity.THINKING,
                error = null,
                notice = null,
                replyProvider = null,
                lastAsk = if (text.isNotBlank()) text else it.lastAsk,
            )
        }
        viewModelScope.launch {
            try {
                val reply = client.ask(text, audio)
                // The AI's trailing mood drives Berry's face: sleepy replies
                // fold him straight into a nap, happy ones beam, oops ones worry.
                val mood = reply.mood.lowercase()
                // If the go_to_sleep tool already fired mid-ask ("sleep" event),
                // a generic mood tag must not un-fold him again.
                val keepSleeping = _state.value.activity == BerryActivity.SLEEPING &&
                    !mood.contains("wake") &&
                    !mood.contains("excit") &&
                    !mood.contains("happy")
                val moodActivity = when {
                    keepSleeping || mood.contains("sleep") -> BerryActivity.SLEEPING
                    mood.contains("excit") || mood.contains("happy") -> BerryActivity.HAPPY
                    mood.contains("error") || mood.contains("oops") || mood.contains("worried") -> BerryActivity.ERROR
                    else -> BerryActivity.SPEAKING
                }
                _state.update {
                    it.copy(
                        busy = false,
                        reply = reply.reply,
                        replyProvider = reply.provider,
                        notice = reply.notice,
                        activity = moodActivity,
                        error = null,
                    )
                }
                speak(reply.reply, mood)
            } catch (exc: Exception) {
                _state.update {
                    it.copy(
                        busy = false,
                        activity = BerryActivity.ERROR,
                        error = userMessage(exc),
                    )
                }
                chirp(ToneGenerator.TONE_PROP_BEEP2)
            }
        }
    }

    // -------------------------------------------------------------- discovery

    private fun onDiscovered(list: List<DiscoveredDesktop>) {
        val saved = _state.value.paired
        var endpointUpdated = false
        var newSaved = saved
        if (saved != null) {
            val match = list.firstOrNull { Fingerprint.normalize(it.fingerprint) == saved.fingerprint }
            if (match != null && (match.host != saved.host || match.port != saved.port)) {
                newSaved = saved.copy(host = match.host, port = match.port)
                store.updateEndpoint(match.host, match.port)
                endpointUpdated = true
            }
        }
        _state.update {
            it.copy(
                discovered = list,
                paired = newSaved,
                discovering = true,
            )
        }
        if (
            endpointUpdated &&
            newSaved != null &&
            _state.value.phase != LinkPhase.CONNECTED &&
            _state.value.phase != LinkPhase.CONNECTING &&
            _state.value.phase != LinkPhase.PAIRING &&
            reconnectJob?.isActive != true &&
            !_state.value.retryBlocked
        ) {
            connectSaved(manual = false)
        }
    }

    private fun onDiscoveryStatus(message: String, failed: Boolean) {
        _state.update {
            it.copy(
                discoveryMessage = message,
                discovering = if (failed) false else it.discovering,
            )
        }
    }

    // ------------------------------------------------------------------- TTS

    /**
     * System TTS engines ship several English voices; the plain default is the
     * tinny robotic one. Pick the best-sounding voice the engine actually has:
     * highest quality first (VERY_HIGH network voices > ENHANCED > NORMAL),
     * with a nudge for the warmer Google "tpd"/"iom" builds, and stop at the
     * first one the engine accepts. Everything fails closed to the engine
     * default voice, which is still fine.
     */
    private fun pickMostHumanVoice(engine: TextToSpeech) {
        val candidates = engine.voices.orEmpty().asSequence()
            .filter { it.locale.language == "en" && it.name != null && it.name.isNotBlank() }
            .filter { it.quality >= 300 }  // QUALITY_ENHANCED / VERY_HIGH network builds
            .sortedWith(
                compareByDescending<Voice> { it.quality }
                    .thenByDescending { voiceNameScore(it.name) },
            )
            .toList()
        for (voice in candidates) {
            val applied = runCatching { engine.setVoice(voice) }
                .getOrDefault(TextToSpeech.ERROR)
            if (applied == TextToSpeech.SUCCESS) return
        }
    }

    private fun voiceNameScore(name: String): Int = when {
        "tpd" in name -> 3   // Google's warm US female network build
        "iom" in name -> 2
        "ynet" in name || "network" in name.lowercase() -> 1
        else -> 0
    }

    private fun initTts() {
        tts = TextToSpeech(getApplication()) { status ->
            val engine = tts ?: return@TextToSpeech
            ttsInitDone = true
            ttsReady = status == TextToSpeech.SUCCESS
            if (ttsReady) {
                val language = engine.setLanguage(Locale.US)
                if (language == TextToSpeech.LANG_MISSING_DATA || language == TextToSpeech.LANG_NOT_SUPPORTED) {
                    ttsReady = false
                } else {
                    // Human-sounding settings: slightly slower than default on
                    // the natural high-quality engine voices, near-neutral
                    // pitch instead of the old chipmunk 1.12.
                    engine.setSpeechRate(0.95f)
                    engine.setPitch(1.05f)
                    pickMostHumanVoice(engine)
                }
                engine.setOnUtteranceProgressListener(object : UtteranceProgressListener() {
                    override fun onStart(utteranceId: String?) {
                        // Keep a mood-driven nap through the spoken reply (e.g.
                        // a goodnight answer): don't wake him just to talk.
                        _state.update {
                            it.copy(
                                activity = if (it.activity == BerryActivity.SLEEPING) {
                                    BerryActivity.SLEEPING
                                } else {
                                    BerryActivity.SPEAKING
                                },
                            )
                        }
                    }

                    override fun onDone(utteranceId: String?) {
                        finishSpeaking()
                    }

                    @Deprecated("Deprecated in Java")
                    override fun onError(utteranceId: String?) {
                        finishSpeaking()
                    }

                    override fun onError(utteranceId: String?, errorCode: Int) {
                        finishSpeaking()
                    }

                    override fun onStop(utteranceId: String?, interrupted: Boolean) {
                        finishSpeaking()
                    }
                })
            }
            val queued = pendingSpeech
            if (queued != null && ttsReady) {
                pendingSpeech = null
                speakNow(queued)
            } else if (queued != null) {
                pendingSpeech = null
                finishSpeaking()
            }
        }
    }

    private fun speak(text: String, mood: String = "happy") {
        val sleepy = mood.contains("sleep")
        speakJob?.cancel()
        if (!_state.value.ttsEnabled || text.isBlank()) {
            _state.update {
                it.copy(activity = if (sleepy) BerryActivity.SLEEPING else BerryActivity.HAPPY)
            }
            if (!sleepy) scheduleHappyToIdle()
            return
        }
        pendingSpeech = text
        if (ttsReady) {
            pendingSpeech = null
            speakNow(text)
        } else if (ttsInitDone) {
            pendingSpeech = null
            _state.update {
                it.copy(activity = if (sleepy) BerryActivity.SLEEPING else BerryActivity.HAPPY)
            }
            if (!sleepy) scheduleHappyToIdle()
        }
    }

    private fun speakNow(text: String) {
        val engine = tts ?: return
        val clipped = text.take(1800)
        val result = runCatching {
            engine.speak(clipped, TextToSpeech.QUEUE_FLUSH, null, "berrylink-reply")
        }.getOrDefault(TextToSpeech.ERROR)
        if (result != TextToSpeech.SUCCESS) {
            finishSpeaking()
        }
    }

    private fun finishSpeaking() {
        viewModelScope.launch {
            _state.update {
                if (it.activity == BerryActivity.SPEAKING) it.copy(activity = BerryActivity.HAPPY) else it
            }
            delay(1500)
            _state.update {
                if (it.activity == BerryActivity.HAPPY) it.copy(activity = BerryActivity.IDLE) else it
            }
        }
    }

    private fun scheduleHappyToIdle() {
        viewModelScope.launch {
            delay(2200)
            _state.update {
                if (it.activity == BerryActivity.HAPPY) it.copy(activity = BerryActivity.IDLE) else it
            }
        }
    }

    private fun chirp(toneType: Int) {
        runCatching { tone?.startTone(toneType, 80) }
    }

    private fun deviceName(): String {
        val model = Build.MODEL?.trim().orEmpty().ifBlank { "Android phone" }
        return "$model (Android)".take(64)
    }

    private fun userMessage(exc: Throwable): String {
        if (exc is RemoteException) return exc.message
        if (exc is java.util.concurrent.TimeoutException) return "The desktop took too long to answer."
        if (exc is kotlinx.coroutines.TimeoutCancellationException) return "The desktop took too long to answer."
        if (exc is java.net.SocketTimeoutException) return "The connection timed out. Check that the desktop is awake."
        if (exc is java.net.ConnectException) return "Connection refused. Is BerryLink running on the desktop?"
        if (exc is java.net.UnknownHostException) return "That desktop address could not be resolved."
        if (exc is javax.net.ssl.SSLException) {
            return "The secure connection failed. The desktop certificate may have changed; pair again."
        }
        return exc.message?.takeIf { it.isNotBlank() }
            ?: "Something went wrong talking to the desktop."
    }

    override fun onCleared() {
        reconnectJob?.cancel()
        initialConnectJob?.cancel()
        recordingTicker?.cancel()
        speakJob?.cancel()
        destroySpeechRecognizer()
        recorder.cancel()
        discovery.stop()
        client.close()
        runCatching {
            tts?.stop()
            tts?.shutdown()
        }
        tts = null
        runCatching { tone?.release() }
        super.onCleared()
    }
}
