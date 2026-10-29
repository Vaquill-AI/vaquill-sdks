package ai.vaquill.sdk.internal;

import ai.vaquill.sdk.ApiStatusException;
import java.net.http.HttpConnectTimeoutException;
import java.time.Duration;
import java.time.Instant;
import java.time.ZonedDateTime;
import java.time.format.DateTimeFormatter;
import java.util.Arrays;
import java.util.HashSet;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.ThreadLocalRandom;

/** Retry policy: which failures are retried and how long to wait. Internal. */
public final class Retry {
    static final double INITIAL_DELAY = 0.5;
    static final double MAX_DELAY = 8.0;
    /** A server-requested wait longer than this is not worth holding the caller for. */
    static final double MAX_RETRY_AFTER = 120.0;

    private static final Set<String> RETRYABLE_CODES = new HashSet<String>(Arrays.asList(
            "rate_limited", "idempotency_in_progress", "upstream_timeout", "service_unavailable", "internal_error"));
    private static final Set<String> NEVER_RETRY_CODES =
            new HashSet<String>(Arrays.asList("insufficient_credits", "daily_cap_exceeded"));

    private Retry() {}

    /**
     * 0.5 s doubling to an 8 s cap, scaled down by 0 to 25 percent jitter.
     *
     * @param retriesDone retries already made
     * @return seconds to wait
     */
    public static double backoffDelay(int retriesDone) {
        double base = Math.min(INITIAL_DELAY * Math.pow(2.0, retriesDone), MAX_DELAY);
        return base * (1 - 0.25 * ThreadLocalRandom.current().nextDouble());
    }

    /**
     * Seconds to wait: {@code retry-after-ms}, then {@code retry-after} seconds, then an HTTP date.
     *
     * @param headers response headers
     * @return seconds, or null when absent or unusable
     */
    public static Double parseRetryAfter(Map<String, List<String>> headers) {
        String ms = first(headers, "retry-after-ms");
        try {
            if (ms != null) {
                double wait = Double.parseDouble(ms.trim()) / 1000.0;
                return Double.isFinite(wait) ? Math.max(wait, 0.0) : null;
            }
            String value = first(headers, "retry-after");
            if (value == null) {
                return null;
            }
            double wait;
            try {
                wait = Double.parseDouble(value.trim());
            } catch (NumberFormatException e) {
                ZonedDateTime when = ZonedDateTime.parse(value.trim(), DateTimeFormatter.RFC_1123_DATE_TIME);
                wait = Duration.between(Instant.now(), when.toInstant()).toMillis() / 1000.0;
            }
            return Double.isFinite(wait) ? Math.max(wait, 0.0) : null;
        } catch (RuntimeException e) {
            return null;
        }
    }

    static String first(Map<String, List<String>> headers, String name) {
        for (Map.Entry<String, List<String>> e : headers.entrySet()) {
            if (e.getKey() != null && e.getKey().toLowerCase(Locale.ROOT).equals(name) && !e.getValue().isEmpty()) {
                return e.getValue().get(0);
            }
        }
        return null;
    }

    /**
     * Whether the server's answer is worth retrying. Keys on the code, falls back to the status.
     *
     * @param error the error
     * @return true when a retry may help
     */
    public static boolean statusIsRetryable(ApiStatusException error) {
        int status = error.getStatusCode();
        if (status == 501) {
            return false;
        }
        String code = error.getCode();
        if ((code != null && NEVER_RETRY_CODES.contains(code)) || Boolean.FALSE.equals(error.getRetryable())) {
            return false;
        }
        if (code != null && RETRYABLE_CODES.contains(code)) {
            return true;
        }
        return status == 408 || status == 429 || status >= 500;
    }

    /**
     * Seconds to wait before retrying this error, or null to raise it instead.
     *
     * @param error the error
     * @param retriesDone retries already made
     * @param replaySafe false for a charged call sent without an idempotency key: a 5xx there may
     *     have been processed (and billed), so it is raised instead of replayed
     * @return seconds, or null
     */
    public static Double delayForStatus(ApiStatusException error, int retriesDone, boolean replaySafe) {
        if (!statusIsRetryable(error)) {
            return null;
        }
        if (!replaySafe && error.getStatusCode() >= 500) {
            return null;
        }
        Double wait = parseRetryAfter(error.getHeaders());
        Double body = error.getRetryAfterSeconds();
        if (wait == null && body != null && Double.isFinite(body)) {
            wait = body;
        }
        if (wait == null) {
            return backoffDelay(retriesDone);
        }
        return wait > MAX_RETRY_AFTER ? null : wait;
    }

    /**
     * Connect failures never reached the server, so they are always safe to retry. Any other
     * transport failure is ambiguous (the request may have been processed) and is retried only for
     * GET and HEAD, or when the call carries an idempotency key.
     *
     * @param error the transport failure
     * @param method the HTTP method
     * @param hasKey whether the call carries an idempotency key
     * @return true when a retry is safe
     */
    public static boolean connectionErrorIsRetryable(java.io.IOException error, String method, boolean hasKey) {
        if (error instanceof java.net.ConnectException || error instanceof HttpConnectTimeoutException) {
            return true;
        }
        String m = method.toUpperCase(Locale.ROOT);
        return m.equals("GET") || m.equals("HEAD") || hasKey;
    }
}
