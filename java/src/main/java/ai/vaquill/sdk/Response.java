package ai.vaquill.sdk;

import com.fasterxml.jackson.databind.JsonNode;
import java.util.Collections;
import java.util.List;
import java.util.Map;
import java.util.TreeMap;

/**
 * A parsed result together with the HTTP metadata: status, headers, request id and credits.
 * Returned by the {@code ...WithResponse} methods.
 *
 * @param <T> the parsed body type
 */
public final class Response<T> {
    private final T data;
    private final int statusCode;
    private final Map<String, List<String>> headers;
    private final JsonNode json;

    /**
     * Creates a response. Used by the transport.
     *
     * @param data the parsed body, or null (for example a 204)
     * @param statusCode the HTTP status
     * @param headers the response headers
     * @param json the body as a tree, or null when empty
     */
    public Response(T data, int statusCode, Map<String, List<String>> headers, JsonNode json) {
        this.data = data;
        this.statusCode = statusCode;
        TreeMap<String, List<String>> ci = new TreeMap<String, List<String>>(String.CASE_INSENSITIVE_ORDER);
        if (headers != null) {
            for (Map.Entry<String, List<String>> e : headers.entrySet()) {
                if (e.getKey() != null) {
                    ci.put(e.getKey(), Collections.unmodifiableList(e.getValue()));
                }
            }
        }
        this.headers = Collections.unmodifiableMap(ci);
        this.json = json;
    }

    /** @return the parsed body, or null for an empty one */
    public T getData() {
        return data;
    }

    /** @return the HTTP status code */
    public int getStatusCode() {
        return statusCode;
    }

    /** @return the response headers; lookups are case-insensitive */
    public Map<String, List<String>> getHeaders() {
        return headers;
    }

    /**
     * One header value.
     *
     * @param name the header name, any case
     * @return the first value, or null
     */
    public String getHeader(String name) {
        List<String> v = headers.get(name);
        return v == null || v.isEmpty() ? null : v.get(0);
    }

    /** @return the {@code X-Request-ID} header, or null */
    public String getRequestId() {
        return getHeader("X-Request-ID");
    }

    /** @return the parsed {@code X-RateLimit-*} headers */
    public RateLimit getRateLimit() {
        return RateLimit.fromHeaders(headers);
    }

    /** @return true when the server replayed a stored response for the idempotency key (no new charge) */
    public boolean isIdempotentReplayed() {
        return "true".equalsIgnoreCase(getHeader("Idempotent-Replayed"));
    }

    /**
     * The credits the response reports: {@code creditsConsumed} from the body, else the one in the
     * {@code meta} block of an envelope. On a replay this is the stored figure.
     *
     * @return the figure, or null when the body has none
     */
    public Double getCreditsConsumed() {
        if (json == null || !json.isObject()) {
            return null;
        }
        JsonNode n = json.get("creditsConsumed");
        if (n == null || !n.isNumber()) {
            JsonNode meta = json.get("meta");
            n = meta == null || !meta.isObject() ? null : meta.get("creditsConsumed");
        }
        return n != null && n.isNumber() ? Double.valueOf(n.asDouble()) : null;
    }

    /** @return zero on an idempotent replay, otherwise {@link #getCreditsConsumed()} (0 when absent) */
    public double getCreditsChargedThisCall() {
        if (isIdempotentReplayed()) {
            return 0.0;
        }
        Double c = getCreditsConsumed();
        return c == null ? 0.0 : c;
    }

    /** @return the raw JSON body, or null when the body was empty */
    public JsonNode getJson() {
        return json;
    }

    @Override
    public String toString() {
        return "Response{status=" + statusCode + ", requestId=" + getRequestId() + ", creditsConsumed="
                + getCreditsConsumed() + "}";
    }
}
