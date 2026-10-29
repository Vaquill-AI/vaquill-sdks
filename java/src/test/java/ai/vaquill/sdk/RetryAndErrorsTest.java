package ai.vaquill.sdk;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertInstanceOf;
import static org.junit.jupiter.api.Assertions.assertNotEquals;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

import ai.vaquill.sdk.FakeServer.Reply;
import ai.vaquill.sdk.TestSupport.Recorder;
import ai.vaquill.sdk.internal.Retry;
import ai.vaquill.sdk.models.StatuteCountRequest;
import java.time.ZoneOffset;
import java.time.ZonedDateTime;
import java.time.format.DateTimeFormatter;
import java.util.Arrays;
import java.util.Collections;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.Test;

class RetryAndErrorsTest {
    private static final StatuteCountRequest COUNT = StatuteCountRequest.builder().build();

    private static ApiStatusException failure(int status, String body) {
        try (FakeServer server = new FakeServer()) {
            server.script(Reply.json(status, body).header("X-Request-ID", "hdr-id"));
            Vaquill c = TestSupport.builder(server, new Recorder()).maxRetries(0).build();
            return assertThrows(ApiStatusException.class, () -> c.credits().balance());
        }
    }

    // ------------------------------------------------------------------ errors

    @Test
    void statusMapsToClass() {
        assertInstanceOf(BadRequestException.class, failure(400, "{}"));
        assertInstanceOf(AuthenticationException.class, failure(401, "{}"));
        assertInstanceOf(InsufficientCreditsException.class, failure(402, "{}"));
        assertInstanceOf(PermissionDeniedException.class, failure(403, "{}"));
        assertInstanceOf(NotFoundException.class, failure(404, "{}"));
        assertInstanceOf(ConflictException.class, failure(409, "{}"));
        assertInstanceOf(UnprocessableEntityException.class, failure(422, "{}"));
        assertInstanceOf(RateLimitException.class, failure(429, "{}"));
        assertInstanceOf(InternalServerException.class, failure(500, "{}"));
        assertInstanceOf(InternalServerException.class, failure(503, "{}"));
        ApiStatusException teapot = failure(418, "{}");
        assertEquals(ApiStatusException.class, teapot.getClass());
    }

    @Test
    void codeOverridesStatus() {
        assertInstanceOf(InsufficientCreditsException.class, failure(400, "{\"code\":\"insufficient_credits\"}"));
        assertInstanceOf(DailyCapExceededException.class, failure(429, "{\"code\":\"daily_cap_exceeded\"}"));
        assertInstanceOf(RateLimitException.class, failure(429, "{\"code\":\"daily_cap_exceeded\"}"));
        ApiStatusException reused = failure(422, "{\"code\":\"idempotency_key_reused\"}");
        assertInstanceOf(IdempotencyKeyReusedException.class, reused);
        assertInstanceOf(UnprocessableEntityException.class, reused);
        assertInstanceOf(IdempotencyConflict.class, reused);
        ApiStatusException progress = failure(409, "{\"code\":\"idempotency_in_progress\"}");
        assertInstanceOf(IdempotencyInProgressException.class, progress);
        assertInstanceOf(ConflictException.class, progress);
        assertInstanceOf(IdempotencyConflict.class, progress);
        ApiStatusException gone = failure(409, "{\"code\":\"idempotency_replay_unavailable\"}");
        assertInstanceOf(IdempotencyReplayUnavailableException.class, gone);
        assertInstanceOf(IdempotencyConflict.class, gone);
        // An unknown code still gives the status class.
        ApiStatusException unknown = failure(404, "{\"code\":\"brand_new_code\"}");
        assertInstanceOf(NotFoundException.class, unknown);
        assertEquals("brand_new_code", unknown.getCode());
    }

    @Test
    void errorCarriesTheEnvelope() {
        ApiStatusException e = failure(429, "{\"detail\":\"Slow down\",\"code\":\"rate_limited\",\"requestId\":\"body-id\","
                + "\"retryable\":true,\"retryAfterSeconds\":3.5,\"errors\":[{\"msg\":\"x\"}]}");
        assertEquals("Slow down", e.getMessage());
        assertEquals("rate_limited", e.getCode());
        assertEquals("body-id", e.getRequestId());
        assertEquals(Boolean.TRUE, e.getRetryable());
        assertEquals(3.5, e.getRetryAfterSeconds());
        assertEquals("Slow down", e.getDetail());
        assertEquals(1, e.getErrors().size());
        assertEquals(429, e.getStatusCode());
        assertEquals("hdr-id", e.getHeader("x-request-id"));
        assertTrue(e.getHeaders().size() > 0);
        assertInstanceOf(Map.class, e.getBody());
        assertTrue(e.toString().contains("status=429") && e.toString().contains("body-id"));
    }

