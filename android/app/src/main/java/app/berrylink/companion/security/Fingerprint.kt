package app.berrylink.companion.security

import java.security.MessageDigest
import java.security.cert.X509Certificate

object Fingerprint {
    private val hex = Regex("[0-9A-Fa-f]")

    fun normalize(raw: String?): String? {
        if (raw == null) return null
        val clean = raw.filter { it.toString().matches(hex) }.uppercase()
        return clean.takeIf { it.length == 64 }
    }

    fun sha256(certificate: X509Certificate): String {
        val digest = MessageDigest.getInstance("SHA-256").digest(certificate.encoded)
        return digest.joinToString("") { "%02X".format(it) }
    }

    fun pretty(normalized: String): String =
        normalized.chunked(2).joinToString(":")

    fun short(normalized: String): String {
        val pretty = pretty(normalized)
        return if (pretty.length > 23) "${pretty.take(23)}…" else pretty
    }
}
