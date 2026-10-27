package app.berrylink.companion.audio

import android.annotation.SuppressLint
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.MediaRecorder
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import java.io.ByteArrayOutputStream
import kotlin.math.max
import kotlin.math.min
import kotlin.math.sqrt

data class RecordedAudio(
    val wav: ByteArray,
    val seconds: Float,
)

/**
 * Small, memory-bounded mono WAV recorder for hold-to-talk.
 * A 60 second ask at 16 kHz is about 1.9 MB, well below the gateway cap.
 */
class WavRecorder {
    companion object {
        const val SAMPLE_RATE = 16_000
        const val MAX_SECONDS = 60
        private const val MAX_BYTES = SAMPLE_RATE * 2 * (MAX_SECONDS + 1)
    }

    private val _amplitude = MutableStateFlow(0f)
    val amplitude: StateFlow<Float> = _amplitude

    private val lock = Any()
    private var record: AudioRecord? = null
    private var worker: Thread? = null
    private var output: ByteArrayOutputStream? = null
    @Volatile private var running = false
    @Volatile private var startedAt = 0L
    @Volatile private var readFailure: String? = null

    val isRecording: Boolean
        get() = running

    @SuppressLint("MissingPermission")
    fun start(): Boolean {
        synchronized(lock) {
            if (running) return false
            val minBuffer = AudioRecord.getMinBufferSize(
                SAMPLE_RATE,
                AudioFormat.CHANNEL_IN_MONO,
                AudioFormat.ENCODING_PCM_16BIT,
            )
            if (minBuffer <= 0) return false
            val bufferSize = max(minBuffer * 2, SAMPLE_RATE / 4 * 2)
            val audioRecord = try {
                AudioRecord(
                    MediaRecorder.AudioSource.MIC,
                    SAMPLE_RATE,
                    AudioFormat.CHANNEL_IN_MONO,
                    AudioFormat.ENCODING_PCM_16BIT,
                    bufferSize,
                )
            } catch (_: Exception) {
                return false
            }
            if (audioRecord.state != AudioRecord.STATE_INITIALIZED) {
                audioRecord.release()
                return false
            }
            val sink = ByteArrayOutputStream(MAX_BYTES.coerceAtMost(512 * 1024))
            try {
                audioRecord.startRecording()
            } catch (_: Exception) {
                audioRecord.release()
                return false
            }
            if (audioRecord.recordingState != AudioRecord.RECORDSTATE_RECORDING) {
                audioRecord.release()
                return false
            }
            record = audioRecord
            output = sink
            readFailure = null
            startedAt = System.nanoTime()
            running = true
            _amplitude.value = 0f
            worker = Thread({ readLoop(audioRecord, sink) }, "berrylink-wav-recorder").apply {
                isDaemon = true
                start()
            }
            return true
        }
    }

    fun stop(): RecordedAudio? {
        val sink: ByteArrayOutputStream
        val recordRef: AudioRecord?
        synchronized(lock) {
            if (!running && record == null) return null
            running = false
            recordRef = record
            sink = output ?: return null
            record = null
            output = null
        }
        try {
            recordRef?.stop()
        } catch (_: Exception) {
        }
        try {
            worker?.join(1200)
        } catch (_: InterruptedException) {
            Thread.currentThread().interrupt()
        }
        worker = null
        recordRef?.release()
        _amplitude.value = 0f
        val elapsed = if (startedAt > 0) (System.nanoTime() - startedAt) / 1_000_000_000f else 0f
        val pcm = sink.toByteArray()
        if (pcm.size < 3200 || elapsed < 0.35f || readFailure != null) return null
        val seconds = min(elapsed, MAX_SECONDS.toFloat())
        return RecordedAudio(WavWriter.wrapPcm16(pcm, SAMPLE_RATE, 1), seconds)
    }

    fun cancel() {
        val recordRef: AudioRecord?
        synchronized(lock) {
            running = false
            recordRef = record
            record = null
            output = null
        }
        try {
            recordRef?.stop()
        } catch (_: Exception) {
        }
        try {
            worker?.join(500)
        } catch (_: InterruptedException) {
            Thread.currentThread().interrupt()
        }
        worker = null
        recordRef?.release()
        _amplitude.value = 0f
    }

    private fun readLoop(audioRecord: AudioRecord, sink: ByteArrayOutputStream) {
        val chunk = ByteArray(4096)
        val started = System.nanoTime()
        var lastMeter = 0L
        while (running) {
            if (sink.size() >= MAX_BYTES) break
            if ((System.nanoTime() - started) / 1_000_000_000L >= MAX_SECONDS.toLong()) break
            val read = try {
                audioRecord.read(chunk, 0, chunk.size)
            } catch (_: Exception) {
                -1
            }
            if (read > 0) {
                sink.write(chunk, 0, read)
                val now = System.nanoTime()
                if (now - lastMeter > 55_000_000L) {
                    lastMeter = now
                    _amplitude.value = rms(chunk, read)
                }
            } else if (read < 0) {
                readFailure = "Microphone read failed."
                break
            }
        }
        running = false
    }

    private fun rms(buffer: ByteArray, length: Int): Float {
        if (length < 2) return 0f
        var sum = 0.0
        var samples = 0
        var i = 0
        while (i + 1 < length) {
            val value = (buffer[i].toInt() and 0xff) or (buffer[i + 1].toInt() shl 8)
            val signed = value.toShort().toInt()
            sum += signed.toDouble() * signed
            samples++
            i += 2
        }
        if (samples == 0) return 0f
        val normalized = sqrt(sum / samples) / 32768.0
        return (normalized * 5.0).coerceIn(0.0, 1.0).toFloat()
    }
}
