package ai.vaquill.sdk

import java.time.Instant
import java.time.ZonedDateTime
import java.time.format.DateTimeFormatter
import kotlin.math.pow
import kotlin.random.Random

/** Retry policy: which failures are retried and how long to wait. */
internal object Retry {
    /** 0.5 s doubling to an 8 s cap, scaled down by 0 to 25 percent jitter. */
    fun backoffDelay(retriesDone: Int, random: Random = Random.Default): Double {
        val base = minOf(INITIAL_RETRY_DELAY_SECONDS * 2.0.pow(retriesDone), MAX_RETRY_DELAY_SECONDS)
        return base * (1 - 0.25 * random.nextDouble())
    }

    /** Seconds to wait: `retry-after-ms`, then `retry-after` seconds, then an HTTP date. */
    fun parseRetryAfter(headers: Headers, now: Instant = Instant.now()): Double? {
        headers["retry-after-ms"]?.let { ms ->
            val wait = ms.trim().toDoubleOrNull()?.div(1000.0) ?: return null
            return if (wait.isFinite()) maxOf(wait, 0.0) else null
        }
        val value = headers["retry-after"]?.trim() ?: return null
        val seconds = value.toDoubleOrNull()
        val wait = seconds ?: runCatching {
            (ZonedDateTime.parse(value, DateTimeFormatter.RFC_1123_DATE_TIME).toInstant().toEpochMilli() -
                now.toEpochMilli()) / 1000.0
        }.getOrNull() ?: return null
        return if (wait.isFinite()) maxOf(wait, 0.0) else null
    }

    /** Whether the server's answer is worth retrying. Keys on `code`, falls back to status. */
    fun statusIsRetryable(error: ApiStatusException): Boolean {
        if (error.status == 501) return false // Not Implemented never becomes implemented by waiting.
        if (error.code in NEVER_RETRY_CODES || error.retryable == false) return false
        if (error.code in RETRYABLE_CODES) return true
        return error.status == 408 || error.status == 429 || error.status >= 500
    }

    /**
     * Seconds to wait before retrying this error, or null to raise it instead.
     *
     * [replaySafe] is false for a charged call sent without an idempotency key: a 5xx there may
     * have been processed (and billed) already, so it is raised instead of replayed.
     */
    fun delayForStatus(error: ApiStatusException, retriesDone: Int, replaySafe: Boolean = true): Double? {
        if (!statusIsRetryable(error)) return null
        if (!replaySafe && error.status >= 500) return null
        var wait = parseRetryAfter(error.headers)
        val hint = error.retryAfterSeconds
        if (wait == null && hint != null && hint.isFinite()) wait = hint
        if (wait == null) return backoffDelay(retriesDone)
        // A wait this long means "go away"; give the caller the error now.
        return if (wait > MAX_RETRY_AFTER_SECONDS) null else wait
    }

    /**
     * Connect failures never reached the server, so they are always safe to retry. Any other
     * transport failure is ambiguous (the request may have been processed): it is retried only
     * for GET and HEAD, or when the call carries an idempotency key.
     */
    fun connectionErrorIsRetryable(
        connectPhase: Boolean,
        method: String,
        hasIdempotencyKey: Boolean,
    ): Boolean = connectPhase || method.uppercase() in setOf("GET", "HEAD") || hasIdempotencyKey
}
