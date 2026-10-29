package ai.vaquill.sdk

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.async
import kotlinx.coroutines.awaitAll
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.runBlocking
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import java.net.ServerSocket
import java.time.Duration
import java.util.concurrent.CopyOnWriteArrayList
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertFalse
import kotlin.test.assertNotNull
import kotlin.test.assertNull
import kotlin.test.assertTrue

private fun err(status: Int, code: String? = null, extra: String = "") =
    Reply(status, """{"detail":"boom"${if (code != null) ""","code":"$code"""" else ""}$extra}""")

class ClientTest {
    @Test
    fun defaultHeadersMergeCaseInsensitivelyAndProtectedOnesWin() = runBlocking<Unit> {
        FakeServer().use { s ->
            val c = client(s) { defaultHeader("X-Foo", "1"); defaultHeader("Authorization", "evil") }
            c.rawRequest("GET", "/x", options = RequestOptions(headers = mapOf("x-foo" to "2", "IDEMPOTENCY-KEY" to "evil", "Accept" to "text/plain")))
            val r = s.requests.single()
            assertEquals("2", r.header("x-foo"))
            assertEquals("Bearer $TEST_KEY", r.header("authorization"))
            assertNull(r.header("idempotency-key"))
            assertEquals("text/plain", r.header("accept"))
        }
    }

    @Test
    fun restrictedHeadersAreRejected() = runBlocking<Unit> {
        FakeServer().use { s ->
            assertFailsWith<IllegalArgumentException> { client(s).rawRequest("GET", "/x", options = RequestOptions(headers = mapOf("Host" to "x"))) }
        }
    }

    @Test
    fun apiKeyIsValidatedWithoutEchoingIt() {
        assertFailsWith<VaquillException> { VaquillClient { apiKey = "   " } }
        val bad = assertFailsWith<VaquillException> { VaquillClient { apiKey = "secret_not_a_vaquill_key" } }
        assertFalse(bad.message!!.contains("secret_not"))
        val ctl = assertFailsWith<IllegalArgumentException> { VaquillClient { apiKey = "vq_key_ab cd" } }
        assertFalse(ctl.message!!.contains("ab cd"))
        assertEquals("https://x.test", VaquillClient { apiKey = "vq_key_abc\n"; baseUrl = "https://x.test//" }.baseUrl)
        assertFailsWith<IllegalArgumentException> { VaquillClient { apiKey = TEST_KEY; maxRetries = -1 } }
        assertTrue(VaquillClient { apiKey = TEST_KEY }.toString().contains("api.vaquill.ai"))
    }

    @Test
    fun withResponseExposesMetadataAndReplayIsNotCounted() = runBlocking<Unit> {
        FakeServer().use { s ->
            s.script(
                Reply(200, """{"creditsConsumed":2}""", mapOf("X-Request-ID" to "req-1", "X-RateLimit-Limit" to "60", "X-RateLimit-Remaining" to "59", "X-RateLimit-Reset-Day" to "12.5")),
                Reply(200, """{"creditsConsumed":5}""", mapOf("Idempotent-Replayed" to "true")),
            )
            val c = client(s)
            val first = c.withResponse { rawRequest("GET", "/x", charged = true) }
            assertEquals(200, first.statusCode)
            assertEquals("req-1", first.requestId)
            assertEquals(2.0, first.creditsConsumed)
            assertEquals(2.0, first.creditsChargedThisCall)
            assertEquals(RateLimit(limit = 60, remaining = 59, resetDay = 12.5), first.rateLimit)
            assertFalse(first.idempotentReplayed)
            assertNotNull(first.json)
            assertEquals(2.0, c.creditsSpent)
            val replay = c.withResponse { rawRequest("GET", "/x", charged = true) }
            assertTrue(replay.idempotentReplayed)
            assertEquals(0.0, replay.creditsChargedThisCall)
            assertEquals(5.0, replay.creditsConsumed)
            assertEquals(2.0, c.creditsSpent)
            assertFailsWith<VaquillException> { c.withResponse { 1 } }
        }
    }

