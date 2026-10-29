package ai.vaquill.sdk;

/** Base class of every exception thrown by this SDK. Unchecked. */
public class VaquillException extends RuntimeException {
    private static final long serialVersionUID = 1L;

    /**
     * Creates the exception.
     *
     * @param message the message
     */
    public VaquillException(String message) {
        super(message);
    }

    /**
     * Creates the exception with a cause.
     *
     * @param message the message
     * @param cause the cause
     */
    public VaquillException(String message, Throwable cause) {
        super(message, cause);
    }
}
