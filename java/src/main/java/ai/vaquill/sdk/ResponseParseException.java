package ai.vaquill.sdk;

/** A 2xx response could not be parsed into the expected model (malformed JSON or wrong shape). */
public class ResponseParseException extends VaquillException {
    private static final long serialVersionUID = 1L;
    private final String requestId;
    private final int statusCode;

    /**
     * Creates the exception.
     *
     * @param message the message
     * @param requestId the {@code X-Request-ID} of the response, or null
     * @param statusCode the HTTP status of the response
     * @param cause the parse failure, or null
     */
    public ResponseParseException(String message, String requestId, int statusCode, Throwable cause) {
        super(message, cause);
        this.requestId = requestId;
        this.statusCode = statusCode;
    }

    /** @return the request id, or null */
    public String getRequestId() {
        return requestId;
    }

    /** @return the HTTP status code */
    public int getStatusCode() {
        return statusCode;
    }

    @Override
    public String toString() {
        return getClass().getName() + ": " + getMessage() + " (status=" + statusCode + ", request_id=" + requestId + ")";
    }
}
