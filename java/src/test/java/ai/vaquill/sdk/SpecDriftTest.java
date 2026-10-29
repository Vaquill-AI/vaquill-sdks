package ai.vaquill.sdk;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.io.File;
import java.lang.reflect.Method;
import java.util.HashMap;
import java.util.Iterator;
import java.util.Map;
import org.junit.jupiter.api.Assumptions;
import org.junit.jupiter.api.Test;

/** Fails when the committed generated sources and the OpenAPI contract disagree. */
class SpecDriftTest {
    private static JsonNode spec() throws Exception {
        String path = System.getProperty("vaquill.spec");
        File f = path == null ? null : new File(path);
        Assumptions.assumeTrue(f != null && f.exists(), "openapi/vaquill-us.json not found next to java/");
        return new ObjectMapper().readTree(f);
    }

    @Test
    void everySpecOperationHasAMatchingMethod() throws Exception {
        JsonNode paths = spec().get("paths");
        Map<String, OperationIndex.Entry> byId = new HashMap<>();
        for (OperationIndex.Entry e : OperationIndex.ALL) {
            byId.put(e.getOperationId(), e);
        }
        int seen = 0;
        Iterator<Map.Entry<String, JsonNode>> pit = paths.fields();
        while (pit.hasNext()) {
            Map.Entry<String, JsonNode> p = pit.next();
            Iterator<Map.Entry<String, JsonNode>> mit = p.getValue().fields();
            while (mit.hasNext()) {
                Map.Entry<String, JsonNode> m = mit.next();
                JsonNode op = m.getValue();
                if (!op.has("operationId")) {
                    continue;
                }
                seen++;
                OperationIndex.Entry e = byId.get(op.get("operationId").asText());
                assertNotNull(e, "no SDK entry for " + op.get("operationId"));
                assertEquals(m.getKey().toUpperCase(), e.getHttpMethod());
                assertEquals(p.getKey(), e.getPath());
                boolean charged = false;
                for (JsonNode param : op.path("parameters")) {
                    if ("Idempotency-Key".equals(param.path("name").asText())) {
                        charged = true;
                    }
                }
                assertEquals(charged, e.isCharged(), e.getOperationId());
                assertTrue(hasMethod(e), "missing method " + e.getResource() + "." + e.getMethod());
            }
        }
        assertEquals(seen, OperationIndex.ALL.size());
        assertEquals(36, seen);
    }

    private static boolean hasMethod(OperationIndex.Entry e) throws Exception {
        Method accessor = Vaquill.class.getMethod(e.getResource());
        Class<?> resource = accessor.getReturnType();
        boolean sync = false;
        boolean async = false;
        boolean meta = false;
        for (Method m : resource.getMethods()) {
            sync |= m.getName().equals(e.getMethod());
            async |= m.getName().equals(e.getMethod() + "Async");
            meta |= m.getName().equals(e.getMethod() + "WithResponse");
        }
        return sync && async && meta;
    }

    @Test
    void everySchemaHasAModelClass() throws Exception {
        Iterator<String> names = spec().get("components").get("schemas").fieldNames();
        int n = 0;
        while (names.hasNext()) {
            String name = names.next();
            Class.forName("ai.vaquill.sdk.models." + name);
            n++;
        }
        assertTrue(n >= 100, "expected the full schema set, got " + n);
    }
}
