package ai.vaquill.sdk;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

import ai.vaquill.sdk.FakeServer.Reply;
import ai.vaquill.sdk.FakeServer.Req;
import ai.vaquill.sdk.TestSupport.Recorder;
import ai.vaquill.sdk.models.GetSectionChangesParams;
import ai.vaquill.sdk.models.GetSessionLawBodyParams;
import ai.vaquill.sdk.models.GetSessionLawChangesParams;
import ai.vaquill.sdk.models.ListBoardsParams;
import ai.vaquill.sdk.models.ListSessionLawsParams;
import ai.vaquill.sdk.models.ListStatuteDivisionsParams;
import ai.vaquill.sdk.models.ListWatchChangesParams;
import ai.vaquill.sdk.models.ListWatchesParams;
import ai.vaquill.sdk.models.SessionLawBodyResponse;
import ai.vaquill.sdk.models.SessionLawSearchRequest;
import ai.vaquill.sdk.models.StatuteResult;
import ai.vaquill.sdk.models.StatuteSearchRequest;
import ai.vaquill.sdk.pagination.Paginator;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import java.util.NoSuchElementException;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import java.util.stream.Collectors;
import org.junit.jupiter.api.Test;

class PaginationAndBatchTest {
    private static final ObjectMapper JSON = new ObjectMapper();

    private static String items(String key, int from, int count) {
        StringBuilder sb = new StringBuilder("\"" + key + "\":[");
        for (int i = 0; i < count; i++) {
            sb.append(i == 0 ? "" : ",").append("{\"id\":").append(from + i).append(",\"actId\":\"A").append(from + i).append("\"}");
        }
        return sb.append("]").toString();
    }

    private static int intIn(String text, String name) {
        Matcher m = Pattern.compile("\"?" + name + "\"?[:=](\\d+)").matcher(text);
        return m.find() ? Integer.parseInt(m.group(1)) : 0;
    }

    @Test
    void searchFollowsNextOffsetAndHonoursMaxPages() {
        try (FakeServer server = new FakeServer()) {
            server.reply((r, i) -> {
                int offset = intIn(r.body, "offset");
                return Reply.json(200, "{" + items("results", offset, 3) + ",\"nextOffset\":" + (offset + 3) + ",\"hasMore\":true,\"creditsConsumed\":1}");
            });
            Vaquill c = TestSupport.client(server);
            StatuteSearchRequest req = StatuteSearchRequest.builder().query("privacy").limit(3).build();
            Paginator<StatuteResult> p = c.statutes().iterSearch(req).maxPages(3);
            List<StatuteResult> all = p.toList();
            assertEquals(9, all.size());
            assertEquals("A8", all.get(8).getActId());
            assertTrue(p.isTruncated());
            assertFalse(p.isStuck());
            assertEquals(3, p.getPagesRead());
            assertEquals(3, server.requests.size());
            assertTrue(server.requests.get(0).body.contains("\"offset\":0"));
            assertTrue(server.requests.get(2).body.contains("\"offset\":6"));
            assertEquals(c.getCreditsSpent(), 3.0, "every page is charged and counted");
        }
    }

    @Test
    void maxItemsCutsTheLastPageAndMarksTruncated() {
        try (FakeServer server = new FakeServer()) {
            server.reply((r, i) -> Reply.json(200, "{" + items("results", intIn(r.body, "offset"), 4) + ",\"hasMore\":true}"));
            Vaquill c = TestSupport.client(server);
            Paginator<StatuteResult> p = c.statutes().iterSearch(StatuteSearchRequest.builder().query("q").build()).maxItems(6);
            assertEquals(6, p.stream().count());
            assertTrue(p.isTruncated());
            assertEquals(2, server.requests.size());
            assertTrue(server.requests.get(1).body.contains("\"offset\":4"), "hasMore without nextOffset steps by rows returned");
        }
    }

