package ai.vaquill.sdk.models;

import ai.vaquill.sdk.internal.Json;
import com.fasterxml.jackson.annotation.JsonAnyGetter;
import com.fasterxml.jackson.annotation.JsonAnySetter;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.Map;

/**
 * Base of every generated model. Members the server sends that this SDK version does not know about
 * are kept in {@link #getAdditionalProperties()} and written back when the model is serialised, so a
 * newer API never breaks an older SDK. Models compare, hash and print by their JSON form.
 */
public abstract class VaquillModel {
    private transient Map<String, Object> additional;

    /** For subclasses. */
    protected VaquillModel() {}

    @JsonAnySetter
    private void putAdditional(String name, Object value) {
        if (additional == null) {
            additional = new LinkedHashMap<String, Object>();
        }
        additional.put(name, value);
    }

    /** @return members of the payload this SDK version has no field for (never null) */
    @JsonAnyGetter
    public Map<String, Object> getAdditionalProperties() {
        return additional == null ? Collections.<String, Object>emptyMap() : Collections.unmodifiableMap(additional);
    }

    /** @return the model as a JSON string */
    public String toJson() {
        return Json.tree(this).toString();
    }

    @Override
    public String toString() {
        return getClass().getSimpleName() + toJson();
    }

    @Override
    public boolean equals(Object o) {
        return o != null && o.getClass() == getClass() && Json.tree(this).equals(Json.tree(o));
    }

    @Override
    public int hashCode() {
        return Json.tree(this).hashCode();
    }
}
