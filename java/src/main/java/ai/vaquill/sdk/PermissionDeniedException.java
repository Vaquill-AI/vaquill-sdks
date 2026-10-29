package ai.vaquill.sdk;

import java.util.List;
import java.util.Map;

/** HTTP 403. */
public class PermissionDeniedException extends ApiStatusException {
    private static final long serialVersionUID = 1L;

    /**
     * Creates the exception.
     *
     * @param message the message
     * @param statusCode the HTTP status
     * @param headers the response headers
     * @param body the parsed body
     */
    public PermissionDeniedException(String message, int statusCode, Map<String, List<String>> headers, Object body) {
        super(message, statusCode, headers, body);
    }
}
