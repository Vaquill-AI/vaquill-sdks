package ai.vaquill.sdk.internal;

import ai.vaquill.sdk.ApiStatusException;
import ai.vaquill.sdk.AuthenticationException;
import ai.vaquill.sdk.BadRequestException;
import ai.vaquill.sdk.ConflictException;
import ai.vaquill.sdk.ConnectionException;
import ai.vaquill.sdk.DailyCapExceededException;
import ai.vaquill.sdk.IdempotencyInProgressException;
import ai.vaquill.sdk.IdempotencyKeyReusedException;
import ai.vaquill.sdk.IdempotencyReplayUnavailableException;
import ai.vaquill.sdk.InsufficientCreditsException;
import ai.vaquill.sdk.InternalServerException;
import ai.vaquill.sdk.NotFoundException;
import ai.vaquill.sdk.PermissionDeniedException;
import ai.vaquill.sdk.RateLimitException;
import ai.vaquill.sdk.RequestOptions;
import ai.vaquill.sdk.RequestTimeoutException;
import ai.vaquill.sdk.Response;
import ai.vaquill.sdk.ResponseParseException;
import ai.vaquill.sdk.SpendGuardExceededException;
import ai.vaquill.sdk.UnprocessableEntityException;
import ai.vaquill.sdk.VaquillException;
import ai.vaquill.sdk.VaquillLogger;
import ai.vaquill.sdk.Version;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.JsonNode;
import java.io.IOException;
import java.lang.System.Logger.Level;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.net.http.HttpTimeoutException;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.ArrayList;
import java.util.Collections;
import java.util.HashSet;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import java.util.TreeMap;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.ThreadFactory;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.locks.ReentrantLock;
import java.util.function.Supplier;
import java.util.regex.Pattern;

/**
 * The HTTP engine behind every operation: auth, headers, retries, idempotency, the spend guard and
 * response parsing. Internal: construct clients through {@code Vaquill.builder()}.
 */
public final class Transport {
    private static final Pattern KEY_SHAPE = Pattern.compile("vq_key_[A-Za-z0-9_\\-]+");
    private static final String IDEMPOTENCY = "Idempotency-Key";

    /** Everything a transport needs; assembled by the client builder. */
    public static final class Config {
        /** API key. */
        public String apiKey;
        /** Base URL without a trailing slash. */
        public String baseUrl;
        /** Default timeout; zero disables. */
        public Duration timeout;
        /** Default retries. */
        public int maxRetries;
        /** Headers on every request. */
        public Map<String, String> defaultHeaders = new TreeMap<String, String>(String.CASE_INSENSITIVE_ORDER);
        /** Auto idempotency keys for charged calls. */
        public boolean idempotencyKeys = true;
        /** Spend cap, or null. */
        public Double maxCredits;
        /** The HTTP client. */
        public HttpClient http;
        /** Where log lines go. */
        public VaquillLogger logger;
        /** Sleeper. */
        public Sleeper sleeper = Sleeper.SYSTEM;
        /** Shared spend tracker. */
        public SpendTracker spend = new SpendTracker();
        /** Shared async executor holder. */
        public AsyncPool pool = new AsyncPool();
    }

    /** Lazily created daemon thread pool for the {@code ...Async} methods, shared by derived clients. */
    public static final class AsyncPool {
        private ExecutorService executor;

        /** @return the executor, created on first use */
        public synchronized ExecutorService get() {
            if (executor == null) {
                final AtomicInteger n = new AtomicInteger();
                ThreadFactory tf = r -> {
                    Thread t = new Thread(r, "vaquill-async-" + n.incrementAndGet());
                    t.setDaemon(true);
                    return t;
                };
                executor = Executors.newCachedThreadPool(tf);
            }
            return executor;
        }

        /** Stops the pool if it was created. */
        public synchronized void shutdown() {
            if (executor != null) {
                executor.shutdown();
                executor = null;
            }
        }
    }

    /** One logical request. */
    public static final class Call {
        final String method;
        final String path;
        Map<String, ?> query;
        Object body;
        boolean charged;

        private Call(String method, String path) {
            this.method = method;
            this.path = path;
        }

        /**
         * Starts a call.
         *
         * @param method the HTTP method
         * @param path the path starting with {@code /}
         * @return the call
         */
        public static Call of(String method, String path) {
            return new Call(method, path);
        }

        /**
         * Sets the query.
         *
         * @param q wire-name parameters
         * @return this
         */
        public Call query(Map<String, ?> q) {
            this.query = q;
            return this;
        }

        /**
         * Sets the JSON body.
         *
         * @param b the body
         * @return this
         */
        public Call body(Object b) {
            this.body = b;
            return this;
        }

        /**
         * Marks the call as consuming credits.
         *
         * @param c true for charged operations
         * @return this
         */
        public Call charged(boolean c) {
            this.charged = c;
            return this;
        }
    }

