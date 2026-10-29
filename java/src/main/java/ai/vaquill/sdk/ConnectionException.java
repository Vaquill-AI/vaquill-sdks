package ai.vaquill.sdk;

/** The request never produced an HTTP response. */
public class ConnectionException extends VaquillException {
    private static final long serialVersionUID = 1L;

    /**
     * Creates the exception.
     *
     * @param message the message
     */
    public ConnectionException(String message) {
        super(message);
    }

    /**
     * Creates the exception with a cause.
     *
     * @param message the message
     * @param cause the cause
     */
    public ConnectionException(String message, Throwable cause) {
        super(message, cause);
    }
}
