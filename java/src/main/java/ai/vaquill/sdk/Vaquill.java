package ai.vaquill.sdk;

import ai.vaquill.sdk.internal.Transport;
import ai.vaquill.sdk.resources.Boards;
import ai.vaquill.sdk.resources.Credits;
import ai.vaquill.sdk.resources.Pricing;
import ai.vaquill.sdk.resources.SessionLaws;
import ai.vaquill.sdk.resources.Statutes;
import ai.vaquill.sdk.resources.Watches;
import com.fasterxml.jackson.databind.JsonNode;
import java.net.http.HttpClient;
import java.time.Duration;
import java.util.Locale;
import java.util.Map;
import java.util.TreeMap;
import java.util.concurrent.CompletableFuture;
import java.util.function.Function;

/**
 * Client for the Vaquill US Data API. Thread safe: share one instance.
 *
 * <pre>{@code
 * try (Vaquill client = Vaquill.builder().apiKey("vq_key_...").maxCredits(50).build()) {
 *     StatuteSectionResponse s = client.statutes().getSection("USC_T42_C21_S1983");
 * }
 * }</pre>
 *
 * <p>Namespaces: {@link #statutes()}, {@link #sessionLaws()}, {@link #watches()}, {@link #boards()},
 * {@link #credits()} and {@link #pricing()}. Every operation has a blocking form, a
 * {@code ...WithResponse} form that also returns HTTP metadata, and a {@code ...Async} form that
 * returns a {@link CompletableFuture}.
 */
public final class Vaquill implements AutoCloseable {
    /** The default base URL. */
    public static final String DEFAULT_BASE_URL = "https://api.vaquill.ai";
    /** Environment variable holding the API key. */
    public static final String API_KEY_ENV = "VAQUILL_API_KEY";
    /** Environment variable overriding the base URL. */
    public static final String BASE_URL_ENV = "VAQUILL_BASE_URL";
    private static final String API_KEY_PREFIX = "vq_key_";

    private final Transport transport;
    private final Transport.Config config;
    private final String baseUrl;
    private final Statutes statutes;
    private final SessionLaws sessionLaws;
    private final Watches watches;
    private final Boards boards;
    private final Credits credits;
    private final Pricing pricing;

    private Vaquill(Transport.Config config) {
        this.config = config;
        this.baseUrl = config.baseUrl;
        this.transport = new Transport(config);
        this.statutes = new Statutes(transport);
        this.sessionLaws = new SessionLaws(transport);
        this.watches = new Watches(transport);
        this.boards = new Boards(transport);
        this.credits = new Credits(transport);
        this.pricing = new Pricing(transport);
    }

    /** @return a new builder */
    public static Builder builder() {
        return new Builder();
    }

    /**
     * A client configured from the environment only ({@code VAQUILL_API_KEY}, {@code VAQUILL_BASE_URL}).
     *
     * @return the client
     */
    public static Vaquill fromEnv() {
        return builder().build();
    }

    /** @return statutes, regulations and court rules (US primary law) */
    public Statutes statutes() {
        return statutes;
    }

    /** @return US session laws */
    public SessionLaws sessionLaws() {
        return sessionLaws;
    }

    /** @return law-change watches (free) */
    public Watches watches() {
        return watches;
    }

    /** @return the sources a watch can follow (free) */
    public Boards boards() {
        return boards;
    }

    /** @return the credit balance (free) */
    public Credits credits() {
        return credits;
    }

    /** @return the pricing matrix (free) */
    public Pricing pricing() {
        return pricing;
    }

    /** @return the base URL in use, without a trailing slash */
    public String getBaseUrl() {
        return baseUrl;
    }

    /** @return credits consumed by charged calls since construction (shared with derived clients) */
    public double getCreditsSpent() {
        return transport.creditsSpent();
    }

    /**
     * A builder pre-filled with this client's settings. The built client shares this client's HTTP
     * client, async executor and spend total, so {@code maxCredits} caps the combined spend.
     *
     * @return the builder
     */
    public Builder toBuilder() {
        Builder b = new Builder();
        b.apiKey = config.apiKey;
        b.baseUrl = config.baseUrl;
        b.timeout = config.timeout;
        b.maxRetries = config.maxRetries;
        b.defaultHeaders.putAll(config.defaultHeaders);
        b.idempotencyKeys = config.idempotencyKeys;
        b.maxCredits = config.maxCredits;
        b.httpClient = config.http;
        b.logger = config.logger;
        b.sleeper = config.sleeper;
        b.shared = config;
        return b;
    }