    private final Config cfg;
    private final Set<String> deprecationsSeen = Collections.synchronizedSet(new HashSet<String>());

    /**
     * Creates a transport.
     *
     * @param cfg the configuration
     */
    public Transport(Config cfg) {
        this.cfg = cfg;
    }

    /** @return credits consumed by charged calls through this transport and its derived ones */
    public double creditsSpent() {
        return cfg.spend.total();
    }

    /** @return the asynchronous executor */
    public ExecutorService executor() {
        return cfg.pool.get();
    }

    /**
     * Runs work on the SDK's executor.
     *
     * @param <T> the result type
     * @param work the work
     * @return the future
     */
    public <T> CompletableFuture<T> supplyAsync(Supplier<T> work) {
        return CompletableFuture.supplyAsync(work, cfg.pool.get());
    }

    // ---------------------------------------------------------------- logging

    /**
     * Logs a message with API keys redacted.
     *
     * @param level the level
     * @param message the message
     */
    public void log(Level level, String message) {
        if (cfg.logger == null) {
            return;
        }
        String safe = message.replace(cfg.apiKey, "vq_key_***");
        safe = KEY_SHAPE.matcher(safe).replaceAll("vq_key_***");
        cfg.logger.log(level, safe);
    }

    // ---------------------------------------------------------------- execution

    /**
     * Sends a request and parses the body into {@code type}.
     *
     * @param <T> the result type; {@code Void} for an empty body, {@code JsonNode} for raw JSON
     * @param call the request
     * @param type the result class
     * @param options per-call overrides, or null
     * @return the result with its HTTP metadata
     */
    public <T> Response<T> execute(Call call, Class<T> type, RequestOptions options) {
        RequestOptions opts = options == null ? RequestOptions.none() : options;
        if (call.charged && cfg.maxCredits != null) {
            // Check-then-act must be exact: hold the lock from the check until the call is counted.
            ReentrantLock lock = cfg.spend.serialLock();
            lock.lock();
            try {
                checkSpend(true);
                return run(call, type, opts);
            } finally {
                lock.unlock();
            }
        }
        checkSpend(call.charged);
        return run(call, type, opts);
    }

    private void checkSpend(boolean charged) {
        if (charged && cfg.maxCredits != null && cfg.spend.total() >= cfg.maxCredits) {
            throw new SpendGuardExceededException(String.format(Locale.ROOT,
                    "Spend guard reached: %s of %s credits used.", fmt(cfg.spend.total()), fmt(cfg.maxCredits)));
        }
    }

    private static String fmt(double d) {
        return d == Math.rint(d) ? Long.toString((long) d) : Double.toString(d);
    }

    private <T> Response<T> run(Call call, Class<T> type, RequestOptions opts) {
        String key = keyFor(call.charged, opts.getIdempotencyKey());
        int retries = opts.getMaxRetries() == null ? cfg.maxRetries : opts.getMaxRetries();
        Duration timeout = opts.getTimeout() == null ? cfg.timeout : opts.getTimeout();
        String q = QueryEncoder.encode(call.query);
        URI uri = URI.create(cfg.baseUrl + call.path + (q.isEmpty() ? "" : "?" + q));
        byte[] payload = call.body == null ? null : Json.toBytes(call.body);
        int attempt = 0;
        while (true) {
            HttpRequest request = build(call.method, uri, payload, key, opts, timeout);
            log(Level.DEBUG, "Request " + call.method + " " + uri + " key=" + (key == null ? null : IdempotencyKeys.redact(key)));
            HttpResponse<byte[]> response;
            try {
                response = cfg.http.send(request, HttpResponse.BodyHandlers.ofByteArray());
            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
                throw new VaquillException("Interrupted while waiting for the response.", e);
            } catch (IOException e) {
                if (attempt < retries && Retry.connectionErrorIsRetryable(e, call.method, key != null)) {
                    double delay = Retry.backoffDelay(attempt);
                    logRetry(e.getClass().getSimpleName(), delay, attempt, retries);
                    pause(delay);
                    attempt++;
                    continue;
                }
                String msg = "Request " + call.method + " " + call.path + " failed: " + describe(e);
                if (e instanceof HttpTimeoutException) {
                    throw new RequestTimeoutException("Request timed out. " + msg, e);
                }
                throw new ConnectionException(msg, e);
            }
            noteDeprecation(call.method, call.path, response.headers().map());
            int status = response.statusCode();
            if (status >= 200 && status < 300) {
                return finish(response, call.charged, type, key);
            }
            ApiStatusException error = errorFor(response);
            boolean replaySafe = key != null || !call.charged;
            Double delay = attempt < retries ? Retry.delayForStatus(error, attempt, replaySafe) : null;
            if (delay == null) {
                throw error;
            }
            logRetry("status " + status, delay, attempt, retries);
            pause(delay);
            attempt++;
        }
    }