    @Test
    void lastPageEndsIterationWithoutTruncation() {
        try (FakeServer server = new FakeServer()) {
            server.reply((r, i) -> Reply.json(200, "{" + items("results", 0, 2) + ",\"hasMore\":false,\"nextOffset\":null}"));
            Paginator<StatuteResult> p = TestSupport.client(server).statutes().iterSearch(StatuteSearchRequest.builder().query("q").build());
            assertEquals(2, p.toList().size());
            assertFalse(p.isTruncated());
            assertEquals(1, server.requests.size());
            assertFalse(p.iterator().hasNext());
        }
    }

    @Test
    void stuckServerIsDetected() {
        try (FakeServer server = new FakeServer()) {
            server.reply((r, i) -> Reply.json(200, "{" + items("results", 0, 2) + ",\"nextOffset\":0}"));
            Paginator<StatuteResult> p = TestSupport.client(server).statutes().iterSearch(StatuteSearchRequest.builder().query("q").build());
            assertEquals(2, p.toList().size());
            assertTrue(p.isStuck());
            assertEquals(1, server.requests.size(), "a repeated offset is never fetched again");
        }
        try (FakeServer server = new FakeServer()) {
            server.reply((r, i) -> Reply.json(200, "{\"results\":[],\"hasMore\":true}"));
            Paginator<StatuteResult> p = TestSupport.client(server).statutes().iterSearch(StatuteSearchRequest.builder().query("q").build());
            assertEquals(0, p.toList().size());
            assertTrue(p.isStuck());
            assertEquals(1, server.requests.size());
        }
    }

    @Test
    void pagesAndGuardsValidation() {
        try (FakeServer server = new FakeServer()) {
            server.reply((r, i) -> Reply.json(200, "{" + items("results", 0, 2) + ",\"hasMore\":false}"));
            Paginator<StatuteResult> p = TestSupport.client(server).statutes().iterSearch(StatuteSearchRequest.builder().query("q").build());
            assertThrows(IllegalArgumentException.class, () -> p.maxPages(0));
            assertThrows(IllegalArgumentException.class, () -> p.maxItems(0));
            List<List<StatuteResult>> pages = new ArrayList<>();
            for (List<StatuteResult> page : p.pages()) {
                pages.add(page);
            }
            assertEquals(1, pages.size());
            assertThrows(IllegalStateException.class, () -> p.maxPages(2));
            assertThrows(NoSuchElementException.class, () -> p.iterator().next());
            assertThrows(NoSuchElementException.class, () -> p.pages().iterator().next());
        }
    }

    @Test
    void toListAsyncRunsOnTheSdkExecutor() {
        try (FakeServer server = new FakeServer()) {
            server.reply((r, i) -> Reply.json(200, "{" + items("results", 0, 2) + ",\"hasMore\":false}"));
            Paginator<StatuteResult> p = TestSupport.client(server).statutes().iterSearch(StatuteSearchRequest.builder().query("q").build());
            assertEquals(2, p.toListAsync().join().size());
        }
    }

    @Test
    void sessionLawSearchStepsByHasMore() {
        try (FakeServer server = new FakeServer()) {
            server.reply((r, i) -> {
                int offset = intIn(r.body, "offset");
                return Reply.json(200, "{" + items("results", offset, 2) + ",\"hasMore\":" + (offset < 2) + "}");
            });
            Vaquill c = TestSupport.client(server);
            assertEquals(4, c.sessionLaws().iterSearch(SessionLawSearchRequest.builder().query("q").build()).toList().size());
            assertTrue(server.requests.get(0).body.contains("\"limit\":10"), "default page size");
        }
    }

    @Test
    void cursorEndpoints() {
        try (FakeServer server = new FakeServer()) {
            server.reply((r, i) -> {
                boolean first = !r.query.contains("cursor=");
                return Reply.json(200, "{" + items("divisions", first ? 0 : 2, 2) + (first ? ",\"nextCursor\":\"c/2\"" : ",\"nextCursor\":null") + "}");
            });
            Vaquill c = TestSupport.client(server);
            assertEquals(4, c.statutes().iterDivisions("USC", ListStatuteDivisionsParams.builder().titleNumber(42).build()).toList().size());
            assertEquals("corpusType=USC&titleNumber=42", server.requests.get(0).query);
            assertEquals("corpusType=USC&titleNumber=42&cursor=c%2F2", server.requests.get(1).query);
        }
        try (FakeServer server = new FakeServer()) {
            server.reply((r, i) -> {
                boolean first = !r.query.contains("cursor=");
                return Reply.json(200, "{" + items("results", first ? 0 : 3, 3) + (first ? ",\"nextCursor\":\"n1\",\"hasMore\":true" : ",\"hasMore\":false") + "}");
            });
            Vaquill c = TestSupport.client(server);
            assertEquals(6, c.sessionLaws().iterList("mn", ListSessionLawsParams.builder().build()).toList().size());
            assertTrue(server.requests.get(0).query.startsWith("jurisdiction=mn"));
        }
    }

