package ai.vaquill.sdk

import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.contentOrNull
import java.security.MessageDigest
import java.util.Base64
import javax.crypto.Mac
import javax.crypto.spec.SecretKeySpec
import kotlin.math.abs

/** Event envelope. Every other member of the payload is kept in [extra]. */
public data class WebhookEvent(
    val event: String,
    val firedAt: String?,
    /** Members other than `event` and `firedAt`. */
    val extra: JsonObject,
    /** The whole payload. */
    val raw: JsonObject,
)

/** Webhook verification: Standard Webhooks (preferred) and the legacy signature header. */
public object Webhooks {
    private const val SECRET_PREFIX = "whsec_"

    private fun key(secret: String): ByteArray {
        if (secret.startsWith(SECRET_PREFIX)) {
            try {
                return Base64.getDecoder().decode(secret.substring(SECRET_PREFIX.length))
            } catch (e: IllegalArgumentException) {
                throw IllegalArgumentException("The webhook secret starts with whsec_ but is not valid base64.", e)
            }
        }
        return secret.toByteArray(Charsets.UTF_8)
    }

    private fun requireSecrets(secrets: List<String>) {
        require(secrets.isNotEmpty()) { "A webhook secret is required." }
        for (s in secrets) {
            require(s.isNotBlank() && s.trim() != SECRET_PREFIX) { "The webhook secret is empty or blank." }
        }
    }

    private fun hmac(key: ByteArray, data: ByteArray): ByteArray {
        val mac = Mac.getInstance("HmacSHA256")
        mac.init(SecretKeySpec(key, "HmacSHA256"))
        return mac.doFinal(data)
    }

    private fun anyMatch(candidates: List<String>, expected: List<String>): Boolean {
        // No early exit: every comparison runs so timing does not reveal which one matched.
        var matched = false
        for (given in candidates) {
            for (want in expected) {
                matched = matched or MessageDigest.isEqual(given.toByteArray(), want.toByteArray())
            }
        }
        return matched
    }

    /**
     * Verify a delivery's signature and timestamp. Throws [WebhookVerificationException].
     *
     * [payload] must be the raw request body, never re-serialised JSON. [secrets] may hold several
     * secrets to accept both during a rotation. Throws [IllegalArgumentException] (not a
     * verification error) for an empty or blank secret or a `whsec_` secret that is not base64, so
     * a missing configuration value is a loud failure and can never accept a forged event.
     *
     * Standard Webhooks (`webhook-id`, `webhook-timestamp`, `webhook-signature`) is checked first,
     * with a [toleranceSeconds] window either side of [nowSeconds]. Legacy
     * `X-Vaquill-Signature: sha256=<hmac>` deliveries are rejected unless [allowLegacy] is true.
     * WARNING: the legacy scheme signs only the body, so it has NO replay protection.
     */
    @JvmStatic
    @JvmOverloads
    public fun verify(
        payload: ByteArray,
        headers: Map<String, String>,
        secrets: List<String>,
        toleranceSeconds: Long = 300,
        allowLegacy: Boolean = false,
        nowSeconds: Long = System.currentTimeMillis() / 1000,
        logger: VaquillLogger = VaquillLogger.NONE,
    ) {
        requireSecrets(secrets)
        val h = headers.mapKeys { it.key.lowercase() }
        val msgId = h["webhook-id"]
        val stamp = h["webhook-timestamp"]
        val sig = h["webhook-signature"]
        if (!msgId.isNullOrEmpty() && !stamp.isNullOrEmpty() && !sig.isNullOrEmpty()) {
            val ts = stamp.trim().toLongOrNull() ?: throw WebhookVerificationException("Invalid webhook-timestamp.")
            if (abs(nowSeconds - ts) > toleranceSeconds) {
                throw WebhookVerificationException("Webhook timestamp is outside the tolerance window.")
            }
            val signed = "$msgId.$ts.".toByteArray() + payload
            val expected = secrets.map { Base64.getEncoder().encodeToString(hmac(key(it), signed)) }
            val given = sig.split(' ', '\t').filter { it.startsWith("v1,") }.map { it.substring(3) }
            if (!anyMatch(given, expected)) throw WebhookVerificationException("No matching signature.")
        } else {
            val legacy = h["x-vaquill-signature"]
            if (!allowLegacy || legacy.isNullOrEmpty()) {
                throw WebhookVerificationException("Missing webhook signature headers.")
            }
            logger.log(LogLevel.WARN, "Verifying a legacy X-Vaquill-Signature: there is no replay protection.")
            val expected = secrets.map { "sha256=" + hmac(it.toByteArray(Charsets.UTF_8), payload).joinToString("") { b -> "%02x".format(b) } }
            if (!anyMatch(listOf(legacy), expected)) throw WebhookVerificationException("No matching signature.")
        }
    }

    /** [verify] and then parse the payload into a [WebhookEvent]. Throws [WebhookPayloadException] for a non-event body. */
    @JvmStatic
    @JvmOverloads
    public fun unwrap(
        payload: ByteArray,
        headers: Map<String, String>,
        secrets: List<String>,
        toleranceSeconds: Long = 300,
        allowLegacy: Boolean = false,
        nowSeconds: Long = System.currentTimeMillis() / 1000,
        logger: VaquillLogger = VaquillLogger.NONE,
    ): WebhookEvent {
        verify(payload, headers, secrets, toleranceSeconds, allowLegacy, nowSeconds, logger)
        val obj = try {
            VaquillJson.parseToJsonElement(payload.toString(Charsets.UTF_8)) as? JsonObject
        } catch (e: kotlinx.serialization.SerializationException) {
            throw WebhookPayloadException("Payload is not a valid event.", e)
        } ?: throw WebhookPayloadException("Payload is not a valid event.")
        val event = (obj["event"] as? JsonPrimitive)?.takeIf { it.isString }?.contentOrNull
            ?: throw WebhookPayloadException("Payload is not a valid event.")
        val firedAt = (obj["firedAt"] as? JsonPrimitive)?.takeIf { it.isString }?.contentOrNull
        return WebhookEvent(event, firedAt, JsonObject(obj - "event" - "firedAt"), obj)
    }

    /** String-payload and single-secret convenience for [unwrap]. */
    @JvmStatic
    @JvmOverloads
    public fun unwrap(
        payload: String,
        headers: Map<String, String>,
        secret: String,
        toleranceSeconds: Long = 300,
        allowLegacy: Boolean = false,
        nowSeconds: Long = System.currentTimeMillis() / 1000,
    ): WebhookEvent = unwrap(payload.toByteArray(Charsets.UTF_8), headers, listOf(secret), toleranceSeconds, allowLegacy, nowSeconds)

    /** String-payload and single-secret convenience for [verify]. */
    @JvmStatic
    @JvmOverloads
    public fun verify(
        payload: String,
        headers: Map<String, String>,
        secret: String,
        toleranceSeconds: Long = 300,
        allowLegacy: Boolean = false,
        nowSeconds: Long = System.currentTimeMillis() / 1000,
    ) {
        verify(payload.toByteArray(Charsets.UTF_8), headers, listOf(secret), toleranceSeconds, allowLegacy, nowSeconds)
    }
}
