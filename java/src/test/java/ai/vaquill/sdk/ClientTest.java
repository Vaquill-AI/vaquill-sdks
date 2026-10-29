package ai.vaquill.sdk;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertSame;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

import ai.vaquill.sdk.FakeServer.Reply;
import ai.vaquill.sdk.TestSupport.Recorder;
import ai.vaquill.sdk.models.StatuteResolveBatchRequest;
import ai.vaquill.sdk.models.StatuteSectionResponse;
import com.fasterxml.jackson.databind.JsonNode;
import java.time.Duration;
import java.util.Collections;
import java.util.HashMap;
import java.util.Map;
import org.junit.jupiter.api.Test;

class ClientTest {
    private static Vaquill.Builder noEnv() {
        return Vaquill.builder().env(k -> null);
    }

    @Test
    void versionMatchesThePom() {
        assertEquals(System.getProperty("project.version"), Version.VERSION);
        assertEquals("0.1.0", Version.VERSION);
    }

    @Test
    void apiKeyResolution() {
        VaquillException none = assertThrows(VaquillException.class, () -> noEnv().build());
        assertTrue(none.getMessage().contains("VAQUILL_API_KEY"));
        Map<String, String> env = new HashMap<>();
        env.put("VAQUILL_API_KEY", "  vq_key_fromenv\n");
        env.put("VAQUILL_BASE_URL", "https://example.test/");
        Vaquill fromEnv = Vaquill.builder().env(env::get).build();
        assertEquals("https://example.test", fromEnv.getBaseUrl());
        assertTrue(fromEnv.toString().contains("example.test"));
        Vaquill explicit = noEnv().apiKey("vq_key_abc\n").build();
        assertEquals(Vaquill.DEFAULT_BASE_URL, explicit.getBaseUrl());
        VaquillException prefix = assertThrows(VaquillException.class, () -> noEnv().apiKey("sk_live_secret_value").build());
        assertFalse(prefix.getMessage().contains("sk_live_secret_value"), "the key is never echoed");
        VaquillException space = assertThrows(VaquillException.class, () -> noEnv().apiKey("vq_key_a b").build());
        assertFalse(space.getMessage().contains("vq_key_a b"));
        assertThrows(VaquillException.class, () -> noEnv().apiKey("   ").build());
        assertThrows(VaquillException.class, () -> noEnv().apiKey("vq_key_café").build());
    }

    @Test
    void builderValidation() {
        assertThrows(IllegalArgumentException.class, () -> Vaquill.builder().maxRetries(-1));
        assertThrows(IllegalArgumentException.class, () -> Vaquill.builder().maxCredits(-1));
        assertThrows(IllegalArgumentException.class, () -> Vaquill.builder().maxCredits(Double.NaN));
        assertThrows(IllegalArgumentException.class, () -> Vaquill.builder().timeout(Duration.ofSeconds(-1)));
        assertThrows(IllegalArgumentException.class, () -> Vaquill.builder().defaultHeader("", "x"));
        assertThrows(IllegalArgumentException.class, () -> RequestOptions.builder().maxRetries(-1));
        assertThrows(IllegalArgumentException.class, () -> RequestOptions.builder().header("", "x"));
        assertThrows(IllegalArgumentException.class, () -> RequestOptions.builder().timeout(Duration.ofSeconds(-1)));
        assertNotNull(RequestOptions.builder().timeout(Duration.ZERO).maxRetries(0).build());
    }

    @Test
    void idempotencyKeyValidation() {
        for (String bad : new String[] {null, "", "short", "has space in it 123456", "tab\t1234567890123456", repeat('a', 256)}) {
            assertThrows(IllegalArgumentException.class, () -> RequestOptions.builder().idempotencyKey(bad), String.valueOf(bad));
        }
        assertEquals(repeat('a', 255), RequestOptions.builder().idempotencyKey(repeat('a', 255)).build().getIdempotencyKey());
        assertEquals("0123456789abcdef", RequestOptions.builder().idempotencyKey("0123456789abcdef").build().getIdempotencyKey());
    }

    private static String repeat(char c, int n) {
        StringBuilder sb = new StringBuilder();
        for (int i = 0; i < n; i++) {
            sb.append(c);
        }
        return sb.toString();
    }

