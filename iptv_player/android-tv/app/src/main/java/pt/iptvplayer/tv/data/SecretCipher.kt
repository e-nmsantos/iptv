package pt.iptvplayer.tv.data

import android.annotation.SuppressLint
import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import java.security.KeyStore
import java.security.SecureRandom
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec
import javax.crypto.spec.SecretKeySpec

/** Envelope encryption: AndroidKeyStore protects one local data key, while catalog
 * fields use that in-memory AES key. This avoids a hardware keystore operation for
 * every one of the thousands of channels in a typical IPTV catalog. */
class SecretCipher(context: Context) {
    private val alias = "iptv-player-tv-catalog-v1"
    private val keyStore = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
    private val preferences = context.getSharedPreferences("catalog-crypto", Context.MODE_PRIVATE)
    private val masterKey: SecretKey by lazy(LazyThreadSafetyMode.SYNCHRONIZED) { loadOrCreateMasterKey() }
    private val dataKey: SecretKey by lazy(LazyThreadSafetyMode.SYNCHRONIZED) { loadOrCreateDataKey() }

    private fun loadOrCreateMasterKey(): SecretKey {
        (keyStore.getKey(alias, null) as? SecretKey)?.let { return it }
        return KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore").run {
            init(
                KeyGenParameterSpec.Builder(
                    alias,
                    KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT,
                ).setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                    .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                    .setKeySize(256)
                    .build(),
            )
            generateKey()
        }
    }

    @SuppressLint("ApplySharedPref", "UseKtx") // The wrapped key must be durable before it is used.
    private fun loadOrCreateDataKey(): SecretKey {
        val wrapped = preferences.getString(WRAPPED_KEY, null)
        if (!wrapped.isNullOrBlank()) {
            runCatching { return SecretKeySpec(decryptBytes(decode(wrapped), masterKey), "AES") }
        }
        val bytes = ByteArray(32).also(SecureRandom()::nextBytes)
        check(preferences.edit().putString(WRAPPED_KEY, encode(encryptBytes(bytes, masterKey))).commit()) {
            "Não foi possível guardar a chave de proteção do catálogo."
        }
        return SecretKeySpec(bytes, "AES")
    }

    fun encrypt(value: String): String = V2_PREFIX + encode(
        encryptBytes(value.toByteArray(Charsets.UTF_8), dataKey),
    )

    fun decrypt(value: String): String = runCatching {
        if (value.startsWith(V2_PREFIX)) {
            String(decryptBytes(decode(value.removePrefix(V2_PREFIX)), dataKey), Charsets.UTF_8)
        } else {
            // Compatibility with catalogs saved by versions up to 0.5.1.
            String(decryptBytes(decode(value), masterKey), Charsets.UTF_8)
        }
    }.getOrDefault("")

    private fun encryptBytes(value: ByteArray, key: SecretKey): ByteArray {
        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(Cipher.ENCRYPT_MODE, key)
        return cipher.iv + cipher.doFinal(value)
    }

    private fun decryptBytes(payload: ByteArray, key: SecretKey): ByteArray {
        require(payload.size > IV_SIZE)
        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(Cipher.DECRYPT_MODE, key, GCMParameterSpec(128, payload.copyOfRange(0, IV_SIZE)))
        return cipher.doFinal(payload.copyOfRange(IV_SIZE, payload.size))
    }

    private fun encode(value: ByteArray): String = Base64.encodeToString(value, Base64.NO_WRAP)
    private fun decode(value: String): ByteArray = Base64.decode(value, Base64.NO_WRAP)

    companion object {
        private const val V2_PREFIX = "v2:"
        private const val WRAPPED_KEY = "wrapped-data-key"
        private const val IV_SIZE = 12
    }
}