    @Test
    fun deprecationIsWarnedOncePerEndpointAndKeysNeverReachTheLog() = runBlocking<Unit> {
        FakeServer().use { s ->
            s.script(Reply(200, "{}", mapOf("Deprecation" to "true", "Sunset" to "Sat, 01 Jan 2028 00:00:00 GMT", "Idempotency-Status" to "unavailable")))
            val lines = CopyOnWriteArrayList<String>()
            val c = client(s) { logger = VaquillLogger { l, m -> lines.add("$l $m") } }
            repeat(3) { c.rawRequest("POST", "/dep", charged = true) }
            assertEquals(1, lines.count { it.contains("is deprecated") })
            assertTrue(lines.any { it.contains("could not deduplicate") })
            assertTrue(lines.any { it.startsWith("DEBUG Request POST") })
            assertTrue(lines.none { it.contains(TEST_KEY) }, "the API key must be redacted")
            val sent = s.requests.first().header("idempotency-key")!!
            assertTrue(lines.none { it.contains(sent) }, "idempotency keys are logged by prefix only")
            assertEquals("A vq_key_*** B", redactSecrets("A $TEST_KEY B", TEST_KEY))
            assertEquals("see vq_key_***", redactSecrets("see vq_key_abc-DEF_1", null))
        }
    }

    @Test
    fun timeoutAndConnectionFailures() = runBlocking<Unit> {
        FakeServer().use { s ->
            s.script(Reply(200, "{}", delayMs = 600))
            assertFailsWith<ApiTimeoutException> { client(s) { timeout = Duration.ofMillis(100); maxRetries = 0 }.rawRequest("GET", "/x") }
            val ok = client(s) { timeout = Duration.ZERO; maxRetries = 0 }.rawRequest("GET", "/x")
            assertNotNull(ok)
        }
        val port = ServerSocket(0).use { it.localPort }
        val sleeps = Sleeps()
        val c = VaquillClient { apiKey = TEST_KEY; baseUrl = "http://127.0.0.1:$port"; logger = VaquillLogger.NONE; sleeper = { sleeps.millis.add(it) }; maxRetries = 1 }
        assertFailsWith<ApiConnectionException> { c.watches.create("usc") }
        assertEquals(1, sleeps.millis.size, "a refused connection never reached the server, so even a POST is retried")
        c.close()
    }

    @Test
    fun malformedSuccessBodiesRaiseResponseParseException() = runBlocking<Unit> {
        FakeServer().use { s ->
            val c = client(s)
            s.script(Reply(200, "not json", mapOf("X-Request-ID" to "r9")))
            val e = assertFailsWith<ResponseParseException> { c.credits.balance() }
            assertEquals("r9", e.requestId)
            assertEquals(200, e.statusCode)
            s.script(Reply(200, "{}"))
            assertFailsWith<ResponseParseException> { c.credits.balance() }
            assertEquals(Unit, c.watches.delete("w").also { })
        }
    }

    @Test
    fun noContentAndWithOptionsShareState() = runBlocking<Unit> {
        FakeServer().use { s ->
            s.script(Reply(204, ""))
            val c = client(s)
            c.watches.delete("w1")
            val d = c.withOptions { maxRetries = 0; maxCredits = 1.0; defaultHeader("x-derived", "y") }
            s.script(Reply(200, """{"creditsConsumed":1}"""))
            d.rawRequest("GET", "/x", charged = true)
            assertEquals(1.0, c.creditsSpent, "derived clients share the spend total")
            assertFailsWith<SpendGuardExceededException> { d.rawRequest("GET", "/x", charged = true) }
            assertEquals("y", s.requests.last().header("x-derived"))
            d.close()
            c.close()
        }
    }
}

class RetryTest {
    @Test
    fun getIsRetriedOn503AndHonoursRetryAfter() = runBlocking<Unit> {
        FakeServer().use { s ->
            val sleeps = Sleeps()
            s.script(Reply(503, """{"detail":"x"}""", mapOf("Retry-After" to "2")), Reply(429, """{"detail":"x"}""", mapOf("retry-after-ms" to "1500")), Reply(200, "{}"))
            client(s, sleeps).rawRequest("GET", "/x")
            assertEquals(3, s.requests.size)
            assertEquals(listOf(2000L, 1500L), sleeps.millis.toList())
        }
    }

    @Test
    fun exhaustedRetriesRaiseTheLastError() = runBlocking<Unit> {
        FakeServer().use { s ->
            s.script(err(500))
            val sleeps = Sleeps()
            assertFailsWith<InternalServerException> { client(s, sleeps).rawRequest("GET", "/x") }
            assertEquals(3, s.requests.size)
            assertEquals(2, sleeps.millis.size)
            assertTrue(sleeps.millis.all { it in 1L..8000L })
        }
    }

