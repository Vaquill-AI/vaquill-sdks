package ai.vaquill.sdk.internal;

import java.time.Instant;
import java.time.LocalDate;
import java.time.OffsetDateTime;
import java.time.ZonedDateTime;
import java.time.format.DateTimeFormatter;
import java.util.Map;

/** Query string encoding. Internal: not part of the public API. */
public final class QueryEncoder {
    private QueryEncoder() {}

    /**
     * Encodes a query map. Null values are skipped, booleans are {@code true}/{@code false},
     * instants are RFC 3339 and unquoted, and arrays repeat the key.
     *
     * @param query the parameters in wire (camelCase) names
     * @return the query string without a leading {@code ?}, or an empty string
     */
    public static String encode(Map<String, ?> query) {
        if (query == null || query.isEmpty()) {
            return "";
        }
        StringBuilder sb = new StringBuilder();
        for (Map.Entry<String, ?> e : query.entrySet()) {
            Object v = e.getValue();
            if (v == null) {
                continue;
            }
            if (v instanceof Iterable) {
                for (Object item : (Iterable<?>) v) {
                    if (item != null) {
                        add(sb, e.getKey(), item);
                    }
                }
            } else if (v instanceof Object[]) {
                for (Object item : (Object[]) v) {
                    if (item != null) {
                        add(sb, e.getKey(), item);
                    }
                }
            } else {
                add(sb, e.getKey(), v);
            }
        }
        return sb.toString();
    }

    private static void add(StringBuilder sb, String key, Object value) {
        if (sb.length() > 0) {
            sb.append('&');
        }
        sb.append(Paths.encode(key)).append('=').append(Paths.encode(format(value)));
    }

    /**
     * Renders one scalar the way the API expects it.
     *
     * @param v the value
     * @return the wire text
     */
    public static String format(Object v) {
        if (v instanceof Boolean || v instanceof CharSequence) {
            return v.toString();
        }
        if (v instanceof Instant) {
            return DateTimeFormatter.ISO_INSTANT.format((Instant) v);
        }
        if (v instanceof OffsetDateTime) {
            return DateTimeFormatter.ISO_OFFSET_DATE_TIME.format((OffsetDateTime) v);
        }
        if (v instanceof ZonedDateTime) {
            return DateTimeFormatter.ISO_OFFSET_DATE_TIME.format((ZonedDateTime) v);
        }
        if (v instanceof LocalDate) {
            return DateTimeFormatter.ISO_LOCAL_DATE.format((LocalDate) v);
        }
        if (v instanceof Double || v instanceof Float) {
            double d = ((Number) v).doubleValue();
            return d == Math.rint(d) && !Double.isInfinite(d) ? Long.toString((long) d) : v.toString();
        }
        return v.toString();
    }
}
