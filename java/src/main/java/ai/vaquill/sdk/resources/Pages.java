package ai.vaquill.sdk.resources;

import ai.vaquill.sdk.ResponseParseException;
import ai.vaquill.sdk.internal.Json;
import ai.vaquill.sdk.internal.Transport;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.JsonNode;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.function.Function;

/** Shared plumbing for the paginators and batch helpers. */
final class Pages {
    private static final TypeReference<LinkedHashMap<String, Object>> MAP = new TypeReference<LinkedHashMap<String, Object>>() {};

    private Pages() {}

    static Function<Map<String, Object>, JsonNode> get(final Transport t, final String path, final boolean charged,
            final boolean unwrapData) {
        return params -> {
            JsonNode body = t.execute(Transport.Call.of("GET", path).query(params).charged(charged), JsonNode.class, null).getData();
            return unwrapData && body != null && body.has("data") ? body.get("data") : body;
        };
    }

    static Function<Map<String, Object>, JsonNode> post(final Transport t, final String path) {
        return params -> t.execute(Transport.Call.of("POST", path).body(params).charged(true), JsonNode.class, null).getData();
    }

    static <T> Function<JsonNode, T> parser(final Class<T> type) {
        return node -> {
            try {
                return Json.treeToValue(node, type);
            } catch (JsonProcessingException e) {
                throw new ResponseParseException("Page item did not match the expected shape: " + e.getOriginalMessage(),
                        null, 200, e);
            }
        };
    }

    /** A request model as its wire-name map. */
    static Map<String, Object> wire(Object model) {
        return Json.MAPPER.convertValue(model, MAP);
    }

    static Map<String, Object> merge(Map<String, Object> base, Map<String, Object> more) {
        Map<String, Object> out = new LinkedHashMap<String, Object>(base);
        if (more != null) {
            out.putAll(more);
        }
        return out;
    }

    static <T> java.util.List<java.util.List<T>> chunks(java.util.List<T> items, int size) {
        java.util.List<java.util.List<T>> out = new java.util.ArrayList<java.util.List<T>>();
        java.util.List<T> unique = new java.util.ArrayList<T>(new java.util.LinkedHashSet<T>(items));
        for (int i = 0; i < unique.size(); i += size) {
            out.add(new java.util.ArrayList<T>(unique.subList(i, Math.min(i + size, unique.size()))));
        }
        return out;
    }
}
