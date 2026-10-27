package app.berrylink.companion.audio

import java.io.ByteArrayOutputStream
import java.nio.ByteBuffer
import java.nio.ByteOrder

object WavWriter {
    fun wrapPcm16(
        pcm: ByteArray,
        sampleRate: Int = 16_000,
        channels: Int = 1,
    ): ByteArray {
        require(sampleRate > 0)
        require(channels in 1..2)
        val bitsPerSample = 16
        val blockAlign = channels * bitsPerSample / 8
        val byteRate = sampleRate * blockAlign
        val dataSize = pcm.size
        val padding = dataSize and 1
        val out = ByteArrayOutputStream(44 + dataSize + padding)
        out.write("RIFF".toByteArray(Charsets.US_ASCII))
        out.write(le32(36 + dataSize + padding))
        out.write("WAVE".toByteArray(Charsets.US_ASCII))
        out.write("fmt ".toByteArray(Charsets.US_ASCII))
        out.write(le32(16))
        out.write(le16(1)) // PCM
        out.write(le16(channels))
        out.write(le32(sampleRate))
        out.write(le32(byteRate))
        out.write(le16(blockAlign))
        out.write(le16(bitsPerSample))
        out.write("data".toByteArray(Charsets.US_ASCII))
        out.write(le32(dataSize + padding))
        out.write(pcm)
        if (padding == 1) out.write(0)
        return out.toByteArray()
    }

    private fun le16(value: Int): ByteArray =
        ByteBuffer.allocate(2).order(ByteOrder.LITTLE_ENDIAN).putShort(value.toShort()).array()

    private fun le32(value: Int): ByteArray =
        ByteBuffer.allocate(4).order(ByteOrder.LITTLE_ENDIAN).putInt(value).array()
}
