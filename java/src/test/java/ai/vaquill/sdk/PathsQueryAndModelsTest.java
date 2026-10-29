package ai.vaquill.sdk;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

import ai.vaquill.sdk.FakeServer.Reply;
import ai.vaquill.sdk.internal.Json;
import ai.vaquill.sdk.internal.Paths;
import ai.vaquill.sdk.internal.QueryEncoder;
import ai.vaquill.sdk.models.ApiFieldError;
import ai.vaquill.sdk.models.ExternalCreditBalanceResponse;
import ai.vaquill.sdk.models.GetSectionBodyParams;
import ai.vaquill.sdk.models.StatuteCountRequest;
import java.time.Instant;
import java.time.LocalDate;
import java.time.OffsetDateTime;
import java.time.ZoneOffset;
import java.util.Arrays;
import java.util.LinkedHashMap;
import java.util.Map;
import org.junit.jupiter.api.Test;

class PathsQueryAndModelsTest {
    @Test
    void segmentsRejectTraversalAndEmpty() {
        assertThrows(IllegalArgumentException.class, () -> Paths.seg(""));
        assertThrows(IllegalArgumentException.class, () -> Paths.seg("."));
        assertThrows(IllegalArgumentException.class, () -> Paths.seg(".."));
        assertThrows(IllegalArgumentException.class, () -> Paths.seg((String) null));
        assertEquals("a%2Fb%20c", Paths.seg("a/b c"));
        assertEquals("100%25", Paths.seg("100%"));
        assertEquals("%C3%A9", Paths.seg("é"));
        assertEquals("a-b_c.d~e", Paths.seg("a-b_c.d~e"));
        assertEquals("...", Paths.seg("..."));
        assertEquals("42", Paths.seg(42L));
    }

    @Test
    void theRawRequestPathCarriesTheEncodedSegmentAndBadOnesSendNothing() {
        try (FakeServer server = new FakeServer()) {
            Vaquill c = TestSupport.client(server);
            c.statutes().getSection("a/b c");
            assertEquals("/api/v1/us/statutes/section/a%2Fb%20c", server.requests.get(0).path);
            assertThrows(IllegalArgumentException.class, () -> c.statutes().getSection(".."));
            assertThrows(IllegalArgumentException.class, () -> c.statutes().getSection(""));
            assertEquals(1, server.requests.size());
        }
    }

    @Test
    void queryEncodingFollowsTheWireRules() {
        Map<String, Object> q = new LinkedHashMap<>();
        q.put("flag", true);
        q.put("off", false);
        q.put("none", null);
        q.put("at", Instant.parse("2026-01-02T03:04:05Z"));
        q.put("odt", OffsetDateTime.of(2026, 1, 2, 3, 4, 5, 0, ZoneOffset.ofHours(2)));
        q.put("zdt", OffsetDateTime.of(2026, 1, 2, 3, 4, 5, 0, ZoneOffset.UTC).toZonedDateTime());
        q.put("day", LocalDate.of(2026, 3, 4));
        q.put("tags", Arrays.asList("a b", "c", null));
        q.put("arr", new String[] {"x", "y"});
        q.put("n", 7L);
        q.put("d", 1.5d);
        q.put("whole", 2.0d);
        String out = QueryEncoder.encode(q);
        assertEquals("flag=true&off=false&at=2026-01-02T03%3A04%3A05Z&odt=2026-01-02T03%3A04%3A05%2B02%3A00"
                + "&zdt=2026-01-02T03%3A04%3A05Z&day=2026-03-04&tags=a%20b&tags=c&arr=x&arr=y&n=7&d=1.5&whole=2", out);
        assertEquals("", QueryEncoder.encode(null));
        assertEquals("", QueryEncoder.encode(new LinkedHashMap<String, Object>()));
        assertEquals("k%26=v%3D", QueryEncoder.encode(Collections_singleton("k&", "v=")));
    }

    private static Map<String, Object> Collections_singleton(String k, Object v) {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put(k, v);
        return m;
    }

    @Test
    void localDateParamsReachTheWireAsPlainDates() {
        try (FakeServer server = new FakeServer()) {
            TestSupport.client(server).statutes().getSectionBody("ACT_1",
                    GetSectionBodyParams.builder().asOf(LocalDate.of(2025, 5, 6)).build());
            assertTrue(server.requests.get(0).query.contains("asOf=2025-05-06"), server.requests.get(0).query);
        }
    }

    // ------------------------------------------------------------------ models

    @Test
    void requiredFieldsAreCheckedAtBuildTime() {
        assertThrows(NullPointerException.class, () -> ApiFieldError.builder().build());
        ApiFieldError ok = ApiFieldError.builder().loc(Arrays.<Object>asList("body", 0)).msg("m").type("t").build();
        assertEquals("m", ok.getMsg());
    }

    @Test
    void serialisationOmitsNullsAndKeepsUnknownMembers() throws Exception {
        StatuteCountRequest r = StatuteCountRequest.builder().query("tax").excludeRepealed(false).build();
        assertEquals("{\"excludeRepealed\":false,\"query\":\"tax\"}", r.toJson());
        ExternalCreditBalanceResponse b = Json.MAPPER.readValue(
                "{\"plan\":\"pro\",\"creditsRemaining\":12.5,\"brandNewField\":{\"x\":1}}", ExternalCreditBalanceResponse.class);
        assertEquals("pro", b.getPlan());
        assertEquals(12.5, b.getCreditsRemaining());
        assertTrue(b.getAdditionalProperties().containsKey("brandNewField"));
        assertTrue(b.toJson().contains("brandNewField"), "unknown members survive a round trip");
        assertTrue(b.toString().startsWith("ExternalCreditBalanceResponse{"));
    }

    @Test
    void modelsCompareByContent() {
        StatuteCountRequest a = StatuteCountRequest.builder().query("x").titleNumber(1L).build();
        StatuteCountRequest b = StatuteCountRequest.builder().query("x").titleNumber(1L).build();
        StatuteCountRequest c = StatuteCountRequest.builder().query("y").build();
        assertEquals(a, b);
        assertEquals(a.hashCode(), b.hashCode());
        assertNotEquals(a, c);
        assertFalse(a.equals(null));
        assertFalse(a.equals("x"));
    }

    @Test
    void balanceParsesEndToEnd() {
        try (FakeServer server = new FakeServer()) {
            server.script(Reply.json(200, "{\"plan\":\"free\",\"creditsRemaining\":3}"));
            ExternalCreditBalanceResponse r = TestSupport.client(server).credits().balance();
            assertEquals("free", r.getPlan());
        }
    }
}
