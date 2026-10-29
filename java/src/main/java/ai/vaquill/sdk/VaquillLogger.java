package ai.vaquill.sdk;

import java.lang.System.Logger.Level;

/**
 * Receives the SDK's log lines. The client redacts API keys (and anything shaped like one) from
 * every message before it reaches the logger, and logs idempotency keys by their first 8 characters.
 */
public interface VaquillLogger {
    /**
     * Logs one line.
     *
     * @param level the severity
     * @param message the message, already redacted
     */
    void log(Level level, String message);

    /** @return a logger that discards everything */
    static VaquillLogger noop() {
        return (level, message) -> { };
    }

    /**
     * A logger backed by {@link System.Logger} named {@code ai.vaquill.sdk}, so the application's
     * logging backend (java.util.logging, or SLF4J through a bridge) controls it.
     *
     * @return the logger
     */
    static VaquillLogger system() {
        final System.Logger delegate = System.getLogger("ai.vaquill.sdk");
        return (level, message) -> delegate.log(level, message);
    }
}