    /**
     * Escape hatch for endpoints newer than this SDK. The body comes back as plain JSON.
     *
     * @param method the HTTP method
     * @param path the path starting with {@code /api/v1/...}
     * @param query query parameters in wire names, or null
     * @param body a JSON body (a Map, a model or a JsonNode), or null
     * @param charged true if the endpoint consumes credits: it then gets an idempotency key and is
     *     counted against {@code maxCredits}
     * @param options per-call overrides, or null
     * @return the raw response
     */
    public Response<JsonNode> rawRequest(String method, String path, Map<String, ?> query, Object body,
            boolean charged, RequestOptions options) {
        return transport.execute(
                Transport.Call.of(method, path).query(query).body(body).charged(charged), JsonNode.class, options);
    }

    /**
     * Asynchronous form of {@link #rawRequest}.
     *
     * @param method the HTTP method
     * @param path the path
     * @param query query parameters, or null
     * @param body a JSON body, or null
     * @param charged whether the endpoint consumes credits
     * @param options per-call overrides, or null
     * @return the future raw response
     */
    public CompletableFuture<Response<JsonNode>> rawRequestAsync(String method, String path, Map<String, ?> query,
            Object body, boolean charged, RequestOptions options) {
        return transport.supplyAsync(() -> rawRequest(method, path, query, body, charged, options));
    }

    /** Stops the thread pool behind the {@code ...Async} methods. The JDK HTTP client needs no closing. */
    @Override
    public void close() {
        config.pool.shutdown();
    }

    @Override
    public String toString() {
        return "Vaquill{baseUrl=" + baseUrl + "}";
    }

    /** Builder for {@link Vaquill}. */
    public static final class Builder {
        private String apiKey;
        private String baseUrl;
        private Duration timeout = Duration.ofSeconds(60);
        private int maxRetries = 2;
        private final Map<String, String> defaultHeaders = new TreeMap<String, String>(String.CASE_INSENSITIVE_ORDER);
        private boolean idempotencyKeys = true;
        private Double maxCredits;
        private HttpClient httpClient;
        private VaquillLogger logger = VaquillLogger.system();
        private ai.vaquill.sdk.internal.Sleeper sleeper = ai.vaquill.sdk.internal.Sleeper.SYSTEM;
        private Function<String, String> env = System::getenv;
        private Transport.Config shared;

        private Builder() {}

        /**
         * The API key ({@code vq_key_...}). Defaults to the {@code VAQUILL_API_KEY} environment variable.
         *
         * @param apiKey the key
         * @return this
         */
        public Builder apiKey(String apiKey) {
            this.apiKey = apiKey;
            return this;
        }

        /**
         * The base URL. Defaults to {@code VAQUILL_BASE_URL}, then {@code https://api.vaquill.ai}.
         *
         * @param baseUrl the URL
         * @return this
         */
        public Builder baseUrl(String baseUrl) {
            this.baseUrl = baseUrl;
            return this;
        }

        /**
         * The per-request timeout (default 60 seconds). {@link Duration#ZERO} disables it.
         *
         * @param timeout the timeout
         * @return this
         */
        public Builder timeout(Duration timeout) {
            if (timeout == null || timeout.isNegative()) {
                throw new IllegalArgumentException("timeout must be zero or positive.");
            }
            this.timeout = timeout;
            return this;
        }

        /**
         * Retries after the first attempt (default 2).
         *
         * @param maxRetries at least 0
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
         * An HTTP client to use (proxy, mTLS, executor, test double). Without one the SDK creates its
         * own with a 5 second connect timeout.
         *
         * @param httpClient the client
         * @return this
         */
        public Builder httpClient(HttpClient httpClient) {
            this.httpClient = httpClient;
            return this;
        }