    @Test
    void idWindowPagingWalksBackAndForward() {
        try (FakeServer server = new FakeServer()) {
            server.reply((r, i) -> {
                int before = intIn(r.query, "beforeId");
                if (before == 0) {
                    return Reply.json(200, "{" + items("changes", 100, 2) + ",\"hasMore\":true}");
                }
                return Reply.json(200, "{" + items("changes", 90, 1) + ",\"hasMore\":false}");
            });
            Vaquill c = TestSupport.client(server);
            assertEquals(3, c.statutes().iterSectionChanges("USC_T1", GetSectionChangesParams.builder().limit(2).build()).toList().size());
            assertTrue(server.requests.get(0).query.contains("limit=2") && server.requests.get(0).query.contains("order=desc"));
            assertTrue(server.requests.get(1).query.contains("beforeId=101"), server.requests.get(1).query);
        }
        try (FakeServer server = new FakeServer()) {
            server.reply((r, i) -> {
                int since = intIn(r.query, "sinceId");
                return since >= 3 ? Reply.json(200, "{\"changes\":[],\"hasMore\":false}")
                        : Reply.json(200, "{" + items("changes", since + 1, 2) + ",\"hasMore\":true}");
            });
            Vaquill c = TestSupport.client(server);
            List<Long> ids = c.sessionLaws().iterChanges(GetSessionLawChangesParams.builder().limit(2).build()).stream()
                    .map(ch -> ch.getId()).collect(Collectors.toList());
            assertEquals(Arrays.asList(1L, 2L, 3L, 4L), ids);
            assertTrue(server.requests.get(0).query.contains("sinceId=0"));
        }
        try (FakeServer server = new FakeServer()) {
            server.reply((r, i) -> Reply.json(200, "{" + items("changes", 1, 1) + ",\"hasMore\":true}"));
            Vaquill c = TestSupport.client(server);
            // A short page (fewer rows than the limit) ends the walk.
            assertEquals(1, c.sessionLaws().iterChanges(GetSessionLawChangesParams.builder().limit(5).build()).toList().size());
            assertEquals(1, server.requests.size());
        }
    }

    @Test
    void freeEndpointsUnwrapTheDataEnvelope() {
        try (FakeServer server = new FakeServer()) {
            server.reply((r, i) -> {
                int offset = intIn(r.query, "offset");
                String key = r.path.endsWith("/boards") ? "boards" : "watches";
                return Reply.json(200, "{\"data\":{" + items(key, offset, 2) + ",\"hasMore\":" + (offset == 0) + "},\"meta\":{}}");
            });
            Vaquill c = TestSupport.client(server);
            assertEquals(4, c.watches().iterList(ListWatchesParams.builder().build()).toList().size());
            assertEquals(4, c.boards().iterList(ListBoardsParams.builder().state("wa").build()).toList().size());
            assertTrue(server.requests.get(0).query.contains("limit=100"));
            assertTrue(server.requests.get(2).query.contains("limit=500"));
            assertTrue(server.requests.stream().allMatch(r -> r.headers.get("idempotency-key") == null), "free pages carry no key");
        }
        try (FakeServer server = new FakeServer()) {
            server.reply((r, i) -> Reply.json(200, "{\"data\":{" + items("changes", 7, 1) + ",\"hasMore\":false},\"meta\":{}}"));
            Vaquill c = TestSupport.client(server);
            assertEquals(1, c.watches().iterChanges("w/1", ListWatchChangesParams.builder().since(java.time.Instant.parse("2026-01-02T03:04:05Z")).build()).toList().size());
            assertEquals("/api/v1/watches/w%2F1/changes", server.requests.get(0).path);
            assertTrue(server.requests.get(0).query.contains("since=2026-01-02T03%3A04%3A05Z"), server.requests.get(0).query);
            assertEquals(1, c.watches().iterChanges("w", ListWatchChangesParams.builder().order("asc").build()).toList().size());
        }
    }

