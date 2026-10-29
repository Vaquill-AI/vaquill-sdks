package ai.vaquill.sdk;

/** A webhook delivery failed signature or timestamp verification. */
public class WebhookVerificationException extends VaquillException {
    private static final long serialVersionUID = 1L;

    /**
     * Creates the exception.
     *
     * @param message the message
     */
    public WebhookVerificationException(String message) {
        super(message);
    }

    /**
     * Creates the exception with a cause.
     *
     * @param message the message
     * @param cause the cause
     */
    public WebhookVerificationException(String message, Throwable cause) {
        super(message, cause);
    }
}
