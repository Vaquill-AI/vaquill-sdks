package ai.vaquill.sdk;

/** The client-side {@code maxCredits} cap was reached; no request was sent. */
public class SpendGuardExceededException extends VaquillException {
    private static final long serialVersionUID = 1L;

    /**
     * Creates the exception.
     *
     * @param message the message
     */
    public SpendGuardExceededException(String message) {
        super(message);
    }

    /**
     * Creates the exception with a cause.
     *
     * @param message the message
     * @param cause the cause
     */
    public SpendGuardExceededException(String message, Throwable cause) {
        super(message, cause);
    }
}
