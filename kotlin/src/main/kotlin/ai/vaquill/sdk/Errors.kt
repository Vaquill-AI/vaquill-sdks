package ai.vaquill.sdk

import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.doubleOrNull

/** Base class of every error this SDK raises. */
public open class VaquillException(message: String, cause: Throwable? = null) :
    RuntimeException(message, cause)

/** The client-side `maxCredits` cap was reached; no request was sent. */
public class SpendGuardExceededException(message: String) : VaquillException(message)

/** A 2xx response could not be parsed into the expected model (bad JSON or wrong shape). */
public class ResponseParseException(
    message: String,
    public val requestId: String? = null,
    public val statusCode: Int? = null,
    cause: Throwable? = null,
) : VaquillException(message, cause) {
    override fun toString(): String = "ResponseParseException: $message (status=$statusCode, requestId=$requestId)"
}

/** A webhook delivery failed signature or timestamp verification. */
public open class WebhookVerificationException(message: String, cause: Throwable? = null) :
    VaquillException(message, cause)

/** The signature matched but the body is not a Vaquill event. */
public class WebhookPayloadException(message: String, cause: Throwable? = null) :
    WebhookVerificationException(message, cause)

/** The request never produced an HTTP response. */
public open class ApiConnectionException(message: String = "Connection error.", cause: Throwable? = null) :
    VaquillException(message, cause)

/** The request timed out. */
public class ApiTimeoutException(cause: Throwable? = null) :
    ApiConnectionException("Request timed out.", cause)

/** Marker for the three idempotency error codes. */
public interface IdempotencyConflict

/**
 * The server answered with a 4xx or 5xx status.
 *
 * Branch on the subclass (chosen by [code] first, then by status) and read [requestId],
 * [retryable], [retryAfterSeconds] and [errors] for detail. The code set is open: an unknown
 * code still produces the status-mapped class.
 */
public sealed class ApiStatusException(
    message: String,
    /** HTTP status code. */
    public val status: Int,
    /** Response headers. */
    public val headers: Headers,
    /** Parsed JSON body, or a JSON string primitive holding non-JSON text, or null when empty. */
    public val body: JsonElement?,
) : VaquillException(message) {
    private val envelope: JsonObject = body as? JsonObject ?: JsonObject(emptyMap())

    /** The server's request id (body `requestId`, else the `X-Request-ID` header). */
    public val requestId: String? = envelope.str("requestId") ?: headers[REQUEST_ID_HEADER]

    /** Machine-readable error code, for example `insufficient_credits`. */
    public val code: String? = envelope.str("code")

    /** The server's own retry hint, when it gave one. */
    public val retryable: Boolean? = (envelope["retryable"] as? JsonPrimitive)?.booleanOrNull

    /** Seconds the server asked the caller to wait. */
    public val retryAfterSeconds: Double? =
        (envelope["retryAfterSeconds"] as? JsonPrimitive)?.takeIf { !it.isString }?.doubleOrNull

    /** Legacy `detail` member, unchanged by the server. */
    public val detail: JsonElement? = envelope["detail"]

    /** Validation errors (422), as sent. */
    public val errors: List<JsonElement>? = (envelope["errors"] as? JsonArray)?.toList()

    override fun toString(): String = "${javaClass.simpleName}: $message (status=$status, requestId=$requestId)"
}

public class BadRequestException internal constructor(m: String, s: Int, h: Headers, b: JsonElement?) :
    ApiStatusException(m, s, h, b)

public class AuthenticationException internal constructor(m: String, s: Int, h: Headers, b: JsonElement?) :
    ApiStatusException(m, s, h, b)

/** Out of credits (402). Never retried. */
public class InsufficientCreditsException internal constructor(m: String, s: Int, h: Headers, b: JsonElement?) :
    ApiStatusException(m, s, h, b)

public class PermissionDeniedException internal constructor(m: String, s: Int, h: Headers, b: JsonElement?) :
    ApiStatusException(m, s, h, b)

public class NotFoundException internal constructor(m: String, s: Int, h: Headers, b: JsonElement?) :
    ApiStatusException(m, s, h, b)

public open class ConflictException internal constructor(m: String, s: Int, h: Headers, b: JsonElement?) :
    ApiStatusException(m, s, h, b)

public open class UnprocessableEntityException internal constructor(m: String, s: Int, h: Headers, b: JsonElement?) :
    ApiStatusException(m, s, h, b)

/** 429. [retryAfterSeconds] is set when the server said how long to wait. */
public open class RateLimitException internal constructor(m: String, s: Int, h: Headers, b: JsonElement?) :
    ApiStatusException(m, s, h, b)

