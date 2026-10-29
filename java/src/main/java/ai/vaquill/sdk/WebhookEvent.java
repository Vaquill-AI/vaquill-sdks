package ai.vaquill.sdk;

import com.fasterxml.jackson.databind.JsonNode;
import java.util.Collections;
import java.util.Iterator;
import java.util.LinkedHashMap;
import java.util.Map;

/** A verified webhook event envelope. Every other member of the payload is kept in {@link #getFields()}. */
public final class WebhookEvent {
    private final String event;
    private final String firedAt;
    private final Map<String, JsonNode> fields;

    WebhookEvent(JsonNode payload) {
        JsonNode e = payload.get("event");
        JsonNode f = payload.get("firedAt");
        this.event = e != null && e.isTextual() ? e.asText() : null;
        this.firedAt = f != null && f.isTextual() ? f.asText() : null;
        Map<String, JsonNode> all = new LinkedHashMap<String, JsonNode>();
        Iterator<Map.Entry<String, JsonNode>> it = payload.fields();
        while (it.hasNext()) {
            Map.Entry<String, JsonNode> en = it.next();
            all.put(en.getKey(), en.getValue());
        }
        this.fields = Collections.unmodifiableMap(all);
    }

    /** @return the event name, for example {@code corpus.changed} */
    public String getEvent() {
        return event;
    }

    /** @return when the event fired (RFC 3339 text), or null */
    public String getFiredAt() {
        return firedAt;
    }

    /** @return every member of the payload, including {@code event} and {@code firedAt} */
    public Map<String, JsonNode> getFields() {
        return fields;
    }

    @Override
    public String toString() {
        return "WebhookEvent{event=" + event + ", firedAt=" + firedAt + "}";
    }
}
