package ai.vaquill.sdk;

import ai.vaquill.sdk.internal.Json;
import com.fasterxml.jackson.databind.JsonNode;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.security.GeneralSecurityException;
import java.security.MessageDigest;
import java.time.Instant;
import java.util.ArrayList;
import java.util.Base64;
import java.util.Collection;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import javax.crypto.Mac;
import javax.crypto.spec.SecretKeySpec;

/**
 * Webhook signature verification (Standard Webhooks). Pass the RAW request body, never re-serialised
 * JSON.
 *
 * <pre>{@code
 * WebhookEvent event = Webhooks.unwrap(rawBody, headers, System.getenv("VAQUILL_WEBHOOK_SECRET"));
 * }</pre>
 */
public final class Webhooks {
    /** Default clock tolerance in seconds either side of now. */
    public static final long DEFAULT_TOLERANCE_SECONDS = 300;
    private static final String SECRET_PREFIX = "whsec_";

    private Webhooks() {}

    /**
     * Verifies a delivery signed with Standard Webhooks headers, 300 second tolerance.
     *
     * @param payload the raw body
     * @param headers the request headers (a value may be a String or a collection of Strings)
     * @param secret the signing secret ({@code whsec_...} base64 form, or a plain string)
     * @throws WebhookVerificationException when the headers, timestamp or signature do not check out
     * @throws IllegalArgumentException when the secret is empty or blank, or {@code whsec_} is followed by invalid base64
     */
    public static void verify(String payload, Map<String, ?> headers, String secret) {
        verify(payload.getBytes(StandardCharsets.UTF_8), headers, java.util.Collections.singletonList(secret),
                DEFAULT_TOLERANCE_SECONDS, false, null);
    }

    /**
     * Verifies a delivery, accepting any of several secrets (rotation).
     *
     * @param payload the raw body bytes
     * @param headers the request headers
     * @param secrets one or more signing secrets; a delivery signed by any of them verifies
     * @param toleranceSeconds clock tolerance either side of {@code now}
     * @param allowLegacy accept the legacy {@code X-Vaquill-Signature: sha256=...} scheme. WARNING: it
     *     signs only the body, so it has NO replay protection
     * @param now the clock to compare with, or null for the current time
     * @throws WebhookVerificationException when verification fails
     * @throws IllegalArgumentException for an empty secret or invalid base64
     */
    public static void verify(byte[] payload, Map<String, ?> headers, List<String> secrets, long toleranceSeconds,
            boolean allowLegacy, Instant now) {
        requireSecrets(secrets);
        Map<String, String> h = lower(headers);
        String id = h.get("webhook-id");
        String stamp = h.get("webhook-timestamp");
        String sig = h.get("webhook-signature");
        List<String> given = new ArrayList<String>();
        List<String> expected = new ArrayList<String>();
        if (notEmpty(id) && notEmpty(stamp) && notEmpty(sig)) {
            long ts;
            try {
                ts = Long.parseLong(stamp.trim());
            } catch (NumberFormatException e) {
                throw new WebhookVerificationException("Invalid webhook-timestamp.");
            }
            double nowSeconds = (now == null ? Instant.now() : now).toEpochMilli() / 1000.0;
            if (Math.abs(nowSeconds - ts) > toleranceSeconds) {
                throw new WebhookVerificationException("Webhook timestamp is outside the tolerance window.");
            }
            byte[] head = (id + "." + ts + ".").getBytes(StandardCharsets.UTF_8);
            byte[] signed = new byte[head.length + payload.length];
            System.arraycopy(head, 0, signed, 0, head.length);
            System.arraycopy(payload, 0, signed, head.length, payload.length);
            for (String s : secrets) {
                expected.add(Base64.getEncoder().encodeToString(hmac(key(s), signed)));
            }
            for (String part : sig.trim().split("\\s+")) {
                if (part.startsWith("v1,")) {
                    given.add(part.substring(3));
                }
            }
        } else {
            String legacy = h.get("x-vaquill-signature");
            if (!allowLegacy || !notEmpty(legacy)) {
                throw new WebhookVerificationException("Missing webhook signature headers.");
            }
            given.add(legacy);
            for (String s : secrets) {
                expected.add("sha256=" + hex(hmac(s.getBytes(StandardCharsets.UTF_8), payload)));
            }
        }
        if (!anyMatch(given, expected)) {
            throw new WebhookVerificationException("No matching signature.");
        }
    }

