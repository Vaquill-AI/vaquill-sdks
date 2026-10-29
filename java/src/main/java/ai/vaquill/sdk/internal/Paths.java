package ai.vaquill.sdk.internal;

import java.nio.charset.StandardCharsets;

/** Path segment encoding. Internal: not part of the public API. */
public final class Paths {
    private static final char[] HEX = "0123456789ABCDEF".toCharArray();

    private Paths() {}

    /**
     * Percent-encodes one path segment, including {@code /}.
     *
     * @param value the raw segment (a citation may be passed where an id goes)
     * @return the encoded segment
     * @throws IllegalArgumentException for an empty segment, {@code .} or {@code ..}, which a URL
     *     parser would resolve to another endpoint
     */
    public static String seg(String value) {
        if (value == null || value.isEmpty() || value.equals(".") || value.equals("..")) {
            throw new IllegalArgumentException(
                    "Invalid path segment '" + (value == null ? "null" : value) + "': it must not be empty, '.' or '..'.");
        }
        return encode(value);
    }

    /**
     * Percent-encodes a path segment of a number.
     *
     * @param value the number
     * @return the segment
     */
    public static String seg(long value) {
        return Long.toString(value);
    }

    /**
     * RFC 3986 percent-encoding (unreserved characters are kept, everything else becomes %XX).
     *
     * @param value the text
     * @return the encoded text
     */
    public static String encode(String value) {
        byte[] bytes = value.getBytes(StandardCharsets.UTF_8);
        StringBuilder sb = new StringBuilder(bytes.length + 8);
        for (byte raw : bytes) {
            int b = raw & 0xff;
            if ((b >= 'A' && b <= 'Z') || (b >= 'a' && b <= 'z') || (b >= '0' && b <= '9')
                    || b == '-' || b == '.' || b == '_' || b == '~') {
                sb.append((char) b);
            } else {
                sb.append('%').append(HEX[b >> 4]).append(HEX[b & 0xf]);
            }
        }
        return sb.toString();
    }
}
