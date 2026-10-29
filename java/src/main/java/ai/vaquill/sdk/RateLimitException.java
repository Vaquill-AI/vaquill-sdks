package ai.vaquill.sdk;

import java.util.List;
import java.util.Map;

/** HTTP 429. {@link #getRetryAfterSeconds()} is set when the server said how long to wait. */
public class RateLimitException extends ApiStatusException {
    private static final long serialVersionUID = 1L;

    /**
     * Creates the exception.
     *
     * @param message the message
     * @param statusCode the HTTP status
     * @param headers the response headers
     * @param body the parsed body
     */
    public RateLimitException(String message, int statusCode, Map<String, List<String>> headers, Object body) {
        super(message, statusCode, headers, body);
    }
}