    /**
     * Verifies a delivery and returns its parsed event.
     *
     * @param payload the raw body
     * @param headers the request headers
     * @param secret the signing secret
     * @return the event
     * @throws WebhookVerificationException when verification fails
     * @throws WebhookPayloadException when the signature is valid but the body is not an event
     */
    public static WebhookEvent unwrap(String payload, Map<String, ?> headers, String secret) {
        return unwrap(payload.getBytes(StandardCharsets.UTF_8), headers, java.util.Collections.singletonList(secret),
                DEFAULT_TOLERANCE_SECONDS, false, null);
    }

    /**
     * Verifies a delivery against one or more secrets and returns its parsed event.
     *
     * @param payload the raw body bytes
     * @param headers the request headers
     * @param secrets the signing secrets
     * @param toleranceSeconds clock tolerance
     * @param allowLegacy accept the replayable legacy scheme
     * @param now the clock, or null
     * @return the event
     */
    public static WebhookEvent unwrap(byte[] payload, Map<String, ?> headers, List<String> secrets,
            long toleranceSeconds, boolean allowLegacy, Instant now) {
        verify(payload, headers, secrets, toleranceSeconds, allowLegacy, now);
        try {
            JsonNode node = Json.parse(payload);
            if (node == null || !node.isObject() || !node.hasNonNull("event")) {
                throw new WebhookPayloadException("Payload is not a valid event.");
            }
            return new WebhookEvent(node);
        } catch (IOException e) {
            throw new WebhookPayloadException("Payload is not a valid event.", e);
        }
    }

    // ---------------------------------------------------------------- helpers

    private static void requireSecrets(List<String> secrets) {
        if (secrets == null || secrets.isEmpty()) {
            throw new IllegalArgumentException("A webhook secret is required.");
        }
        for (String s : secrets) {
            // An unset environment variable must never verify a forged event.
            if (s == null || s.trim().isEmpty() || s.trim().equals(SECRET_PREFIX)) {
                throw new IllegalArgumentException("The webhook secret is empty or blank.");
            }
        }
    }

    private static byte[] key(String secret) {
        if (secret.startsWith(SECRET_PREFIX)) {
            String b64 = secret.substring(SECRET_PREFIX.length());
            try {
                return Base64.getDecoder().decode(b64);
            } catch (IllegalArgumentException e) {
                throw new IllegalArgumentException("The webhook secret has an invalid base64 key after 'whsec_'.");
            }
        }
        return secret.getBytes(StandardCharsets.UTF_8);
    }

    private static byte[] hmac(byte[] key, byte[] data) {
        try {
            Mac mac = Mac.getInstance("HmacSHA256");
            mac.init(new SecretKeySpec(key.length == 0 ? new byte[1] : key, "HmacSHA256"));
            return mac.doFinal(data);
        } catch (GeneralSecurityException e) {
            throw new VaquillException("HmacSHA256 is unavailable.", e);
        }
    }

    private static boolean anyMatch(List<String> given, List<String> expected) {
        // No early exit: every comparison runs so timing does not reveal which one matched.
        boolean matched = false;
        for (String g : given) {
            for (String w : expected) {
                matched |= MessageDigest.isEqual(g.getBytes(StandardCharsets.UTF_8), w.getBytes(StandardCharsets.UTF_8));
            }
        }
        return matched;
    }

    private static String hex(byte[] bytes) {
        StringBuilder sb = new StringBuilder();
        for (byte b : bytes) {
            sb.append(String.format(Locale.ROOT, "%02x", b & 0xff));
        }
        return sb.toString();
    }

    private static boolean notEmpty(String s) {
        return s != null && !s.isEmpty();
    }

    private static Map<String, String> lower(Map<String, ?> headers) {
        Map<String, String> out = new java.util.HashMap<String, String>();
        for (Map.Entry<String, ?> e : headers.entrySet()) {
            Object v = e.getValue();
            String value = null;
            if (v instanceof String) {
                value = (String) v;
            } else if (v instanceof Collection && !((Collection<?>) v).isEmpty()) {
                Object first = ((Collection<?>) v).iterator().next();
                value = first == null ? null : first.toString();
            }
            if (e.getKey() != null && value != null) {
                out.put(e.getKey().toLowerCase(Locale.ROOT), value);
            }
        }
        return out;
    }
}
