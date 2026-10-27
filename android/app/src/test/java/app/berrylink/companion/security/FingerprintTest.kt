package app.berrylink.companion.security

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class FingerprintTest {
    private val pin =
        "A1B2C3D4E5F60718293A4B5C6D7E8F90" +
            "112233445566778899AABBCCDDEEFF00"

    @Test
    fun normalizeAcceptsColonsAndLowercase() {
        val formatted = pin.lowercase().chunked(2).joinToString(":")
        assertEquals(pin, Fingerprint.normalize(formatted))
    }

    @Test
    fun normalizeAcceptsSpacesAndSurroundingWhitespace() {
        assertEquals(pin, Fingerprint.normalize("  $pin  "))
        assertEquals(pin, Fingerprint.normalize(pin.chunked(2).joinToString(" ")))
    }

    @Test
    fun normalizeRejectsWrongLengthAndNonHex() {
        assertNull(Fingerprint.normalize(null))
        assertNull(Fingerprint.normalize(""))
        assertNull(Fingerprint.normalize(pin.dropLast(1)))
        assertNull(Fingerprint.normalize(pin + "AA"))
        assertNull(Fingerprint.normalize("Z" + pin.drop(1)))
    }

    @Test
    fun prettyAndShortUseColonPairs() {
        assertEquals(pin.chunked(2).joinToString(":"), Fingerprint.pretty(pin))
        assertEquals("A1:B2:C3:D4:E5:F6:07:18…", Fingerprint.short(pin))
    }
}
