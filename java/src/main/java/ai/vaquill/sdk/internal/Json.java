package ai.vaquill.sdk.internal;

import com.fasterxml.jackson.annotation.JsonAutoDetect.Visibility;
import com.fasterxml.jackson.annotation.JsonInclude;
import com.fasterxml.jackson.annotation.PropertyAccessor;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.DeserializationFeature;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.SerializationFeature;
import java.io.IOException;

/** Shared Jackson configuration. Internal: not part of the public API. */
public final class Json {
    /** The shared mapper. Only fields annotated with {@code @JsonProperty} are (de)serialised. */
    public static final ObjectMapper MAPPER = build();

    private Json() {}

    private static ObjectMapper build() {
        ObjectMapper m = new ObjectMapper();
        m.setVisibility(PropertyAccessor.ALL, Visibility.NONE);
        m.setSerializationInclusion(JsonInclude.Include.NON_NULL);
        m.configure(DeserializationFeature.FAIL_ON_UNKNOWN_PROPERTIES, false);
        m.configure(DeserializationFeature.ACCEPT_SINGLE_VALUE_AS_ARRAY, false);
        m.configure(SerializationFeature.FAIL_ON_EMPTY_BEANS, false);
        return m;
    }

    /**
     * Serialises a value to UTF-8 JSON bytes.
     *
     * @param value the value
     * @return the bytes
     */
    public static byte[] toBytes(Object value) {
        try {
            return MAPPER.writeValueAsBytes(value);
        } catch (JsonProcessingException e) {
            throw new IllegalArgumentException("Cannot serialise request body: " + e.getOriginalMessage(), e);
        }
    }

    /**
     * Converts any value to a tree.
     *
     * @param value the value
     * @return the tree
     */
    public static JsonNode tree(Object value) {
        return MAPPER.valueToTree(value);
    }

    /**
     * Parses text into a tree.
     *
     * @param text the JSON text
     * @return the tree
     * @throws IOException when the text is not JSON
     */
    public static JsonNode parse(byte[] text) throws IOException {
        return MAPPER.readTree(text);
    }

    /**
     * Converts a tree into a model.
     *
     * @param <T> the model type
     * @param node the tree
     * @param type the model class
     * @return the model
     * @throws JsonProcessingException when the shape does not match
     */
    public static <T> T treeToValue(JsonNode node, Class<T> type) throws JsonProcessingException {
        return MAPPER.treeToValue(node, type);
    }
}
