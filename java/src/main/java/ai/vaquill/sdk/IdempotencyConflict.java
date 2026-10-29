package ai.vaquill.sdk;

/**
 * Marker interface implemented by the three idempotency exceptions. Java has single inheritance, so
 * use {@code instanceof IdempotencyConflict} to test for any of them.
 */
public interface IdempotencyConflict {}
