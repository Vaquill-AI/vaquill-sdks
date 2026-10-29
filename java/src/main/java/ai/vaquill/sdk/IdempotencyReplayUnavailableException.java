package ai.vaquill.sdk;

import java.util.List;
import java.util.Map;

/** The original completed but its response is too large to replay. The call was not charged again; check the credit balance before retrying. */
public class IdempotencyReplayUnavailableException extends ConflictException implements IdempotencyConflict {
    private static final long serialVersionUID = 1L;

    /**
     * Creates the exception.
     *
     * @param message the message
     * @param statusCode the HTTP status
     * @param headers the response headers
     * @param body the parsed body
     */
    public IdempotencyReplayUnavailableException(String message, int statusCode, Map<String, List<String>> headers, Object body) {
        super(message, statusCode, headers, body);
    }
}