    @Test
    void requestIdFallsBackToHeaderAndTextBodies() {
        ApiStatusException e = failure(500, "<html>boom</html>");
        assertEquals("hdr-id", e.getRequestId());
        assertEquals("<html>boom</html>", e.getBody());
        assertEquals("HTTP 500", e.getMessage());
        assertNull(e.getCode());
        assertNull(e.getRetryable());
        assertNull(e.getRetryAfterSeconds());
        assertNull(e.getErrors());
        assertEquals("Not Found", failure(404, "{\"title\":\"Not Found\"}").getMessage());
        assertEquals("HTTP 404", failure(404, "{\"detail\":\"\"}").getMessage());
        assertEquals("HTTP 400", failure(400, "").getMessage());
    }

    @Test
    void validationMessageAppendsTheFirstReasons() {
        String body = "{\"detail\":\"Validation failed\",\"errors\":["
                + "{\"loc\":[\"body\",\"limit\"],\"msg\":\"must be <= 100\"},"
                + "{\"loc\":[\"query\",\"filters\",0],\"msg\":\"bad\"},"
                + "{\"msg\":\"bare\"},"
                + "{\"loc\":[\"body\"],\"msg\":\"top\"},"
                + "{\"loc\":[\"x\"]},\"junk\"]}";
        assertEquals("Validation failed: limit: must be <= 100; filters.0: bad; bare (+3 more)", failure(422, body).getMessage());
        assertEquals("Validation failed: body: top", failure(422, "{\"detail\":\"Validation failed\",\"errors\":[{\"loc\":[\"body\"],\"msg\":\"top\"}]}").getMessage());
        assertEquals("Nope", failure(400, "{\"detail\":\"Nope\",\"errors\":[{\"msg\":\"x\"}]}").getMessage(), "only 422 appends reasons");
        assertEquals("Plain", failure(422, "{\"detail\":\"Plain\",\"errors\":\"nope\"}").getMessage());
        assertEquals("Plain", failure(422, "{\"detail\":\"Plain\",\"errors\":[1,2]}").getMessage());
    }

    // ------------------------------------------------------------------ retries

    @Test
    void retriesTransientStatusThenSucceeds() {
        try (FakeServer server = new FakeServer()) {
            Recorder rec = new Recorder();
            server.script(Reply.json(503, "{}"), Reply.json(502, "{}"), Reply.json(200, "{}"));
            Vaquill c = TestSupport.builder(server, rec).build();
            c.credits().balance();
            assertEquals(3, server.requests.size());
            assertEquals(2, rec.sleeps.size());
            // 0.5 s then 1 s, each scaled down by at most 25 percent jitter.
            assertTrue(rec.sleeps.get(0) >= 375 && rec.sleeps.get(0) <= 500, rec.sleeps.toString());
            assertTrue(rec.sleeps.get(1) >= 750 && rec.sleeps.get(1) <= 1000, rec.sleeps.toString());
        }
    }

    @Test
    void exhaustedRetriesRaiseTheLastError() {
        try (FakeServer server = new FakeServer()) {
            server.script(Reply.json(500, "{\"detail\":\"a\"}"), Reply.json(500, "{\"detail\":\"b\"}"), Reply.json(500, "{\"detail\":\"c\"}"));
            Vaquill c = TestSupport.client(server);
            InternalServerException e = assertThrows(InternalServerException.class, () -> c.credits().balance());
            assertEquals("c", e.getMessage());
            assertEquals(3, server.requests.size());
            RequestOptions none = RequestOptions.builder().maxRetries(0).build();
            assertThrows(InternalServerException.class, () -> c.credits().balance(none));
            assertEquals(4, server.requests.size());
        }
    }

