package ai.vaquill.sdk.pagination;

import com.fasterxml.jackson.databind.JsonNode;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/** The paging schemes the Vaquill API uses. */
public final class PageStyles {
    private PageStyles() {}

    /** Converts a JSON scalar to a Java value (integers become Long) so parameter maps compare reliably. */
    static Object scalar(JsonNode n) {
        if (n == null || n.isNull() || n.isMissingNode()) {
            return null;
        }
        if (n.isIntegralNumber()) {
            return n.asLong();
        }
        if (n.isNumber()) {
            return n.asDouble();
        }
        if (n.isBoolean()) {
            return n.asBoolean();
        }
        return n.asText();
    }

    private static Map<String, Object> with(Map<String, Object> params, String key, Object value) {
        Map<String, Object> out = new LinkedHashMap<String, Object>(params);
        out.put(key, value);
        return out;
    }

    /** Opaque {@code cursor} request parameter, {@code nextCursor} response member. */
    public static PageStyle cursor() {
        return (params, body, items) -> {
            JsonNode nxt = body.get("nextCursor");
            return nxt == null || nxt.isNull() || nxt.asText().isEmpty() ? null : with(params, "cursor", scalar(nxt));
        };
    }

    /** {@code sinceId} or {@code beforeId} taken from the last item's {@code id}; stops on an empty or short page. */
    public static PageStyle idWindow(final String param) {
        return (params, body, items) -> {
            if (items.isEmpty()) {
                return null;
            }
            Object limit = params.get("limit");
            if (limit instanceof Number && items.size() < ((Number) limit).longValue()) {
                return null;
            }
            JsonNode last = items.get(items.size() - 1);
            Object id = last != null && last.isObject() ? scalar(last.get("id")) : null;
            return id == null ? null : with(params, param, id);
        };
    }

    /** Like {@link #idWindow(String)} but also stops when the server says {@code hasMore: false}. */
    public static PageStyle hasMoreId(final String param) {
        final PageStyle inner = idWindow(param);
        return (params, body, items) -> {
            JsonNode more = body.get("hasMore");
            if (more != null && more.isBoolean() && !more.asBoolean()) {
                return null;
            }
            return inner.next(params, body, items);
        };
    }

    /** Offset paging for responses with {@code hasMore} but no {@code nextOffset}. */
    public static PageStyle hasMoreOffset() {
        return (params, body, items) -> {
            JsonNode more = body.get("hasMore");
            boolean hasMore;
            if (more == null || more.isNull()) {
                // No flag: a full page means there may be another.
                long limit = params.get("limit") instanceof Number ? ((Number) params.get("limit")).longValue() : 0;
                hasMore = limit > 0 && items.size() >= limit;
            } else {
                hasMore = more.asBoolean();
            }
            if (!hasMore || items.isEmpty()) {
                return null;
            }
            return with(params, "offset", offsetOf(params) + items.size());
        };
    }

    /**
     * Offset paging for statute search: follow {@code nextOffset} when the server gives one (boolean
     * match type), otherwise step by the rows returned while {@code hasMore} is true.
     */
    public static PageStyle nextOffsetOrHasMore() {
        return (params, body, items) -> {
            JsonNode nxt = body.get("nextOffset");
            if (nxt != null && !nxt.isNull()) {
                return with(params, "offset", scalar(nxt));
            }
            JsonNode more = body.get("hasMore");
            if (more != null && more.isBoolean() && more.asBoolean() && !items.isEmpty()) {
                return with(params, "offset", offsetOf(params) + items.size());
            }
            return null;
        };
    }

    /**
     * Cursor paging for a long text: stops when {@code hasMore} is false or {@code pageEnd} reaches
     * {@code totalChars}. Later pages are addressed by the cursor alone, so {@code startChar} is dropped.
     */
    public static PageStyle bodyCursor() {
        return (params, body, items) -> {
            JsonNode nxt = body.get("nextCursor");
            JsonNode more = body.get("hasMore");
            if (nxt == null || nxt.isNull() || nxt.asText().isEmpty() || (more != null && more.isBoolean() && !more.asBoolean())) {
                return null;
            }
            JsonNode end = body.get("pageEnd");
            JsonNode total = body.get("totalChars");
            if (end != null && total != null && end.isIntegralNumber() && total.isIntegralNumber()
                    && end.asLong() >= total.asLong()) {
                return null;
            }
            Map<String, Object> out = new LinkedHashMap<String, Object>(params);
            out.remove("startChar");
            out.put("cursor", scalar(nxt));
            return out;
        };
    }

    private static long offsetOf(Map<String, Object> params) {
        Object o = params.get("offset");
        return o instanceof Number ? ((Number) o).longValue() : 0L;
    }
}
