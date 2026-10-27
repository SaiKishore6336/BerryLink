package app.berrylink.companion.security

import java.security.SecureRandom
import java.security.cert.CertificateException
import java.security.cert.X509Certificate
import javax.net.ssl.HostnameVerifier
import javax.net.ssl.SSLContext
import javax.net.ssl.SSLSession
import javax.net.ssl.SSLSocketFactory
import javax.net.ssl.X509TrustManager

/**
 * Exact leaf-certificate pinning for the self-signed BerryLink desktop.
 *
 * The normal CA chain is not used.  Hostname checks are also replaced with the
 * pin check because a LAN IP often does not match the desktop's certificate
 * subject.  The connection is refused unless the SHA-256 of the presented leaf
 * certificate equals the pin shown by mDNS or copied from the desktop.
 */
class PinnedTls private constructor(
    val fingerprint: String,
    val socketFactory: SSLSocketFactory,
    val trustManager: X509TrustManager,
    val hostnameVerifier: HostnameVerifier,
) {
    companion object {
        fun forFingerprint(expected: String): PinnedTls {
            val normalized = Fingerprint.normalize(expected)
                ?: throw IllegalArgumentException("The certificate fingerprint must be 64 hexadecimal characters.")
            val trustManager = object : X509TrustManager {
                override fun checkClientTrusted(chain: Array<out X509Certificate>?, authType: String?) {
                    throw CertificateException("Client certificates are not used.")
                }

                override fun checkServerTrusted(chain: Array<out X509Certificate>?, authType: String?) {
                    val leaf = chain?.firstOrNull()
                        ?: throw CertificateException("The desktop sent no certificate.")
                    val actual = Fingerprint.sha256(leaf)
                    if (actual != normalized) {
                        throw CertificateException("Desktop certificate pin mismatch.")
                    }
                }

                override fun getAcceptedIssuers(): Array<X509Certificate> = emptyArray()
            }
            val context = SSLContext.getInstance("TLS")
            context.init(null, arrayOf(trustManager), SecureRandom())
            val verifier = HostnameVerifier { _, session: SSLSession? ->
                val leaf = session?.peerCertificates?.firstOrNull() as? X509Certificate
                leaf != null && Fingerprint.sha256(leaf) == normalized
            }
            return PinnedTls(normalized, context.socketFactory, trustManager, verifier)
        }

        fun looksLikePinMismatch(error: Throwable?): Boolean {
            var current = error
            var depth = 0
            while (current != null && depth < 10) {
                val message = current.message.orEmpty().lowercase()
                if (
                    current is CertificateException ||
                    "pin mismatch" in message ||
                    "certificate pin" in message ||
                    "trust anchor" in message
                ) {
                    return true
                }
                current = current.cause
                depth += 1
            }
            return false
        }
    }
}
