package ai.vaquill.sdk

import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.doubleOrNull
import kotlin.coroutines.AbstractCoroutineContextElement
import kotlin.coroutines.CoroutineContext

/** Parsed `X-RateLimit-*` headers. Any field is null when the server omitted it. */
public data class RateLimit(
    val limit: Int? = null,
    val remaining: Int? = null,
    val reset: Double? = null,
    val limitDay: Int? = null,
    val remainingDay: Int? = null,
    val resetDay: Double? = null,
) {
    public companion object {
        public fun fromHeaders(h: Headers): RateLimit = RateLimit(
            limit = h["X-RateLimit-Limit"]?.trim()?.toIntOrNull(),
            remaining = h["X-RateLimit-Remaining"]?.trim()?.toIntOrNull(),
            reset = h["X-RateLimit-Reset"]?.trim()?.toDoubleOrNull(),
            limitDay = h["X-RateLimit-Limit-Day"]?.trim()?.toIntOrNull(),
            remainingDay = h["X-RateLimit-Remaining-Day"]?.trim()?.toIntOrNull(),
            resetDay = h["X-RateLimit-Reset-Day"]?.trim()?.toDoubleOrNull(),
        )
    }
}

/**
 * What [VaquillClient.withResponse] returns: the parsed result plus status, headers and metering
 * metadata of the (last) HTTP response behind it.
 */
public class ApiResponse<out T> internal constructor(
    /** The parsed result of the call. */
    public val data: T,
    /** HTTP status code. */
    public val statusCode: Int,
    /** Response headers. */
    public val headers: Headers,
    /** The raw JSON body, or null when the response had none. */
    public val json: JsonElement?,
) {
    /** The `X-Request-ID` header. */
    public val requestId: String? get() = headers[REQUEST_ID_HEADER]

    public val rateLimit: RateLimit get() = RateLimit.fromHeaders(headers)

    /** True when the server replayed a stored answer for this idempotency key. */
    public val idempotentReplayed: Boolean get() = headers[REPLAYED_HEADER].equals("true", ignoreCase = true)

    /** `creditsConsumed` from the body when present. The stored figure on a replay. */
    public val creditsConsumed: Double?
        get() = ((json as? JsonObject)?.get("creditsConsumed") as? JsonPrimitive)
            ?.takeIf { !it.isString }?.doubleOrNull

    /** Zero on an idempotent replay, otherwise [creditsConsumed] (0 when absent). */
    public val creditsChargedThisCall: Double
        get() = if (idempotentReplayed) 0.0 else creditsConsumed ?: 0.0
}

/** Result of one HTTP exchange, before typing. */
internal class RawResponse(val status: Int, val headers: Headers, val json: JsonElement?)

/** Coroutine-context element that records the last response for [VaquillClient.withResponse]. */
internal class ResponseCapture : AbstractCoroutineContextElement(Key) {
    @Volatile
    var last: RawResponse? = null

    companion object Key : CoroutineContext.Key<ResponseCapture>
}
