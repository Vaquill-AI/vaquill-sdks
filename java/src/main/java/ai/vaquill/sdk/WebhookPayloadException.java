package ai.vaquill.sdk;

/** The signature matched but the body is not a Vaquill event. */
public class WebhookPayloadException extends WebhookVerificationException {
    private static final long serialVersionUID = 1L;

    /**
     * Creates the exception.
     *
     * @param message the message
     */
    public WebhookPayloadException(String message) {
        super(message);
    }

    /**
     * Creates the exception with a cause.
     *
     * @param message the message
     * @param cause the cause
     */
    public WebhookPayloadException(String message, Throwable cause) {
        super(message, cause);
    }
}
