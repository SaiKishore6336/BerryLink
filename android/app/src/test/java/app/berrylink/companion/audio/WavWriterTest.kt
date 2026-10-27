package app.berrylink.companion.audio

import org.junit.Assert.assertEquals
import org.junit.Assert.fail
import org.junit.Test
import java.nio.ByteBuffer
import java.nio.ByteOrder

class WavWriterTest {
    @Test
    fun writesRiffHeaderForMono16kPcm() {
        val pcm = byteArrayOf(1, 2, 3, 4)
        val wav = WavWriter.wrapPcm16(pcm, 16_000, 1)
        assertEquals(48, wav.size)
        assertEquals("RIFF", ascii(wav, 0, 4))
        assertEquals(40, le32(wav, 4))
        assertEquals("WAVE", ascii(wav, 8, 4))
        assertEquals("fmt ", ascii(wav, 12, 4))
        assertEquals(16, le32(wav, 16))
        assertEquals(1, le16(wav, 20))
        assertEquals(1, le16(wav, 22))
        assertEquals(16_000, le32(wav, 24))
        assertEquals(32_000, le32(wav, 28))
        assertEquals(2, le16(wav, 32))
        assertEquals(16, le16(wav, 34))
        assertEquals("data", ascii(wav, 36, 4))
        assertEquals(4, le32(wav, 40))
        assertEquals(pcm.toList(), wav.drop(44).toList())
    }

    @Test
    fun padsOddLengthPcm() {
        val pcm = byteArrayOf(9, 8, 7, 6, 5)
        val wav = WavWriter.wrapPcm16(pcm, 8_000, 1)
        assertEquals(50, wav.size)
        assertEquals(42, le32(wav, 4))
        assertEquals(8_000, le32(wav, 24))
        assertEquals(16_000, le32(wav, 28))
        assertEquals(6, le32(wav, 40))
        assertEquals(0, wav.last().toInt())
        assertEquals(pcm.toList(), wav.drop(44).take(5).toList())
    }

    @Test
    fun supportsStereoAndRejectsBadSettings() {
        val wav = WavWriter.wrapPcm16(byteArrayOf(0, 0, 0, 0), 44_100, 2)
        assertEquals(2, le16(wav, 22))
        assertEquals(44_100, le32(wav, 24))
        assertEquals(176_400, le32(wav, 28))
        assertEquals(4, le16(wav, 32))
        try {
            WavWriter.wrapPcm16(byteArrayOf(), 0, 1)
            fail("accepted a zero sample rate")
        } catch (_: IllegalArgumentException) {
            // expected
        }
        try {
            WavWriter.wrapPcm16(byteArrayOf(), 16_000, 3)
            fail("accepted three channels")
        } catch (_: IllegalArgumentException) {
            // expected
        }
    }

    private fun ascii(data: ByteArray, offset: Int, length: Int): String =
        String(data, offset, length, Charsets.US_ASCII)

    private fun le16(data: ByteArray, offset: Int): Int =
        ByteBuffer.wrap(data, offset, 2).order(ByteOrder.LITTLE_ENDIAN).short.toInt() and 0xffff

    private fun le32(data: ByteArray, offset: Int): Int =
        ByteBuffer.wrap(data, offset, 4).order(ByteOrder.LITTLE_ENDIAN).int
}