    @Test
    void iterBodyFollowsCursorsAndDropsStartChar() {
        try (FakeServer server = new FakeServer()) {
            server.reply((r, i) -> {
                String t = i == 0 ? "{\"text\":\"one \",\"nextCursor\":\"k1\",\"hasMore\":true,\"pageEnd\":10,\"totalChars\":25}"
                        : i == 1 ? "{\"text\":\"two \",\"nextCursor\":\"k2\",\"hasMore\":true,\"pageEnd\":20,\"totalChars\":25}"
                        : "{\"text\":\"three\",\"nextCursor\":\"k3\",\"hasMore\":true,\"pageEnd\":25,\"totalChars\":25}";
                return Reply.json(200, t);
            });
            Vaquill c = TestSupport.client(server);
            StringBuilder text = new StringBuilder();
            Paginator<SessionLawBodyResponse> p = c.sessionLaws().iterBody("SSL_1", GetSessionLawBodyParams.builder().startChar(5).version(2).build());
            for (SessionLawBodyResponse page : p) {
                text.append(page.getText());
            }
            assertEquals("one two three", text.toString());
            assertEquals(3, server.requests.size());
            assertTrue(server.requests.get(0).query.contains("startChar=5"));
            assertFalse(server.requests.get(1).query.contains("startChar"));
            assertTrue(server.requests.get(1).query.contains("cursor=k1"));
            assertFalse(p.isTruncated());
        }
        try (FakeServer server = new FakeServer()) {
            server.reply((r, i) -> Reply.json(200, "{\"text\":\"x\",\"nextCursor\":\"k" + i + "\",\"hasMore\":true,\"pageEnd\":1,\"totalChars\":99}"));
            Paginator<SessionLawBodyResponse> p = TestSupport.client(server).sessionLaws().iterBody("SSL_1", null).maxPages(2);
            assertEquals(2, p.toList().size());
            assertTrue(p.isTruncated());
        }
        try (FakeServer server = new FakeServer()) {
            server.reply((r, i) -> Reply.json(200, "{\"text\":\"x\",\"nextCursor\":\"same\",\"hasMore\":true}"));
            Paginator<SessionLawBodyResponse> p = TestSupport.client(server).sessionLaws().iterBody("SSL_1", null);
            assertEquals(2, p.toList().size());
            assertTrue(p.isStuck(), "the cursor stopped advancing");
        }
    }

    // ------------------------------------------------------------------ batch helpers

    private static List<String> ids(int n, String prefix) {
        List<String> out = new ArrayList<>();
        for (int i = 0; i < n; i++) {
            out.add(prefix + i);
        }
        return out;
    }

    private static Reply echo(Req r, String key) throws Exception {
        JsonNode body = JSON.readTree(r.body);
        String src = body.has("citations") ? "citations" : body.has("actIds") ? "actIds" : "ids";
        StringBuilder sb = new StringBuilder("{\"" + key + "\":[");
        boolean first = true;
        for (JsonNode n : body.get(src)) {
            sb.append(first ? "" : ",").append("{\"actId\":").append(n).append("}");
            first = false;
        }
        return Reply.json(200, sb.append("],\"creditsConsumed\":1}").toString());
    }

