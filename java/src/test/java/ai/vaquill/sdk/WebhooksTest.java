package ai.vaquill.sdk;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertThrows;

import java.nio.charset.StandardCharsets;
import java.util.Base64;
import java.util.Collections;
import java.util.HashMap;
import java.util.Map;
import javax.crypto.Mac;
import javax.crypto.spec.SecretKeySpec;
import org.junit.jupiter.api.Test;

class WebhooksTest {
    private static final byte[] RAW = "whsec-test-secret-bytes-0123456789".getBytes(StandardCharsets.UTF_8);
    private static final String SECRET = "whsec_" + Base64.getEncoder().encodeToString(RAW);
    private static final String BODY = "{\"event\":\"corpus.changed\",\"firedAt\":\"2026-01-01T00:00:00Z\",\"id\":\"evt_1\"}";

    private static String sign(byte[] key, String id, long ts, String body) throws Exception {
        Mac mac = Mac.getInstance("HmacSHA256");
        mac.init(new SecretKeySpec(key, "HmacSHA256"));
        byte[] out = mac.doFinal((id + "." + ts + "." + body).getBytes(StandardCharsets.UTF_8));
        return "v1," + Base64.getEncoder().encodeToString(out);
    }

    private static Map<String, String> headers(String id, long ts, String sig) {
        Map<String, String> h = new HashMap<>();
        h.put("Webhook-Id", id);
        h.put("webhook-timestamp", Long.toString(ts));
        h.put("WEBHOOK-SIGNATURE", sig);
        return h;
    }

    private static long now() {
        return System.currentTimeMillis() / 1000;
    }

    @Test
    void validSignatureVerifiesAndUnwraps() throws Exception {
        long ts = now();
        Map<String, String> h = headers("msg_1", ts, sign(RAW, "msg_1", ts, BODY));
        Webhooks.verify(BODY, h, SECRET);
        WebhookEvent e = Webhooks.unwrap(BODY, h, SECRET);
        assertNotNull(e);
        assertEquals("corpus.changed", e.getEvent());
        assertEquals("2026-01-01T00:00:00Z", e.getFiredAt());
        assertEquals("evt_1", e.getFields().get("id").asText());
        assertNotNull(e.toString());
    }

    @Test
    void listValuedHeadersAreAccepted() throws Exception {
        long ts = now();
        Map<String, java.util.List<String>> h = new HashMap<>();
        h.put("webhook-id", Collections.singletonList("msg_2"));
        h.put("webhook-timestamp", Collections.singletonList(Long.toString(ts)));
        h.put("webhook-signature", Collections.singletonList(sign(RAW, "msg_2", ts, BODY)));
        Webhooks.verify(BODY.getBytes(StandardCharsets.UTF_8), h, Collections.singletonList(SECRET), 300, false, null);
    }

    @Test
    void tamperedBodyAndBadSignatureAreRejected() throws Exception {
        long ts = now();
        Map<String, String> h = headers("msg_1", ts, sign(RAW, "msg_1", ts, BODY));
        assertThrows(WebhookVerificationException.class, () -> Webhooks.verify(BODY + " ", h, SECRET));
        Map<String, String> bad = headers("msg_1", ts, "v1,AAAA");
        assertThrows(WebhookVerificationException.class, () -> Webhooks.verify(BODY, bad, SECRET));
        Map<String, String> junk = headers("msg_1", ts, "garbage");
        assertThrows(WebhookVerificationException.class, () -> Webhooks.verify(BODY, junk, SECRET));
    }

    @Test
    void toleranceAppliesInBothDirections() throws Exception {
        long old = now() - 3600;
        assertThrows(WebhookVerificationException.class,
                () -> Webhooks.verify(BODY, headers("m", old, sign(RAW, "m", old, BODY)), SECRET));
        long future = now() + 3600;
        assertThrows(WebhookVerificationException.class,
                () -> Webhooks.verify(BODY, headers("m", future, sign(RAW, "m", future, BODY)), SECRET));
        Webhooks.verify(BODY.getBytes(StandardCharsets.UTF_8), headers("m", old, sign(RAW, "m", old, BODY)), Collections.singletonList(SECRET), 7200, false, null);
    }

    @Test
    void missingOrInvalidHeadersAreRejected() throws Exception {
        long ts = now();
        Map<String, String> h = headers("msg_1", ts, sign(RAW, "msg_1", ts, BODY));
        for (String name : new String[] {"Webhook-Id", "webhook-timestamp", "WEBHOOK-SIGNATURE"}) {
            Map<String, String> copy = new HashMap<>(h);
            copy.remove(name);
            assertThrows(WebhookVerificationException.class, () -> Webhooks.verify(BODY, copy, SECRET), name);
        }
        Map<String, String> nan = new HashMap<>(h);
        nan.put("webhook-timestamp", "not-a-number");
        assertThrows(WebhookVerificationException.class, () -> Webhooks.verify(BODY, nan, SECRET));
    }

