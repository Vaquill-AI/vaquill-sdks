package ai.vaquill.sdk

import java.util.UUID

/** Idempotency keys: one UUIDv4 per logical call, reused across every retry. */
internal object Idempotency {
    fun newKey(): String = UUID.randomUUID().toString()

    /** The server accepts 16 to 255 visible ASCII characters. */
    fun validate(key: String): String {
        if (key.length !in 16..255 || key.any { it.code !in 33..126 }) {
            throw VaquillException("idempotencyKey must be 16 to 255 visible ASCII characters.")
        }
        return key
    }

    /** Keys are logged by their first 8 characters only. */
    fun redact(key: String): String = key.take(8) + "..."

    /** Suffix a caller key for chunks after the first; every chunk has a different body. */
    fun forChunk(key: String?, index: Int): String? {
        if (key == null || index == 0) return key
        val suffix = "-$index"
        return key.take(255 - suffix.length) + suffix
    }
}
