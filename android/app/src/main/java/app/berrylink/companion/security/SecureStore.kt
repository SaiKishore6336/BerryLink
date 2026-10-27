package app.berrylink.companion.security

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import android.util.Log
import app.berrylink.companion.model.StoredPairing
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

/**
 * Stores the pairing token encrypted with a non-exportable Android Keystore
 * key.  No Gemini key is ever stored on the phone.
 */
class SecureStore(context: Context) {
    private val prefs = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)

    /** Reason a saved pairing was rejected while loading; read after loadPairing(). */
    var lastLoadIssue: String? = null
        private set

    fun loadPairing(): StoredPairing? {
        val deviceId = prefs.getString(KEY_DEVICE_ID, null)
        val encryptedToken = prefs.getString(KEY_TOKEN, null)
        val desktopName = prefs.getString(KEY_DESKTOP_NAME, null)
        val host = prefs.getString(KEY_HOST, null)
        val port = prefs.getInt(KEY_PORT, 0)
        val fingerprintRaw = prefs.getString(KEY_FINGERPRINT, null)
        if (deviceId == null || encryptedToken == null) {
            Log.d(TAG, "loadPairing: nothing saved (deviceId=${deviceId != null}, token=${encryptedToken != null})")
            lastLoadIssue = null
            return null
        }
        val fingerprint = Fingerprint.normalize(fingerprintRaw)
        if (fingerprint == null) {
            Log.d(TAG, "loadPairing: saved pin unreadable (raw=$fingerprintRaw)")
            lastLoadIssue = "Saved certificate pin is unreadable."
            return null
        }
        if (port !in 1..65535) {
            Log.d(TAG, "loadPairing: saved port invalid ($port)")
            lastLoadIssue = "Saved desktop port ($port) is invalid."
            return null
        }
        if (host == null) {
            Log.d(TAG, "loadPairing: saved host missing")
            lastLoadIssue = "Saved desktop address is missing."
            return null
        }
        val token = runCatching { decrypt(encryptedToken) }
            .onFailure { Log.d(TAG, "loadPairing: decrypt failed", it) }
            .getOrNull()
        if (token == null || token.isEmpty()) {
            Log.d(TAG, "loadPairing: token empty after decrypt (len=${token?.length})")
            lastLoadIssue = "Stored key could not be decrypted (device security reset?). Pair once more."
            return null
        }
        Log.d(TAG, "loadPairing: ok device=$deviceId host=$host:$port pin=${Fingerprint.short(fingerprint)}")
        lastLoadIssue = null
        return StoredPairing(deviceId, token, desktopName ?: "Desktop", host, port, fingerprint)
    }

    fun savePairing(pairing: StoredPairing) {
        require(Fingerprint.normalize(pairing.fingerprint) != null) { "Invalid certificate pin" }
        val encrypted = encrypt(pairing.token)
        prefs.edit()
            .putString(KEY_DEVICE_ID, pairing.deviceId)
            .putString(KEY_TOKEN, encrypted)
            .putString(KEY_DESKTOP_NAME, pairing.desktopName)
            .putString(KEY_HOST, pairing.host)
            .putInt(KEY_PORT, pairing.port)
            .putString(KEY_FINGERPRINT, pairing.fingerprint.uppercase())
            .apply()
        lastLoadIssue = null
        Log.d(TAG, "savePairing: device=${pairing.deviceId} host=${pairing.host}:${pairing.port}")
    }

    fun updateEndpoint(host: String, port: Int) {
        prefs.edit().putString(KEY_HOST, host).putInt(KEY_PORT, port).apply()
    }

    fun clearPairing() {
        prefs.edit()
            .remove(KEY_DEVICE_ID)
            .remove(KEY_TOKEN)
            .remove(KEY_DESKTOP_NAME)
            .remove(KEY_HOST)
            .remove(KEY_PORT)
            .remove(KEY_FINGERPRINT)
            .apply()
        lastLoadIssue = null
    }

    fun speakReplies(): Boolean = prefs.getBoolean(KEY_TTS, true)

    fun setSpeakReplies(enabled: Boolean) {
        prefs.edit().putBoolean(KEY_TTS, enabled).apply()
    }

    private fun key(): SecretKey {
        val keyStore = KeyStore.getInstance(ANDROID_KEYSTORE).apply { load(null) }
        (keyStore.getEntry(KEY_ALIAS, null) as? KeyStore.SecretKeyEntry)?.secretKey?.let { return it }
        val generator = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, ANDROID_KEYSTORE)
        val spec = KeyGenParameterSpec.Builder(
            KEY_ALIAS,
            KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT,
        )
            .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
            .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
            .setKeySize(256)
            .setUserAuthenticationRequired(false)
            .build()
        generator.init(spec)
        return generator.generateKey()
    }

    private fun encrypt(plainText: String): String {
        val cipher = Cipher.getInstance(TRANSFORMATION)
        cipher.init(Cipher.ENCRYPT_MODE, key())
        val encrypted = cipher.doFinal(plainText.toByteArray(Charsets.UTF_8))
        val iv = Base64.encodeToString(cipher.iv, Base64.NO_WRAP)
        val body = Base64.encodeToString(encrypted, Base64.NO_WRAP)
        return "$iv:$body"
    }

    private fun decrypt(encoded: String): String {
        val separator = encoded.indexOf(':')
        require(separator > 0) { "Malformed token" }
        val iv = Base64.decode(encoded.substring(0, separator), Base64.NO_WRAP)
        val body = Base64.decode(encoded.substring(separator + 1), Base64.NO_WRAP)
        val cipher = Cipher.getInstance(TRANSFORMATION)
        cipher.init(Cipher.DECRYPT_MODE, key(), GCMParameterSpec(128, iv))
        return cipher.doFinal(body).toString(Charsets.UTF_8)
    }

    private companion object {
        private const val TAG = "BerryLinkSecureStore"
        const val PREFS = "berrylink_secure"
        const val ANDROID_KEYSTORE = "AndroidKeyStore"
        const val TRANSFORMATION = "AES/GCM/NoPadding"
        const val KEY_ALIAS = "berrylink_pairing_token_v1"
        const val KEY_DEVICE_ID = "device_id"
        const val KEY_TOKEN = "token_encrypted"
        const val KEY_DESKTOP_NAME = "desktop_name"
        const val KEY_HOST = "host"
        const val KEY_PORT = "port"
        const val KEY_FINGERPRINT = "certificate_pin"
        const val KEY_TTS = "speak_replies"
    }
}
