package ai.vaquill.sdk;

import java.time.Duration;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.Map;

/** Per-call overrides accepted by every operation. Immutable; build with {@link #builder()}. */
public final class RequestOptions {
    private static final RequestOptions EMPTY = new Builder().build();

    private final Duration timeout;
    private final Integer maxRetries;
    private final String idempotencyKey;
    private final Map<String, String> headers;

    private RequestOptions(Builder b) {
        this.timeout = b.timeout;
        this.maxRetries = b.maxRetries;
        this.idempotencyKey = b.idempotencyKey;
        this.headers = Collections.unmodifiableMap(new LinkedHashMap<String, String>(b.headers));
    }

    /** @return options that change nothing */
    public static RequestOptions none() {
        return EMPTY;
    }

    /** @return a new builder */
    public static Builder builder() {
        return new Builder();
    }

    /**
     * A copy with a different idempotency key (used by the chunking helpers).
     *
     * @param key the key, or null for none
     * @return the copy
     */
    public RequestOptions withIdempotencyKey(String key) {
        Builder b = new Builder();
        b.timeout = timeout;
        b.maxRetries = maxRetries;
        b.idempotencyKey = key;
        b.headers.putAll(headers);
        return b.build();
    }

    /** @return the per-call timeout ({@link Duration#ZERO} disables it), or null to use the client's */
    public Duration getTimeout() {
        return timeout;
    }

    /** @return the per-call retry count, or null to use the client's */
    public Integer getMaxRetries() {
        return maxRetries;
    }

    /** @return the caller supplied idempotency key, or null */
    public String getIdempotencyKey() {
        return idempotencyKey;
    }

    /** @return extra headers for this call */
    public Map<String, String> getHeaders() {
        return headers;
    }

    /** Builder for {@link RequestOptions}. */
    public static final class Builder {
        private Duration timeout;
        private Integer maxRetries;
        private String idempotencyKey;
        private final Map<String, String> headers = new LinkedHashMap<String, String>();

        private Builder() {}

        /**
         * Overrides the timeout for this call.
         *
         * @param timeout the timeout; zero disables it
         * @return this
         */
        public Builder timeout(Duration timeout) {
            if (timeout != null && timeout.isNegative()) {
                throw new IllegalArgumentException("timeout must not be negative.");
            }
            this.timeout = timeout;
            return this;
        }

        /**
         * Overrides the retry count for this call.
         *
         * @param maxRetries retries after the first attempt, at least 0
         * @return this
         */
        public Builder maxRetries(int maxRetries) {
            if (maxRetries < 0) {
                throw new IllegalArgumentException("maxRetries must be >= 0.");
            }
            this.maxRetries = maxRetries;
            return this;
        }

        /**
         * Sets the idempotency key (16 to 255 visible ASCII characters). Charged calls get a random
         * one automatically; set it to make a retry of your own safe.
         *
         * @param key the key
         * @return this
         */
        public Builder idempotencyKey(String key) {
            this.idempotencyKey = ai.vaquill.sdk.internal.IdempotencyKeys.validate(key);
            return this;
        }

        /**
         * Adds a header for this call. {@code Authorization} and {@code Idempotency-Key} cannot be overridden.
         *
         * @param name the name
         * @param value the value
         * @return this
         */
        public Builder header(String name, String value) {
            if (name == null || name.isEmpty() || value == null) {
                throw new IllegalArgumentException("Header name and value are required.");
            }
            this.headers.put(name, value);
            return this;
        }

        /**
         * Builds the options.
         *
         * @return the options
         */
        public RequestOptions build() {
            return new RequestOptions(this);
        }
    }
}