    @Test
    fun neverRetriedStatusesAndCodes() = runBlocking<Unit> {
        val cases = listOf(err(402, "insufficient_credits"), err(429, "daily_cap_exceeded"), err(400), err(404), err(501), err(503, extra = ""","retryable":false"""), Reply(429, """{"detail":"x"}""", mapOf("Retry-After" to "600")))
        for (reply in cases) {
            FakeServer().use { s ->
                s.script(reply)
                assertFailsWith<ApiStatusException> { client(s).rawRequest("GET", "/x") }
                assertEquals(1, s.requests.size, "status ${reply.status} must not be retried")
            }
        }
        FakeServer().use { s ->
            s.script(err(408), Reply())
            client(s).rawRequest("GET", "/x")
            assertEquals(2, s.requests.size)
        }
    }

    @Test
    fun chargedFiveHundredIsReplayedOnlyWithAKeyAndTheKeyIsReused() = runBlocking<Unit> {
        FakeServer().use { s ->
            s.script(err(503), Reply())
            client(s).rawRequest("POST", "/x", charged = true)
            assertEquals(2, s.requests.size)
            assertEquals(s.requests[0].header("idempotency-key"), s.requests[1].header("idempotency-key"))
        }
        FakeServer().use { s ->
            s.script(err(503), Reply())
            assertFailsWith<InternalServerException> { client(s) { idempotencyKeys = false }.rawRequest("POST", "/x", charged = true) }
            assertEquals(1, s.requests.size)
        }
        FakeServer().use { s ->
            s.script(err(429), Reply())
            client(s) { idempotencyKeys = false }.rawRequest("POST", "/x", charged = true)
            assertEquals(2, s.requests.size, "a 429 was refused before processing, so it is safe to replay")
        }
    }

    @Test
    fun ambiguousTransportFailures() = runBlocking<Unit> {
        FakeServer().use { s ->
            s.responder = { _, n -> if (n == 1) Reply(abort = true) else Reply() }
            client(s).rawRequest("GET", "/x")
            assertEquals(2, s.requests.size)
        }
        FakeServer().use { s ->
            s.responder = { _, _ -> Reply(abort = true) }
            assertFailsWith<ApiConnectionException> { client(s).watches.create("usc") }
            assertEquals(1, s.requests.size, "a keyless POST is not replayed after an ambiguous failure")
        }
        FakeServer().use { s ->
            s.responder = { _, n -> if (n == 1) Reply(abort = true) else Reply() }
            client(s).rawRequest("POST", "/x", options = RequestOptions(idempotencyKey = "k".repeat(16)))
            assertEquals(2, s.requests.size)
        }
    }

    @Test
    fun retryPolicyUnits() {
        val now = java.time.Instant.parse("2026-01-01T00:00:00Z")
        assertEquals(1.5, Retry.parseRetryAfter(Headers.of("Retry-After-Ms" to "1500")))
        assertEquals(3.0, Retry.parseRetryAfter(Headers.of("Retry-After" to "3")))
        assertEquals(30.0, Retry.parseRetryAfter(Headers.of("Retry-After" to "Thu, 01 Jan 2026 00:00:30 GMT"), now))
        assertEquals(0.0, Retry.parseRetryAfter(Headers.of("Retry-After" to "Wed, 31 Dec 2025 00:00:00 GMT"), now))
        assertNull(Retry.parseRetryAfter(Headers.of("Retry-After" to "NaN")))
        assertNull(Retry.parseRetryAfter(Headers.of("Retry-After" to "soon")))
        assertNull(Retry.parseRetryAfter(Headers.of("retry-after-ms" to "inf")))
        assertNull(Retry.parseRetryAfter(Headers.EMPTY))
        repeat(50) { i ->
            val d = Retry.backoffDelay(i % 8)
            assertTrue(d in 0.375..8.0, "delay $d")
        }
        val e = makeStatusError(503, Headers.EMPTY, JsonObject(mapOf("retryAfterSeconds" to JsonPrimitive(7))))
        assertEquals(7.0, Retry.delayForStatus(e, 0))
        assertNull(Retry.delayForStatus(e, 0, replaySafe = false))
        assertTrue(Retry.connectionErrorIsRetryable(true, "POST", false))
        assertFalse(Retry.connectionErrorIsRetryable(false, "POST", false))
        assertTrue(Retry.connectionErrorIsRetryable(false, "head", false))
    }
}

class ErrorsTest {
    private fun make(status: Int, body: String?): ApiStatusException =
        makeStatusError(status, Headers.of("X-Request-ID" to "hdr-id"), body?.let { VaquillJson.parseToJsonElement(it) })