/** Per-key daily cap. Retrying cannot succeed until the cap resets. */
public class DailyCapExceededException internal constructor(m: String, s: Int, h: Headers, b: JsonElement?) :
    RateLimitException(m, s, h, b)

public class InternalServerException internal constructor(m: String, s: Int, h: Headers, b: JsonElement?) :
    ApiStatusException(m, s, h, b)

/** Any other 4xx or 5xx status without a more specific class. */
public class UnexpectedStatusException internal constructor(m: String, s: Int, h: Headers, b: JsonElement?) :
    ApiStatusException(m, s, h, b)

/** Same idempotency key sent with a different request (422). */
public class IdempotencyKeyReusedException internal constructor(m: String, s: Int, h: Headers, b: JsonElement?) :
    UnprocessableEntityException(m, s, h, b), IdempotencyConflict

/** The original request is still running (409). Retryable. */
public class IdempotencyInProgressException internal constructor(m: String, s: Int, h: Headers, b: JsonElement?) :
    ConflictException(m, s, h, b), IdempotencyConflict

/**
 * The original completed but its response is too large to replay (409).
 * The call was not charged again. Check `credits.balance()` before retrying.
 */
public class IdempotencyReplayUnavailableException internal constructor(m: String, s: Int, h: Headers, b: JsonElement?) :
    ConflictException(m, s, h, b), IdempotencyConflict

/** Codes the server marks retryable. Anything else is not retried. */
internal val RETRYABLE_CODES = setOf(
    "rate_limited", "idempotency_in_progress", "upstream_timeout", "service_unavailable", "internal_error",
)
internal val NEVER_RETRY_CODES = setOf("insufficient_credits", "daily_cap_exceeded")

private fun JsonObject.str(key: String): String? =
    (this[key] as? JsonPrimitive)?.takeIf { it.isString }?.contentOrNull?.takeIf { it.isNotEmpty() }

/** First few `loc: msg` pairs of a 422 `errors` list, or null. */
private fun validationSummary(errors: JsonElement?): String? {
    val items = (errors as? JsonArray) ?: return null
    val parts = mutableListOf<String>()
    for (raw in items) {
        val item = raw as? JsonObject ?: continue
        val msg = item.str("msg") ?: continue
        var path = (item["loc"] as? JsonArray)?.map { (it as? JsonPrimitive)?.contentOrNull ?: it.toString() } ?: emptyList()
        if (path.size > 1 && path[0] in setOf("body", "query", "path", "header")) path = path.drop(1)
        val where = path.joinToString(".")
        parts += if (where.isNotEmpty()) "$where: $msg" else msg
    }
    if (parts.isEmpty()) return null
    val shown = parts.take(3).joinToString("; ")
    val more = items.size - minOf(parts.size, 3)
    return if (more > 0) "$shown (+$more more)" else shown
}

private fun messageFor(status: Int, body: JsonElement?): String {
    val env = body as? JsonObject ?: JsonObject(emptyMap())
    val detail = env.str("detail")
    if (detail != null) {
        val why = if (status == 422) validationSummary(env["errors"]) else null
        return if (why != null) "$detail: $why" else detail
    }
    env.str("title")?.let { return it }
    return "HTTP $status"
}

/** Map a response to the most specific error class. */
internal fun makeStatusError(status: Int, headers: Headers, body: JsonElement?): ApiStatusException {
    val msg = messageFor(status, body)
    val code = ((body as? JsonObject)?.get("code") as? JsonPrimitive)?.takeIf { it.isString }?.content
    when (code) {
        "insufficient_credits" -> return InsufficientCreditsException(msg, status, headers, body)
        "daily_cap_exceeded" -> return DailyCapExceededException(msg, status, headers, body)
        "idempotency_key_reused" -> return IdempotencyKeyReusedException(msg, status, headers, body)
        "idempotency_in_progress" -> return IdempotencyInProgressException(msg, status, headers, body)
        "idempotency_replay_unavailable" -> return IdempotencyReplayUnavailableException(msg, status, headers, body)
    }
    return when {
        status >= 500 -> InternalServerException(msg, status, headers, body)
        status == 400 -> BadRequestException(msg, status, headers, body)
        status == 401 -> AuthenticationException(msg, status, headers, body)
        status == 402 -> InsufficientCreditsException(msg, status, headers, body)
        status == 403 -> PermissionDeniedException(msg, status, headers, body)
        status == 404 -> NotFoundException(msg, status, headers, body)
        status == 409 -> ConflictException(msg, status, headers, body)
        status == 422 -> UnprocessableEntityException(msg, status, headers, body)
        status == 429 -> RateLimitException(msg, status, headers, body)
        else -> UnexpectedStatusException(msg, status, headers, body)
    }
}
