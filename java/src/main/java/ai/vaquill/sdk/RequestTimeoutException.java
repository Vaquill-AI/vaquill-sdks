package ai.vaquill.sdk;

/** The request timed out. */
public class RequestTimeoutException extends ConnectionException {
    private static final long serialVersionUID = 1L;

    /**
     * Creates the exception.
     *
     * @param message the message
     */
    public RequestTimeoutException(String message) {
        super(message);
    }

    /**
     * Creates the exception with a cause.
     *
     * @param message the message
     * @param cause the cause
     */
    public RequestTimeoutException(String message, Throwable cause) {
        super(message, cause);
    }
}