    @Test
    void rotationAcceptsEitherSecretAndMultipleSignatures() throws Exception {
        byte[] other = "another-secret-key-material-xyz".getBytes(StandardCharsets.UTF_8);
        String otherSecret = "whsec_" + Base64.getEncoder().encodeToString(other);
        long ts = now();
        String sigs = sign(other, "m", ts, BODY) + " " + sign(RAW, "m", ts, BODY);
        Webhooks.verify(BODY, headers("m", ts, sigs), SECRET);
        Webhooks.verify(BODY, headers("m", ts, sigs), otherSecret);
        Webhooks.verify(BODY.getBytes(StandardCharsets.UTF_8), headers("m", ts, sign(other, "m", ts, BODY)), java.util.Arrays.asList(SECRET, otherSecret), 300, false, null);
        assertThrows(WebhookVerificationException.class,
                () -> Webhooks.verify(BODY, headers("m", ts, sign(other, "m", ts, BODY)), SECRET));
    }

    @Test
    void emptyAndMalformedSecretsAreProgrammerErrors() throws Exception {
        long ts = now();
        Map<String, String> h = headers("m", ts, sign(RAW, "m", ts, BODY));
        assertThrows(IllegalArgumentException.class, () -> Webhooks.verify(BODY, h, ""));
        assertThrows(IllegalArgumentException.class, () -> Webhooks.verify(BODY, h, "   "));
        assertThrows(IllegalArgumentException.class, () -> Webhooks.verify(BODY, h, "whsec_"));
        assertThrows(IllegalArgumentException.class, () -> Webhooks.verify(BODY, h, "whsec_!!!not base64!!!"));
        assertThrows(IllegalArgumentException.class, () -> Webhooks.verify(BODY.getBytes(StandardCharsets.UTF_8), h, Collections.<String>emptyList(), 300, false, null));
    }

    @Test
    void invalidBase64AfterWhsecThrowsWithAClearMessageThatDoesNotEchoTheSecret() throws Exception {
        long ts = now();
        Map<String, String> h = headers("m", ts, sign(RAW, "m", ts, BODY));
        String bad = "whsec_!!!not base64!!!";
        IllegalArgumentException e = assertThrows(IllegalArgumentException.class, () -> Webhooks.verify(BODY, h, bad));
        assertEquals("The webhook secret has an invalid base64 key after 'whsec_'.", e.getMessage());
        assertEquals(false, e.getMessage().contains("not base64"));
    }

    @Test
    void plainStringSecretIsUsedAsRawBytes() throws Exception {
        long ts = now();
        Webhooks.verify(BODY, headers("m", ts, sign("plain-secret".getBytes(StandardCharsets.UTF_8), "m", ts, BODY)), "plain-secret");
    }

    @Test
    void legacySignatureNeedsOptIn() throws Exception {
        Mac mac = Mac.getInstance("HmacSHA256");
        mac.init(new SecretKeySpec("plain".getBytes(StandardCharsets.UTF_8), "HmacSHA256"));
        StringBuilder hex = new StringBuilder("sha256=");
        for (byte b : mac.doFinal(BODY.getBytes(StandardCharsets.UTF_8))) {
            hex.append(String.format("%02x", b));
        }
        Map<String, String> h = new HashMap<>();
        h.put("X-Vaquill-Signature", hex.toString());
        byte[] body = BODY.getBytes(StandardCharsets.UTF_8);
        assertThrows(WebhookVerificationException.class, () -> Webhooks.verify(BODY, h, "plain"));
        Webhooks.verify(body, h, Collections.singletonList("plain"), 300, true, null);
        assertEquals("corpus.changed", Webhooks.unwrap(body, h, Collections.singletonList("plain"), 300, true, null).getEvent());
        h.put("X-Vaquill-Signature", "sha256=00");
        assertThrows(WebhookVerificationException.class, () -> Webhooks.verify(body, h, Collections.singletonList("plain"), 300, true, null));
    }

    @Test
    void unwrapRejectsNonJsonPayloads() throws Exception {
        long ts = now();
        String text = "not json";
        Map<String, String> h = headers("m", ts, sign(RAW, "m", ts, text));
        assertThrows(WebhookPayloadException.class, () -> Webhooks.unwrap(text, h, SECRET));
        String noEvent = "{\"a\":1}";
        Map<String, String> h2 = headers("m", ts, sign(RAW, "m", ts, noEvent));
        assertThrows(WebhookPayloadException.class, () -> Webhooks.unwrap(noEvent, h2, SECRET));
    }
}