    @Test
    void headersMergeCaseInsensitivelyAndProtectAuth() {
        try (FakeServer server = new FakeServer()) {
            Vaquill c = TestSupport.builder(server, new Recorder())
                    .defaultHeader("X-Team", "one")
                    .defaultHeader("x-team", "two")
                    .defaultHeader("authorization", "Bearer evil")
                    .defaultHeader("Idempotency-Key", "evil-evil-evil-evil")
                    .defaultHeaders(Collections.singletonMap("X-Other", "o"))
                    .build();
            RequestOptions opts = RequestOptions.builder().header("X-TEAM", "three").header("Authorization", "evil").build();
            c.credits().balance(opts);
            FakeServer.Req r = server.requests.get(0);
            assertEquals("three", r.headers.get("x-team"));
            assertEquals("o", r.headers.get("x-other"));
            assertEquals("Bearer " + TestSupport.KEY, r.headers.get("authorization"));
            assertNull(r.headers.get("idempotency-key"));
        }
    }

    @Test
    void timeoutsAndZeroDisables() {
        try (FakeServer server = new FakeServer()) {
            Reply slow = Reply.json(200, "{}");
            slow.delayMillis = 400;
            server.script(slow);
            Vaquill quick = TestSupport.builder(server, new Recorder()).timeout(Duration.ofMillis(100)).maxRetries(0).build();
            assertThrows(RequestTimeoutException.class, () -> quick.credits().balance());
            Vaquill off = TestSupport.builder(server, new Recorder()).timeout(Duration.ZERO).maxRetries(0).build();
            assertNotNull(off.credits().balance());
            RequestOptions perCall = RequestOptions.builder().timeout(Duration.ofMillis(100)).build();
            assertThrows(RequestTimeoutException.class, () -> off.credits().balance(perCall));
            RequestOptions disable = RequestOptions.builder().timeout(Duration.ZERO).build();
            assertNotNull(quick.credits().balance(disable));
        }
    }

    @Test
    void responseMetadata() {
        try (FakeServer server = new FakeServer()) {
            server.script(Reply.json(200, "{\"creditsConsumed\":2.5,\"actId\":\"A\"}")
                    .header("X-Request-ID", "req-1").header("Idempotent-Replayed", "true")
                    .header("X-RateLimit-Limit", "60").header("X-RateLimit-Remaining", "59")
                    .header("X-RateLimit-Reset", "12.5").header("X-RateLimit-Limit-Day", "bad"));
            Vaquill c = TestSupport.client(server);
            Response<StatuteSectionResponse> r = c.statutes().getSectionWithResponse("A");
            assertEquals(200, r.getStatusCode());
            assertEquals("req-1", r.getRequestId());
            assertEquals("req-1", r.getHeader("x-request-id"));
            assertEquals(2.5, r.getCreditsConsumed());
            assertTrue(r.isIdempotentReplayed());
            assertEquals(0.0, r.getCreditsChargedThisCall(), "a replay is not charged again");
            assertEquals(0.0, c.getCreditsSpent());
            assertEquals(60L, r.getRateLimit().getLimit());
            assertEquals(59L, r.getRateLimit().getRemaining());
            assertEquals(12.5, r.getRateLimit().getReset());
            assertNull(r.getRateLimit().getLimitDay());
            assertNull(r.getRateLimit().getRemainingDay());
            assertNull(r.getRateLimit().getResetDay());
            assertTrue(r.getRateLimit().toString().contains("limit=60"));
            assertTrue(r.toString().contains("req-1"));
            assertNotNull(r.getJson());
            assertEquals("A", r.getData().getAdditionalProperties().get("actId"));
        }
    }

    @Test
    void creditsFromMetaBlockAndRawRequest() {
        try (FakeServer server = new FakeServer()) {
            server.script(Reply.json(200, "{\"data\":{},\"meta\":{\"creditsConsumed\":3}}"));
            Vaquill c = TestSupport.client(server);
            Response<JsonNode> r = c.rawRequest("GET", "/api/v1/anything", Collections.singletonMap("a", "b"), null, true, null);
            assertEquals(3.0, r.getCreditsConsumed());
            assertEquals(3.0, c.getCreditsSpent());
            assertEquals("a=b", server.requests.get(0).query);
            assertNotNull(server.requests.get(0).headers.get("idempotency-key"));
            assertEquals(3.0, c.rawRequestAsync("GET", "/x", null, null, true, null).join().getCreditsConsumed());
        }
    }