    @Test
    void retryAfterIsHonoured() {
        try (FakeServer server = new FakeServer()) {
            Recorder rec = new Recorder();
            Vaquill c = TestSupport.builder(server, rec).maxRetries(1).build();
            server.script(Reply.json(429, "{}").header("Retry-After", "2"), Reply.json(200, "{}"));
            c.credits().balance();
            assertEquals(2000L, rec.sleeps.get(0));
            server.requests.clear();
            server.script(Reply.json(429, "{}").header("retry-after-ms", "250").header("Retry-After", "9"), Reply.json(200, "{}"));
            c.credits().balance();
            assertEquals(250L, rec.sleeps.get(1));
            server.requests.clear();
            String date = DateTimeFormatter.RFC_1123_DATE_TIME.format(ZonedDateTime.now(ZoneOffset.UTC).plusSeconds(30));
            server.script(Reply.json(503, "{}").header("Retry-After", date), Reply.json(200, "{}"));
            c.credits().balance();
            assertTrue(rec.sleeps.get(2) > 20_000 && rec.sleeps.get(2) <= 30_000, rec.sleeps.toString());
            server.requests.clear();
            server.script(Reply.json(429, "{\"retryAfterSeconds\":4}"), Reply.json(200, "{}"));
            c.credits().balance();
            assertEquals(4000L, rec.sleeps.get(3));
        }
    }

    @Test
    void absurdRetryAfterIsRaisedImmediately() {
        try (FakeServer server = new FakeServer()) {
            server.script(Reply.json(429, "{}").header("Retry-After", "100000"), Reply.json(200, "{}"));
            Vaquill c = TestSupport.client(server);
            assertThrows(RateLimitException.class, () -> c.credits().balance());
            assertEquals(1, server.requests.size());
        }
    }

    @Test
    void neverRetried() {
        for (String body : new String[] {"{\"code\":\"insufficient_credits\"}", "{\"code\":\"daily_cap_exceeded\"}", "{\"retryable\":false}"}) {
            try (FakeServer server = new FakeServer()) {
                server.script(Reply.json(429, body), Reply.json(200, "{}"));
                Vaquill c = TestSupport.client(server);
                assertThrows(ApiStatusException.class, () -> c.credits().balance());
                assertEquals(1, server.requests.size(), body);
            }
        }
        try (FakeServer server = new FakeServer()) {
            server.script(Reply.json(501, "{}"), Reply.json(200, "{}"));
            assertThrows(InternalServerException.class, () -> TestSupport.client(server).credits().balance());
            assertEquals(1, server.requests.size());
        }
        try (FakeServer server = new FakeServer()) {
            server.script(Reply.json(404, "{}"), Reply.json(200, "{}"));
            assertThrows(NotFoundException.class, () -> TestSupport.client(server).credits().balance());
            assertEquals(1, server.requests.size());
        }
    }

    @Test
    void codesMarkedRetryableAreRetried() {
        for (String code : Arrays.asList("rate_limited", "idempotency_in_progress", "upstream_timeout", "service_unavailable", "internal_error")) {
            try (FakeServer server = new FakeServer()) {
                server.script(Reply.json(409, "{\"code\":\"" + code + "\"}"), Reply.json(200, "{}"));
                TestSupport.client(server).credits().balance();
                assertEquals(2, server.requests.size(), code);
            }
        }
        try (FakeServer server = new FakeServer()) {
            server.script(Reply.json(408, "{}"), Reply.json(200, "{}"));
            TestSupport.client(server).credits().balance();
            assertEquals(2, server.requests.size());
        }
    }

    @Test
    void chargedCallKeepsOneKeyAcrossRetries() {
        try (FakeServer server = new FakeServer()) {
            server.script(Reply.json(503, "{}"), Reply.json(503, "{}"), Reply.json(200, "{}"));
            TestSupport.client(server).statutes().count(COUNT);
            assertEquals(3, server.requests.size());
            String key = server.requests.get(0).headers.get("idempotency-key");
            assertEquals(key, server.requests.get(1).headers.get("idempotency-key"));
            assertEquals(key, server.requests.get(2).headers.get("idempotency-key"));
        }
    }

    @Test
    void callerKeyIsUsedAsIs() {
        try (FakeServer server = new FakeServer()) {
            RequestOptions o = RequestOptions.builder().idempotencyKey("my-own-key-0123456").build();
            TestSupport.client(server).statutes().count(COUNT, o);
            assertEquals("my-own-key-0123456", server.requests.get(0).headers.get("idempotency-key"));
            server.requests.clear();
            TestSupport.client(server).credits().balance(o);
            assertEquals("my-own-key-0123456", server.requests.get(0).headers.get("idempotency-key"), "free calls may carry a key too");
        }
    }