    private static String describe(IOException e) {
        String m = e.getMessage();
        return e.getClass().getSimpleName() + (m == null ? "" : ": " + m);
    }

    private void logRetry(String why, double delay, int attempt, int retries) {
        log(Level.DEBUG, String.format(Locale.ROOT, "Retrying after %s in %.2fs (retry %d of %d)", why, delay, attempt + 1, retries));
    }

    private void pause(double seconds) {
        try {
            cfg.sleeper.sleep((long) Math.ceil(seconds * 1000.0));
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            throw new VaquillException("Interrupted while waiting to retry.", e);
        }
    }

    private String keyFor(boolean charged, String given) {
        if (given != null) {
            return IdempotencyKeys.validate(given);
        }
        return charged && cfg.idempotencyKeys ? IdempotencyKeys.newKey() : null;
    }

    private HttpRequest build(String method, URI uri, byte[] payload, String key, RequestOptions opts, Duration timeout) {
        HttpRequest.Builder b = HttpRequest.newBuilder(uri);
        TreeMap<String, String> headers = new TreeMap<String, String>(String.CASE_INSENSITIVE_ORDER);
        headers.put("User-Agent", userAgent());
        headers.put("Accept", "application/json");
        if (payload != null) {
            headers.put("Content-Type", "application/json");
        }
        mergeHeaders(headers, cfg.defaultHeaders);
        mergeHeaders(headers, opts.getHeaders());
        headers.put("Authorization", "Bearer " + cfg.apiKey);
        if (key != null) {
            headers.put(IDEMPOTENCY, key);
        }
        for (Map.Entry<String, String> e : headers.entrySet()) {
            b.header(e.getKey(), e.getValue());
        }
        if (timeout != null && !timeout.isZero()) {
            b.timeout(timeout);
        }
        b.method(method, payload == null ? HttpRequest.BodyPublishers.noBody() : HttpRequest.BodyPublishers.ofByteArray(payload));
        return b.build();
    }

    private static void mergeHeaders(Map<String, String> into, Map<String, String> from) {
        for (Map.Entry<String, String> e : from.entrySet()) {
            String n = e.getKey().toLowerCase(Locale.ROOT);
            // Authorization and Idempotency-Key are ours alone.
            if (!n.equals("authorization") && !n.equals("idempotency-key")) {
                into.put(e.getKey(), e.getValue());
            }
        }
    }

    /** @return the {@code User-Agent} sent on every request */
    public static String userAgent() {
        return "vaquill-java/" + Version.VERSION + " java/" + System.getProperty("java.version", "unknown")
                + " " + System.getProperty("os.name", "unknown").toLowerCase(Locale.ROOT);
    }

    private <T> Response<T> finish(HttpResponse<byte[]> response, boolean charged, Class<T> type, String key) {
        Map<String, List<String>> headers = response.headers().map();
        String requestId = firstHeader(headers, "x-request-id");
        if ("unavailable".equalsIgnoreCase(nullToEmpty(firstHeader(headers, "idempotency-status")))) {
            log(Level.WARNING, "Server could not deduplicate this request (idempotency store unavailable).");
        }
        byte[] raw = response.body();
        JsonNode json = null;
        if (raw != null && raw.length > 0) {
            try {
                json = Json.parse(raw);
            } catch (IOException e) {
                throw new ResponseParseException("Response was not valid JSON (status " + response.statusCode() + ").",
                        requestId, response.statusCode(), e);
            }
        }
        T data = null;
        if (type != Void.class) {
            if (json == null) {
                throw new ResponseParseException("Response body was empty (status " + response.statusCode() + ").",
                        requestId, response.statusCode(), null);
            }
            try {
                data = type == JsonNode.class ? type.cast(json) : Json.treeToValue(json, type);
            } catch (JsonProcessingException e) {
                throw new ResponseParseException("Response did not match the expected shape: " + e.getOriginalMessage(),
                        requestId, response.statusCode(), e);
            }
        }
        Response<T> result = new Response<T>(data, response.statusCode(), headers, json);
        if (charged) {
            cfg.spend.add(result.getCreditsChargedThisCall());
        }
        log(Level.DEBUG, "Response " + response.statusCode() + " key=" + (key == null ? null : IdempotencyKeys.redact(key)));
        return result;
    }

    private static String nullToEmpty(String s) {
        return s == null ? "" : s;
    }

    private static String firstHeader(Map<String, List<String>> headers, String name) {
        return Retry.first(headers, name);
    }