    @Test
    fun statusAndCodeMapping() {
        assertTrue(make(400, null) is BadRequestException)
        assertTrue(make(401, null) is AuthenticationException)
        assertTrue(make(402, null) is InsufficientCreditsException)
        assertTrue(make(403, null) is PermissionDeniedException)
        assertTrue(make(404, null) is NotFoundException)
        assertTrue(make(409, null) is ConflictException)
        assertTrue(make(422, null) is UnprocessableEntityException)
        assertTrue(make(429, null) is RateLimitException)
        assertTrue(make(502, null) is InternalServerException)
        assertTrue(make(418, null) is UnexpectedStatusException)
        assertTrue(make(429, """{"code":"daily_cap_exceeded"}""") is DailyCapExceededException)
        assertTrue(make(429, """{"code":"daily_cap_exceeded"}""") is RateLimitException)
        assertTrue(make(500, """{"code":"insufficient_credits"}""") is InsufficientCreditsException)
        assertTrue(make(422, """{"code":"idempotency_key_reused"}""") is IdempotencyKeyReusedException)
        assertTrue(make(422, """{"code":"idempotency_key_reused"}""") is UnprocessableEntityException)
        assertTrue(make(409, """{"code":"idempotency_in_progress"}""") is IdempotencyInProgressException)
        assertTrue(make(409, """{"code":"idempotency_replay_unavailable"}""") is IdempotencyReplayUnavailableException)
        assertTrue(make(409, """{"code":"idempotency_replay_unavailable"}""") is IdempotencyConflict)
        assertTrue(make(409, """{"code":"brand_new"}""") is ConflictException)
    }

    @Test
    fun fieldsAndMessages() {
        val e = make(429, """{"detail":"slow down","code":"rate_limited","requestId":"body-id","retryable":true,"retryAfterSeconds":4.5,"errors":[{"x":1}]}""")
        assertEquals("slow down", e.message)
        assertEquals("rate_limited", e.code)
        assertEquals("body-id", e.requestId)
        assertEquals(true, e.retryable)
        assertEquals(4.5, e.retryAfterSeconds)
        assertEquals(1, e.errors!!.size)
        assertEquals(429, e.status)
        assertTrue(e.toString().contains("requestId=body-id"))
        assertEquals("hdr-id", make(500, """{"detail":"x"}""").requestId)
        assertEquals("T", make(500, """{"title":"T"}""").message)
        assertEquals("HTTP 500", make(500, null).message)
        val text = makeStatusError(502, Headers.EMPTY, JsonPrimitive("<html>bad gateway</html>"))
        assertEquals("HTTP 502", text.message)
        assertEquals(JsonPrimitive("<html>bad gateway</html>"), text.body)
    }

    @Test
    fun unprocessableMessageAppendsTheFirstReasons() {
        val body = """{"detail":"Validation failed","errors":[
            {"loc":["body","query"],"msg":"field required"},
            {"loc":["query","limit"],"msg":"must be <= 500"},
            {"loc":["body","a","b"],"msg":"bad"},
            {"msg":"fourth"}, {"loc":[],"msg":""}]}"""
        assertEquals("Validation failed: query: field required; limit: must be <= 500; a.b: bad (+2 more)", make(422, body).message)
        assertEquals("Validation failed", make(400, body).message, "only a 422 appends reasons")
        assertEquals("Validation failed", make(422, """{"detail":"Validation failed","errors":"nope"}""").message)
    }
}

class SpendGuardTest {
    @Test
    fun concurrentChargedCallsNeverExceedTheCap() = runBlocking<Unit> {
        FakeServer().use { s ->
            s.responder = { _, _ -> Reply(200, """{"creditsConsumed":1}""", delayMs = 30) }
            val c = client(s) { maxCredits = 3.0 }
            val results = coroutineScope {
                (1..12).map { async(Dispatchers.Default) { runCatching { c.rawRequest("GET", "/x", charged = true) } } }.awaitAll()
            }
            assertEquals(3, results.count { it.isSuccess })
            assertEquals(9, results.count { it.exceptionOrNull() is SpendGuardExceededException })
            assertEquals(3, s.requests.size, "a refused call never reaches the network")
            assertEquals(3.0, c.creditsSpent)
            c.rawRequest("GET", "/free")
            assertEquals(4, s.requests.size, "free calls are never blocked by the guard")
        }
    }
}
