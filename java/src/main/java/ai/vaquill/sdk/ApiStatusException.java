package ai.vaquill.sdk;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.Map;

/**
 * The server answered with a 4xx or 5xx status.
 *
 * <p>Branch on {@link #getCode()} when present and fall back to the status class. The code set is
 * open: an unknown code still produces the status-mapped class.
 */
public class ApiStatusException extends VaquillException {
    private static final long serialVersionUID = 1L;

    private final int statusCode;
    private final transient Map<String, List<String>> headers;
    private final transient Object body;
    private final String requestId;
    private final String code;
    private final Boolean retryable;
    private final Double retryAfterSeconds;
    private final transient Object detail;
    private final transient List<Object> errors;

    /**
     * Creates the exception, reading the error envelope out of {@code body}.
     *
     * @param message the human readable message
     * @param statusCode the HTTP status
     * @param headers the response headers
     * @param body the parsed JSON body (a Map), or the raw text when it was not JSON
     */
    public ApiStatusException(String message, int statusCode, Map<String, List<String>> headers, Object body) {
        super(message);
        this.statusCode = statusCode;
        this.headers = headers == null ? Collections.<String, List<String>>emptyMap() : headers;
        this.body = body;
        Map<?, ?> env = body instanceof Map ? (Map<?, ?>) body : Collections.emptyMap();
        this.requestId = firstNonEmpty(str(env.get("requestId")), header(this.headers, "x-request-id"));
        this.code = str(env.get("code"));
        Object r = env.get("retryable");
        this.retryable = r instanceof Boolean ? (Boolean) r : null;
        Object a = env.get("retryAfterSeconds");
        this.retryAfterSeconds = a instanceof Number ? Double.valueOf(((Number) a).doubleValue()) : null;
        this.detail = env.get("detail");
        Object e = env.get("errors");
        List<Object> list = null;
        if (e instanceof List) {
            list = Collections.unmodifiableList(new ArrayList<Object>((List<?>) e));
        }
        this.errors = list;
    }

    private static String str(Object v) {
        return v instanceof String && !((String) v).isEmpty() ? (String) v : null;
    }

    private static String firstNonEmpty(String a, String b) {
        return a != null ? a : b;
    }

    private static String header(Map<String, List<String>> h, String name) {
        for (Map.Entry<String, List<String>> en : h.entrySet()) {
            if (en.getKey() != null && en.getKey().equalsIgnoreCase(name) && !en.getValue().isEmpty()) {
                return en.getValue().get(0);
            }
        }
        return null;
    }

    /** @return the HTTP status code */
    public int getStatusCode() {
        return statusCode;
    }

    /** @return the response headers (case-insensitive lookup via {@link #getHeader(String)}) */
    public Map<String, List<String>> getHeaders() {
        return headers;
    }

    /**
     * Looks a response header up by case-insensitive name.
     *
     * @param name the header name
     * @return the first value, or null
     */
    public String getHeader(String name) {
        return header(headers, name);
    }

    /** @return the parsed body: a Map for a JSON object, otherwise the raw text */
    public Object getBody() {
        return body;
    }

    /** @return the request id from the envelope, else the {@code X-Request-ID} header, else null */
    public String getRequestId() {
        return requestId;
    }

    /** @return the machine readable error code (for example {@code insufficient_credits}), or null */
    public String getCode() {
        return code;
    }

    /** @return the server's retry verdict, or null when it gave none */
    public Boolean getRetryable() {
        return retryable;
    }

    /** @return the server's suggested wait in seconds, or null */
    public Double getRetryAfterSeconds() {
        return retryAfterSeconds;
    }

    /** @return the legacy {@code detail} member of the envelope, or null */
    public Object getDetail() {
        return detail;
    }

    /** @return the validation {@code errors} list of a 422, or null */
    public List<Object> getErrors() {
        return errors;
    }

    @Override
    public String toString() {
        return getClass().getName() + ": " + getMessage() + " (status=" + statusCode + ", request_id=" + requestId + ")";
    }
}
