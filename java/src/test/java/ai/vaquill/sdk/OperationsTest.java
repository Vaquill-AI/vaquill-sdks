package ai.vaquill.sdk;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

import ai.vaquill.sdk.GeneratedCases.Case;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.util.ArrayList;
import java.util.List;
import java.util.function.Function;
import java.util.regex.Pattern;
import org.junit.jupiter.api.DynamicTest;
import org.junit.jupiter.api.TestFactory;

/** One request per operation (and per overload) against a fake server, asserting method, path, query and body. */
class OperationsTest {
    private static final ObjectMapper JSON = new ObjectMapper();
    private static final Pattern UUID = Pattern.compile("[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}");

    @TestFactory
    List<DynamicTest> everyOperationSendsTheRightRequest() {
        List<DynamicTest> tests = new ArrayList<>();
        for (Case k : GeneratedCases.all()) {
            tests.add(DynamicTest.dynamicTest(k.operationId, () -> run(k)));
        }
        assertEquals(36, tests.size());
        return tests;
    }

    private void run(Case k) throws Exception {
        try (FakeServer server = new FakeServer()) {
            server.reply((r, i) -> k.status == 204 ? FakeServer.Reply.json(204, "")
                    : FakeServer.Reply.json(k.status, "{\"creditsConsumed\":1}"));
            try (Vaquill client = TestSupport.client(server)) {
                for (Function<Vaquill, Object> call : k.calls) {
                    call.apply(client);
                }
            }
            assertEquals(k.calls.size(), server.requests.size(), k.operationId);
            for (FakeServer.Req r : server.requests) {
                assertEquals(k.httpMethod, r.method, k.operationId);
                assertEquals(k.path, r.path, k.operationId);
                assertEquals(k.query, r.query, k.operationId);
                if (k.body == null) {
                    assertEquals("", r.body, k.operationId);
                } else {
                    JsonNode expected = JSON.readTree(k.body);
                    assertEquals(expected, JSON.readTree(r.body), k.operationId);
                    assertEquals("application/json", r.headers.get("content-type"));
                }
                assertEquals("Bearer " + TestSupport.KEY, r.headers.get("authorization"));
                assertTrue(r.headers.get("user-agent").startsWith("vaquill-java/0.1.0 "), r.headers.get("user-agent"));
                assertEquals("application/json", r.headers.get("accept"));
                String key = r.headers.get("idempotency-key");
                if (k.charged) {
                    assertNotNull(key, k.operationId + " is charged and must carry an Idempotency-Key");
                    assertTrue(UUID.matcher(key).matches(), key);
                } else {
                    assertNull(key, k.operationId + " is free and must not carry an Idempotency-Key");
                }
            }
            long withOptions = server.requests.stream().filter(r -> "1".equals(r.headers.get("x-case"))).count();
            assertTrue(withOptions > 0 && withOptions < server.requests.size(), "per-call headers reach the wire");
            if (k.charged) {
                // Each call spent 1 credit.
                // (the client above is closed; spend is checked in SpendGuardTest)
                assertTrue(server.requests.size() > 0);
            }
        }
    }
}