    @Test
    void malformedSuccessBodiesRaiseResponseParseException() {
        try (FakeServer server = new FakeServer()) {
            Vaquill c = TestSupport.builder(server, new Recorder()).build();
            server.script(Reply.json(200, "{not json").header("X-Request-ID", "r9"));
            ResponseParseException bad = assertThrows(ResponseParseException.class, () -> c.credits().balance());
            assertEquals("r9", bad.getRequestId());
            assertEquals(200, bad.getStatusCode());
            assertTrue(bad.toString().contains("r9"));
            server.script(Reply.json(200, "{\"results\":\"not-a-list\"}"));
            assertThrows(ResponseParseException.class,
                    () -> c.statutes().resolveBatch(StatuteResolveBatchRequest.builder().citations(Collections.singletonList("c")).build()));
            server.script(Reply.json(200, ""));
            assertThrows(ResponseParseException.class, () -> c.credits().balance());
            server.script(Reply.json(200, "[1,2]"));
            assertThrows(ResponseParseException.class, () -> c.credits().balance());
        }
    }

    @Test
    void deprecationWarnsOncePerEndpointAndKeysAreRedacted() {
        try (FakeServer server = new FakeServer()) {
            Recorder rec = new Recorder();
            server.script(Reply.json(200, "{}").header("Deprecation", "true").header("Sunset", "Wed, 01 Jan 2031 00:00:00 GMT")
                    .header("Idempotency-Status", "unavailable"));
            Vaquill c = TestSupport.builder(server, rec).build();
            c.credits().balance();
            c.credits().balance();
            c.pricing().get();
            long warnings = rec.logs.stream().filter(l -> l.contains("is deprecated")).count();
            assertEquals(2, warnings, "once for balance, once for pricing");
            assertTrue(rec.logs.stream().anyMatch(l -> l.contains("Sunset: Wed, 01 Jan 2031")));
            assertTrue(rec.logs.stream().anyMatch(l -> l.contains("could not deduplicate")));
            // A key that appears in a logged URL is redacted.
            c.rawRequest("GET", "/api/v1/echo/" + TestSupport.KEY, null, null, false, null);
            assertTrue(rec.logs.stream().anyMatch(l -> l.contains("vq_key_***")));
            assertTrue(rec.logs.stream().noneMatch(l -> l.contains(TestSupport.KEY)), rec.logs.toString());
            c.statutes().count(ai.vaquill.sdk.models.StatuteCountRequest.builder().build());
            String sent = server.requests.get(server.requests.size() - 1).headers.get("idempotency-key");
            assertTrue(rec.logs.stream().noneMatch(l -> l.contains(sent)), "idempotency keys are logged by prefix only");
            assertTrue(rec.logs.stream().anyMatch(l -> l.contains(sent.substring(0, 8) + "...")));
        }
    }

    @Test
    void toBuilderSharesSpendAndNoopLogger() {
        try (FakeServer server = new FakeServer()) {
            server.script(Reply.json(200, "{\"creditsConsumed\":1}"));
            Vaquill a = TestSupport.builder(server, new Recorder()).build();
            Vaquill b = a.toBuilder().maxRetries(0).logger(null).defaultHeader("X-B", "1").build();
            a.statutes().count(ai.vaquill.sdk.models.StatuteCountRequest.builder().build());
            b.statutes().count(ai.vaquill.sdk.models.StatuteCountRequest.builder().build());
            assertEquals(2.0, a.getCreditsSpent());
            assertEquals(2.0, b.getCreditsSpent());
            assertEquals("1", server.requests.get(1).headers.get("x-b"));
            assertSame(a.statutes(), a.statutes());
            VaquillLogger.noop().log(java.lang.System.Logger.Level.INFO, "x");
            VaquillLogger.system().log(java.lang.System.Logger.Level.TRACE, "x");
            a.close();
            // Async still works after close: the pool is recreated lazily.
            assertNotNull(a.credits().balanceAsync().join());
        }
    }

    @Test
    void redirectsAreNotFollowedAndAreErrors() {
        try (FakeServer server = new FakeServer()) {
            server.script(Reply.json(302, "").header("Location", "http://127.0.0.1:1/"));
            Vaquill c = TestSupport.client(server);
            ApiStatusException e = assertThrows(ApiStatusException.class, () -> c.credits().balance());
            assertEquals(302, e.getStatusCode());
            assertEquals("HTTP 302", e.getMessage());
        }
    }
}
