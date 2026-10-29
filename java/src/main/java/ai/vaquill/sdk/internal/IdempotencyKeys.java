package ai.vaquill.sdk.internal;

import java.util.UUID;

/** Idempotency key helpers. Internal. */
public final class IdempotencyKeys {
    private IdempotencyKeys() {}

    /** @return a fresh UUIDv4 */
    public static String newKey() {
        return UUID.randomUUID().toString();
    }

    /**
     * The server accepts 16 to 255 visible ASCII characters.
     *
     * @param key the key
     * @return the same key
     * @throws IllegalArgumentException when it is empty, too short or long, or not visible ASCII
     */
    public static String validate(String key) {
        if (key == null || key.length() < 16 || key.length() > 255) {
            throw new IllegalArgumentException("idempotencyKey must be 16 to 255 visible ASCII characters.");
        }
        for (int i = 0; i < key.length(); i++) {
            char c = key.charAt(i);
            if (c < 33 || c > 126) {
                throw new IllegalArgumentException("idempotencyKey must be 16 to 255 visible ASCII characters.");
            }
        }
        return key;
    }

    /**
     * Keys are logged by their first 8 characters only.
     *
     * @param key the key
     * @return the redacted form
     */
    public static String redact(String key) {
        return key.substring(0, Math.min(8, key.length())) + "...";
    }

    /**
     * A caller's key for chunk {@code index}: unchanged for the first, suffixed for later ones, because
     * every chunk has a different body and reusing one key would be rejected as a key reuse.
     *
     * @param key the caller's key, or null
     * @param index the chunk number from 0
     * @return the key to send, or null
     */
    public static String forChunk(String key, int index) {
        if (key == null || index == 0) {
            return key;
        }
        String suffix = "-" + index;
        String base = key.length() + suffix.length() > 255 ? key.substring(0, 255 - suffix.length()) : key;
        return base + suffix;
    }
}
