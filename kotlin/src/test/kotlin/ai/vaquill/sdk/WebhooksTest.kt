package ai.vaquill.sdk

import java.util.Base64
import javax.crypto.Mac
import javax.crypto.spec.SecretKeySpec
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertTrue

class WebhooksTest {
    // Known-answer vector from the Standard Webhooks README.
    private val secret = "whsec_MfKQ9r8GKYqrTwjUPD8ILPZIo2LaLaSw"
    private val msgId = "msg_p5jXN8AQM9LWM0D4loKWxJek"
    private val ts = 1614265330L
    private val payload = """{"test": 2432232314}"""
    private val knownSig = "v1,g0hM9SsE+OTPJTGt/tmIKtSyZlE3uFJELVlNIOLJ1OE="
    private val now = ts + 10
    private val event = """{"event":"watch.changed","firedAt":"2026-10-29T00:00:00Z","extra":1}"""

    private fun sign(sec: String, body: String, id: String = msgId, stamp: Long = ts): String {
        val key = if (sec.startsWith("whsec_")) Base64.getDecoder().decode(sec.substring(6)) else sec.toByteArray()
        val mac = Mac.getInstance("HmacSHA256").apply { init(SecretKeySpec(key, "HmacSHA256")) }
        return "v1," + Base64.getEncoder().encodeToString(mac.doFinal("$id.$stamp.$body".toByteArray()))
    }

    private fun headers(sig: String, stamp: Long = ts) =
        mapOf("webhook-id" to msgId, "webhook-timestamp" to stamp.toString(), "webhook-signature" to sig)

    @Test
    fun knownAnswerVector() {
        assertEquals(knownSig, sign(secret, payload))
        Webhooks.verify(payload, headers(knownSig), secret, nowSeconds = now)
        assertFailsWith<WebhookPayloadException> { Webhooks.unwrap(payload, headers(knownSig), secret, nowSeconds = now) }
    }

    @Test
    fun validEventKeepsExtras() {
        val e = Webhooks.unwrap(event, headers(sign(secret, event)).mapKeys { it.key.uppercase() }, secret, nowSeconds = now)
        assertEquals("watch.changed", e.event)
        assertEquals("2026-10-29T00:00:00Z", e.firedAt)
        assertEquals(setOf("extra"), e.extra.keys)
        assertEquals(3, e.raw.size)
        val bytes = Webhooks.unwrap(event.toByteArray(), headers(sign(secret, event)), listOf(secret), nowSeconds = now)
        assertEquals(e, bytes)
    }

    @Test
    fun rejectsTamperingWrongSecretsAndBadTimestamps() {
        val good = headers(sign(secret, event))
        assertFailsWith<WebhookVerificationException> { Webhooks.verify(event + " ", good, secret, nowSeconds = now) }
        assertFailsWith<WebhookVerificationException> { Webhooks.verify(event, good, "whsec_" + Base64.getEncoder().encodeToString("other".toByteArray()), nowSeconds = now) }
        assertFailsWith<WebhookVerificationException> { Webhooks.verify(event, good + ("webhook-id" to "other"), secret, nowSeconds = now) }
        assertFailsWith<WebhookVerificationException> { Webhooks.verify(event, good, secret, nowSeconds = ts + 301) }
        assertFailsWith<WebhookVerificationException> { Webhooks.verify(event, good, secret, nowSeconds = ts - 301) }
        Webhooks.verify(event, good, secret, toleranceSeconds = 600, nowSeconds = ts + 500)
        assertFailsWith<WebhookVerificationException> { Webhooks.verify(event, good + ("webhook-timestamp" to "abc"), secret, nowSeconds = now) }
        assertFailsWith<WebhookVerificationException> { Webhooks.verify(event, emptyMap(), secret, nowSeconds = now) }
    }

    @Test
    fun rotationAndUnknownVersions() {
        val other = "whsec_" + Base64.getEncoder().encodeToString("rotated-secret-bytes".toByteArray())
        val both = "v1,AAAA ${sign(other, event)} v2,zzzz"
        Webhooks.verify(event.toByteArray(), headers(both), listOf(secret, other), nowSeconds = now)
        Webhooks.verify(event.toByteArray(), headers(both), listOf(other), nowSeconds = now)
        assertFailsWith<WebhookVerificationException> { Webhooks.verify(event.toByteArray(), headers(both), listOf(secret), nowSeconds = now) }
        assertFailsWith<WebhookVerificationException> { Webhooks.verify(event, headers(sign(secret, event).replace("v1,", "v2,")), secret, nowSeconds = now) }
    }

    @Test
    fun plainSecretsUseUtf8Bytes() {
        Webhooks.verify(event, headers(sign("plain-secret", event)), "plain-secret", nowSeconds = now)
    }

    @Test
    fun emptyBlankAndInvalidBase64SecretsFailLoudly() {
        val good = headers(sign(secret, event))
        for (bad in listOf("", "   ", "whsec_", " whsec_ ")) {
            assertFailsWith<IllegalArgumentException>(bad) { Webhooks.verify(event, good, bad, nowSeconds = now) }
        }
        assertFailsWith<IllegalArgumentException> { Webhooks.verify(event.toByteArray(), good, emptyList(), nowSeconds = now) }
        assertFailsWith<IllegalArgumentException> { Webhooks.verify(event.toByteArray(), good, listOf(secret, ""), nowSeconds = now) }
        val e = assertFailsWith<IllegalArgumentException> { Webhooks.verify(event, good, "whsec_!!!not base64!!!", nowSeconds = now) }
        assertTrue(!e.message!!.contains("!!!not"), "the secret must not be echoed")
    }

    @Test
    fun legacySignatureIsOptInAndLowerPriorityThanStandardHeaders() {
        val sig = "sha256=" + Mac.getInstance("HmacSHA256").apply { init(SecretKeySpec("s3cret".toByteArray(), "HmacSHA256")) }
            .doFinal(event.toByteArray()).joinToString("") { "%02x".format(it) }
        val legacy = mapOf("X-Vaquill-Signature" to sig)
        assertFailsWith<WebhookVerificationException> { Webhooks.verify(event, legacy, "s3cret", nowSeconds = now) }
        val warnings = mutableListOf<String>()
        Webhooks.verify(event.toByteArray(), legacy, listOf("s3cret"), allowLegacy = true, nowSeconds = now, logger = { _, m -> warnings.add(m) })
        assertEquals(1, warnings.size)
        Webhooks.verify(event, legacy, "s3cret", allowLegacy = true)
        assertFailsWith<WebhookVerificationException> { Webhooks.verify(event + "x", legacy, "s3cret", allowLegacy = true) }
        assertFailsWith<WebhookVerificationException> { Webhooks.verify(event, emptyMap(), "s3cret", allowLegacy = true) }
        // A present but wrong set of standard headers does not fall back to legacy.
        assertFailsWith<WebhookVerificationException> { Webhooks.verify(event, legacy + headers("v1,bad"), "s3cret", allowLegacy = true, nowSeconds = now) }
    }

    @Test
    fun nonEventBodiesAreRejectedAfterVerification() {
        for (body in listOf("[1]", "not json", """{"event":5}""", """{"firedAt":"x"}""")) {
            assertFailsWith<WebhookPayloadException>(body) { Webhooks.unwrap(body, headers(sign(secret, body)), secret, nowSeconds = now) }
        }
        val minimal = Webhooks.unwrap("""{"event":"x"}""", headers(sign(secret, """{"event":"x"}""")), secret, nowSeconds = now)
        assertEquals(null, minimal.firedAt)
    }
}
