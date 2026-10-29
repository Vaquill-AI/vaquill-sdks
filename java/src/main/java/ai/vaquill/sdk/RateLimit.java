package ai.vaquill.sdk;

import java.util.List;
import java.util.Locale;
import java.util.Map;

/** Parsed {@code X-RateLimit-*} headers. Any value is null when the server omitted it. */
public final class RateLimit {
    private final Long limit;
    private final Long remaining;
    private final Double reset;
    private final Long limitDay;
    private final Long remainingDay;
    private final Double resetDay;

    private RateLimit(Map<String, List<String>> h) {
        limit = longOf(h, "x-ratelimit-limit");
        remaining = longOf(h, "x-ratelimit-remaining");
        reset = doubleOf(h, "x-ratelimit-reset");
        limitDay = longOf(h, "x-ratelimit-limit-day");
        remainingDay = longOf(h, "x-ratelimit-remaining-day");
        resetDay = doubleOf(h, "x-ratelimit-reset-day");
    }

    static RateLimit fromHeaders(Map<String, List<String>> headers) {
        return new RateLimit(headers);
    }

    private static String get(Map<String, List<String>> h, String name) {
        for (Map.Entry<String, List<String>> e : h.entrySet()) {
            if (e.getKey() != null && e.getKey().toLowerCase(Locale.ROOT).equals(name) && !e.getValue().isEmpty()) {
                return e.getValue().get(0);
            }
        }
        return null;
    }

    private static Long longOf(Map<String, List<String>> h, String name) {
        String v = get(h, name);
        try {
            return v == null ? null : Long.valueOf(v.trim());
        } catch (NumberFormatException e) {
            return null;
        }
    }

    private static Double doubleOf(Map<String, List<String>> h, String name) {
        String v = get(h, name);
        try {
            return v == null ? null : Double.valueOf(v.trim());
        } catch (NumberFormatException e) {
            return null;
        }
    }

    /** @return requests allowed per minute, or null */
    public Long getLimit() {
        return limit;
    }

    /** @return requests left in the current minute window, or null */
    public Long getRemaining() {
        return remaining;
    }

    /** @return when the minute window resets (epoch seconds), or null */
    public Double getReset() {
        return reset;
    }

    /** @return requests allowed per day, or null */
    public Long getLimitDay() {
        return limitDay;
    }

    /** @return requests left today, or null */
    public Long getRemainingDay() {
        return remainingDay;
    }

    /** @return when the daily window resets (epoch seconds), or null */
    public Double getResetDay() {
        return resetDay;
    }

    @Override
    public String toString() {
        return "RateLimit{limit=" + limit + ", remaining=" + remaining + ", limitDay=" + limitDay
                + ", remainingDay=" + remainingDay + "}";
    }
}