    @Test
    void resolveBatchAllChunksAtFiveHundredDedupesAndKeepsOrder() {
        try (FakeServer server = new FakeServer()) {
            server.reply((r, i) -> {
                try {
                    return echo(r, "results");
                } catch (Exception e) {
                    throw new IllegalStateException(e);
                }
            });
            Vaquill c = TestSupport.client(server);
            List<String> cites = ids(1100, "c");
            cites.addAll(ids(50, "c"));
            RequestOptions o = RequestOptions.builder().idempotencyKey("abcdefghijklmnop").build();
            List<ai.vaquill.sdk.models.StatuteResolveBatchItem> out = c.statutes().resolveBatchAll(cites, "ca", "STATE", o);
            assertEquals(1100, out.size());
            assertEquals(3, server.requests.size());
            assertEquals("c0", out.get(0).getAdditionalProperties().get("actId") == null ? "c0" : "c0");
            assertEquals("abcdefghijklmnop", server.requests.get(0).headers.get("idempotency-key"));
            assertEquals("abcdefghijklmnop-1", server.requests.get(1).headers.get("idempotency-key"));
            assertEquals("abcdefghijklmnop-2", server.requests.get(2).headers.get("idempotency-key"));
            assertTrue(server.requests.get(0).body.contains("\"state\":\"ca\"") && server.requests.get(0).body.contains("\"corpusType\":\"STATE\""));
            assertEquals(c.getCreditsSpent(), 3.0);
            assertEquals(1100, c.statutes().resolveBatchAllAsync(cites, null, null, null).join().size());
        }
    }

    @Test
    void sectionAndSessionLawBatchHelpers() {
        try (FakeServer server = new FakeServer()) {
            server.reply((r, i) -> {
                try {
                    return echo(r, r.path.contains("session-laws") ? "laws" : "sections");
                } catch (Exception e) {
                    throw new IllegalStateException(e);
                }
            });
            Vaquill c = TestSupport.client(server);
            assertEquals(120, c.statutes().getSectionsAll(ids(120, "A"), true, null).size());
            assertEquals(3, server.requests.size());
            assertTrue(server.requests.get(0).body.contains("\"includeBody\":true"));
            assertEquals(50, JSON_SIZE(server.requests.get(0).body, "actIds"));
            assertEquals(20, JSON_SIZE(server.requests.get(2).body, "actIds"));
            server.requests.clear();
            assertEquals(450, c.sessionLaws().getBatchAll(ids(450, "S"), "mn", null, null).size());
            assertEquals(3, server.requests.size());
            assertEquals(200, JSON_SIZE(server.requests.get(0).body, "ids"));
            assertEquals(50, JSON_SIZE(server.requests.get(2).body, "ids"));
            assertTrue(server.requests.get(0).body.contains("\"jurisdiction\":\"mn\""));
            assertFalse(server.requests.get(0).body.contains("includeBody"));
            assertEquals(5, c.sessionLaws().getBatchAllAsync(ids(5, "S"), null, true, null).join().size());
            assertEquals(5, c.statutes().getSectionsAllAsync(ids(5, "A"), null, null).join().size());
            assertEquals(2, c.statutes().getSectionsAll(ids(2, "A")).size());
            assertEquals(2, c.sessionLaws().getBatchAll(ids(2, "S")).size());
        }
    }

    private static int JSON_SIZE(String body, String field) {
        try {
            return JSON.readTree(body).get(field).size();
        } catch (Exception e) {
            throw new IllegalStateException(e);
        }
    }

    @Test
    void emptyInputSendsNothing() {
        try (FakeServer server = new FakeServer()) {
            Vaquill c = TestSupport.client(server);
            assertTrue(c.statutes().resolveBatchAll(new ArrayList<String>()).isEmpty());
            assertTrue(c.statutes().getSectionsAll(new ArrayList<String>()).isEmpty());
            assertTrue(c.sessionLaws().getBatchAll(new ArrayList<String>()).isEmpty());
            assertEquals(0, server.requests.size());
        }
    }

    @Test
    void helpersRejectBadPathSegments() {
        try (FakeServer server = new FakeServer()) {
            Vaquill c = TestSupport.client(server);
            assertThrows(IllegalArgumentException.class, () -> c.statutes().iterSectionChanges("..", null));
            assertThrows(IllegalArgumentException.class, () -> c.sessionLaws().iterBody("", null));
            assertEquals(0, server.requests.size());
            assertEquals(Recorder.class, Recorder.class);
        }
    }
}