    @Test
    void chargedFiveHundredWithoutAKeyIsNotRetried() {
        try (FakeServer server = new FakeServer()) {
            server.script(Reply.json(500, "{}"), Reply.json(200, "{}"));
            Vaquill c = TestSupport.builder(server, new Recorder()).idempotencyKeys(false).build();
            assertThrows(InternalServerException.class, () -> c.statutes().count(COUNT));
            assertEquals(1, server.requests.size());
            assertNull(server.requests.get(0).headers.get("idempotency-key"));
            // A 429 was refused before processing, so it is still retried.
            server.requests.clear();
            server.script(Reply.json(429, "{}"), Reply.json(200, "{}"));
            c.statutes().count(COUNT);
            assertEquals(2, server.requests.size());
            // A free call is replay safe.
            server.requests.clear();
            server.script(Reply.json(500, "{}"), Reply.json(200, "{}"));
            c.credits().balance();
            assertEquals(2, server.requests.size());
        }
    }

    @Test
    void ambiguousTransportErrorsRetriedOnlyWhenSafe() {
        try (FakeServer server = new FakeServer()) {
            Vaquill noKey = TestSupport.builder(server, new Recorder()).idempotencyKeys(false).build();
            server.script(Reply.dropConnection(), Reply.json(200, "{}"));
            assertThrows(ConnectionException.class, () -> noKey.statutes().count(COUNT));
            assertEquals(1, server.requests.size(), "charged POST without a key is not replayed");
            server.requests.clear();
            noKey.credits().balance();
            assertEquals(2, server.requests.size(), "GET is replayed");
            server.requests.clear();
            Vaquill withKey = TestSupport.client(server);
            withKey.statutes().count(COUNT);
            assertEquals(2, server.requests.size(), "a keyed POST is replayed");
        }
    }

    @Test
    void connectFailuresAlwaysRetried() {
        String dead;
        try (FakeServer server = new FakeServer()) {
            dead = server.url();
        }
        Recorder rec = new Recorder();
        Vaquill c = Vaquill.builder().apiKey(TestSupport.KEY).baseUrl(dead).sleeper(rec.sleeps::add)
                .idempotencyKeys(false).logger(null).build();
        ConnectionException e = assertThrows(ConnectionException.class, () -> c.statutes().count(COUNT));
        assertEquals(2, rec.sleeps.size(), "even a keyless POST is retried when nothing was sent");
        assertFalse(e instanceof RequestTimeoutException);
        assertTrue(e.getMessage().contains("POST"));
    }

    @Test
    void interruptedSleepStopsRetrying() {
        try (FakeServer server = new FakeServer()) {
            server.script(Reply.json(503, "{}"), Reply.json(200, "{}"));
            Vaquill c = TestSupport.builder(server, new Recorder()).sleeper(ms -> {
                throw new InterruptedException();
            }).build();
            VaquillException e = assertThrows(VaquillException.class, () -> c.credits().balance());
            assertTrue(e.getMessage().contains("Interrupted"));
            assertTrue(Thread.interrupted(), "the interrupt flag is restored");
        }
    }

    @Test
    void retryHelpers() {
        for (int i = 0; i < 20; i++) {
            double d = Retry.backoffDelay(10);
            assertTrue(d <= 8.0 && d >= 6.0, "capped at 8 s: " + d);
        }
        List<String> one = Collections.singletonList("1");
        assertEquals(1.0, Retry.parseRetryAfter(Collections.singletonMap("Retry-After", one)));
        assertNull(Retry.parseRetryAfter(Collections.singletonMap("Retry-After", Collections.singletonList("soon"))));
        assertNull(Retry.parseRetryAfter(Collections.singletonMap("Retry-After", Collections.singletonList("NaN"))));
        assertNull(Retry.parseRetryAfter(Collections.singletonMap("retry-after-ms", Collections.singletonList("Infinity"))));
        assertNull(Retry.parseRetryAfter(Collections.<String, List<String>>emptyMap()));
        assertEquals(0.0, Retry.parseRetryAfter(Collections.singletonMap("Retry-After", Collections.singletonList("-5"))));
        assertNotEquals(null, Retry.parseRetryAfter(Collections.singletonMap("Retry-After", one)));
    }
}