    private void noteDeprecation(String method, String path, Map<String, List<String>> headers) {
        String deprecation = firstHeader(headers, "deprecation");
        String sunset = firstHeader(headers, "sunset");
        if (deprecation == null && sunset == null) {
            return;
        }
        if (!deprecationsSeen.add(method + " " + path)) {
            return;
        }
        List<String> parts = new ArrayList<String>();
        if (deprecation != null) {
            parts.add("Deprecation: " + deprecation);
        }
        if (sunset != null) {
            parts.add("Sunset: " + sunset);
        }
        log(Level.WARNING, method + " " + path + " is deprecated (" + String.join(", ", parts) + ").");
    }

    // ---------------------------------------------------------------- errors

    private static ApiStatusException errorFor(HttpResponse<byte[]> response) {
        byte[] raw = response.body() == null ? new byte[0] : response.body();
        Object body;
        try {
            JsonNode node = Json.parse(raw);
            body = node == null || node.isMissingNode() ? new String(raw, StandardCharsets.UTF_8)
                    : Json.MAPPER.convertValue(node, Object.class);
        } catch (IOException e) {
            body = new String(raw, StandardCharsets.UTF_8);
        }
        return makeStatusError(response.statusCode(), response.headers().map(), body);
    }

    /**
     * Maps a status and body to the most specific exception class.
     *
     * @param status the HTTP status
     * @param headers response headers
     * @param body the parsed body
     * @return the exception
     */
    public static ApiStatusException makeStatusError(int status, Map<String, List<String>> headers, Object body) {
        Map<?, ?> env = body instanceof Map ? (Map<?, ?>) body : Collections.emptyMap();
        String message = message(status, env);
        Object code = env.get("code");
        if (code instanceof String) {
            switch ((String) code) {
                case "insufficient_credits":
                    return new InsufficientCreditsException(message, status, headers, body);
                case "daily_cap_exceeded":
                    return new DailyCapExceededException(message, status, headers, body);
                case "idempotency_key_reused":
                    return new IdempotencyKeyReusedException(message, status, headers, body);
                case "idempotency_in_progress":
                    return new IdempotencyInProgressException(message, status, headers, body);
                case "idempotency_replay_unavailable":
                    return new IdempotencyReplayUnavailableException(message, status, headers, body);
                default:
                    break;
            }
        }
        if (status >= 500) {
            return new InternalServerException(message, status, headers, body);
        }
        switch (status) {
            case 400:
                return new BadRequestException(message, status, headers, body);
            case 401:
                return new AuthenticationException(message, status, headers, body);
            case 402:
                return new InsufficientCreditsException(message, status, headers, body);
            case 403:
                return new PermissionDeniedException(message, status, headers, body);
            case 404:
                return new NotFoundException(message, status, headers, body);
            case 409:
                return new ConflictException(message, status, headers, body);
            case 422:
                return new UnprocessableEntityException(message, status, headers, body);
            case 429:
                return new RateLimitException(message, status, headers, body);
            default:
                return new ApiStatusException(message, status, headers, body);
        }
    }

    private static String message(int status, Map<?, ?> env) {
        Object detail = env.get("detail");
        if (detail instanceof String && !((String) detail).isEmpty()) {
            String why = status == 422 ? validationSummary(env.get("errors")) : null;
            return why != null ? detail + ": " + why : (String) detail;
        }
        Object title = env.get("title");
        if (title instanceof String && !((String) title).isEmpty()) {
            return (String) title;
        }
        return "HTTP " + status;
    }

    /** First few {@code loc: msg} pairs of a 422 {@code errors} list, or null. */
    private static String validationSummary(Object errors) {
        if (!(errors instanceof List)) {
            return null;
        }
        List<?> items = (List<?>) errors;
        List<String> parts = new ArrayList<String>();
        for (Object raw : items) {
            if (!(raw instanceof Map)) {
                continue;
            }
            Map<?, ?> item = (Map<?, ?>) raw;
            Object msg = item.get("msg");
            if (!(msg instanceof String) || ((String) msg).isEmpty()) {
                continue;
            }
            List<Object> path = new ArrayList<Object>();
            if (item.get("loc") instanceof List) {
                path.addAll((List<?>) item.get("loc"));
            }
            if (path.size() > 1) {
                String head = String.valueOf(path.get(0));
                if (head.equals("body") || head.equals("query") || head.equals("path") || head.equals("header")) {
                    path.remove(0);
                }
            }
            StringBuilder where = new StringBuilder();
            for (Object p : path) {
                if (where.length() > 0) {
                    where.append('.');
                }
                where.append(p);
            }
            parts.add(where.length() > 0 ? where + ": " + msg : (String) msg);
        }
        if (parts.isEmpty()) {
            return null;
        }
        int shown = Math.min(parts.size(), 3);
        String joined = String.join("; ", parts.subList(0, shown));
        int more = items.size() - shown;
        return more > 0 ? joined + " (+" + more + " more)" : joined;
    }
}