        /**
         * Adds a header sent on every request. Names are case-insensitive; a later value replaces an
         * earlier one. {@code Authorization} and {@code Idempotency-Key} cannot be overridden.
         *
         * @param name the name
         * @param value the value
         * @return this
         */
        public Builder defaultHeader(String name, String value) {
            if (name == null || name.isEmpty() || value == null) {
                throw new IllegalArgumentException("Header name and value are required.");
            }
            this.defaultHeaders.put(name, value);
            return this;
        }

        /**
         * Adds several default headers.
         *
         * @param headers the headers
         * @return this
         */
        public Builder defaultHeaders(Map<String, String> headers) {
            for (Map.Entry<String, String> e : headers.entrySet()) {
                defaultHeader(e.getKey(), e.getValue());
            }
            return this;
        }

        /**
         * Sends an auto-generated {@code Idempotency-Key} on charged calls (default true). When
         * false, charged calls are not retried after an ambiguous failure.
         *
         * @param enabled whether to generate keys
         * @return this
         */
        public Builder idempotencyKeys(boolean enabled) {
            this.idempotencyKeys = enabled;
            return this;
        }

        /**
         * The spend guard. Charged calls throw {@link SpendGuardExceededException} once the credits
         * consumed through this client reach the cap. The guard is exact: charged calls are
         * serialised, so concurrent threads cannot overshoot it by more than the one call in flight.
         *
         * @param maxCredits the cap, zero or more
         * @return this
         */
        public Builder maxCredits(double maxCredits) {
            if (Double.isNaN(maxCredits) || maxCredits < 0) {
                throw new IllegalArgumentException("maxCredits must be zero or positive.");
            }
            this.maxCredits = maxCredits;
            return this;
        }

        /**
         * Where log lines go (default: {@link System.Logger} {@code ai.vaquill.sdk}). API keys are redacted.
         *
         * @param logger the logger, or null to discard
         * @return this
         */
        public Builder logger(VaquillLogger logger) {
            this.logger = logger == null ? VaquillLogger.noop() : logger;
            return this;
        }

        Builder sleeper(ai.vaquill.sdk.internal.Sleeper sleeper) {
            this.sleeper = sleeper;
            return this;
        }

        Builder env(Function<String, String> env) {
            this.env = env;
            return this;
        }

        /**
         * Builds the client.
         *
         * @return the client
         * @throws VaquillException when no API key is available or it is malformed
         */
        public Vaquill build() {
            Transport.Config c = new Transport.Config();
            c.apiKey = resolveKey(apiKey, env);
            String base = baseUrl != null ? baseUrl : env.apply(BASE_URL_ENV);
            if (base == null || base.trim().isEmpty()) {
                base = DEFAULT_BASE_URL;
            }
            c.baseUrl = base.trim().replaceAll("/+$", "");
            c.timeout = timeout;
            c.maxRetries = maxRetries;
            c.defaultHeaders.putAll(defaultHeaders);
            c.idempotencyKeys = idempotencyKeys;
            c.maxCredits = maxCredits;
            c.logger = logger;
            c.sleeper = sleeper;
            c.http = httpClient != null ? httpClient
                    : HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(5)).build();
            if (shared != null) {
                c.spend = shared.spend;
                c.pool = shared.pool;
            }
            return new Vaquill(c);
        }

        private static String resolveKey(String given, Function<String, String> env) {
            String key = given != null ? given : env.apply(API_KEY_ENV);
            // A key pasted from a file or a secret store often carries a trailing newline.
            key = key == null ? null : key.trim();
            if (key == null || key.isEmpty()) {
                throw new VaquillException("No API key. Call apiKey(...) or set the " + API_KEY_ENV + " variable.");
            }
            for (int i = 0; i < key.length(); i++) {
                char ch = key.charAt(i);
                if (ch < 33 || ch > 126) {
                    // The key is deliberately not echoed.
                    throw new VaquillException("Invalid API key: it contains control, whitespace or non-ASCII "
                            + "characters. Check for a stray newline or quote in the value.");
                }
            }
            if (!key.toLowerCase(Locale.ROOT).startsWith(API_KEY_PREFIX)) {
                throw new VaquillException("Invalid API key: Vaquill keys start with '" + API_KEY_PREFIX + "'.");
            }
            return key;
        }
    }
}
