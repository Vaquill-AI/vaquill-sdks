package ai.vaquill.sdk

/** Severity of a log line. */
public enum class LogLevel { DEBUG, INFO, WARN, ERROR }

/**
 * Sink for the SDK's log lines. The client wraps whatever you pass so API keys are always
 * redacted before a line reaches it.
 */
public fun interface VaquillLogger {
    public fun log(level: LogLevel, message: String)

    public companion object {
        /** Discards everything. */
        public val NONE: VaquillLogger = VaquillLogger { _, _ -> }

        /** Writes to a `java.lang.System.Logger` (JDK 9+), which routes to SLF4J/JUL/Log4j when bridged. */
        public fun system(name: String = "ai.vaquill.sdk"): VaquillLogger {
            val sys = System.getLogger(name)
            return VaquillLogger { level, message ->
                val l = when (level) {
                    LogLevel.DEBUG -> System.Logger.Level.DEBUG
                    LogLevel.INFO -> System.Logger.Level.INFO
                    LogLevel.WARN -> System.Logger.Level.WARNING
                    LogLevel.ERROR -> System.Logger.Level.ERROR
                }
                sys.log(l, message)
            }
        }
    }
}

private val KEY_PATTERN = Regex("vq_key_[A-Za-z0-9_\\-]+")

/** Replace anything that looks like (or is) the API key. */
internal fun redactSecrets(message: String, secret: String?): String {
    var out = KEY_PATTERN.replace(message, "vq_key_***")
    if (!secret.isNullOrBlank()) out = out.replace(secret, "vq_key_***")
    return out
}

internal class RedactingLogger(private val delegate: VaquillLogger, private val secret: String?) : VaquillLogger {
    override fun log(level: LogLevel, message: String) = delegate.log(level, redactSecrets(message, secret))
}
