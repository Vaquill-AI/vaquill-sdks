package ai.vaquill.sdk.resources

import ai.vaquill.sdk.PageStyle
import ai.vaquill.sdk.Paginator
import ai.vaquill.sdk.ResponseParseException
import ai.vaquill.sdk.VaquillClient
import ai.vaquill.sdk.VaquillJson
import ai.vaquill.sdk.RawResponse
import kotlinx.serialization.SerializationException
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.serializer

/** Maximum citations per `POST /us/statutes/resolve` call. */
public const val RESOLVE_BATCH_MAX: Int = 500

/** Maximum ids per `POST /us/statutes/sections` call. */
public const val SECTIONS_BATCH_MAX: Int = 50

/** Maximum ids per `POST /us/session-laws/batch` call. */
public const val SESSION_LAWS_BATCH_MAX: Int = 200

internal const val API = "/api/v1"

internal fun badShape(raw: RawResponse, what: String): ResponseParseException =
    ResponseParseException("Response was not a JSON object ($what).", raw.headers["X-Request-ID"], raw.status)

/** Fetch a page as a JSON object; [unwrap] picks the member that holds the page (`data` for free endpoints). */
internal suspend fun VaquillClient.fetchObject(
    method: String,
    path: String,
    query: Map<String, Any?>?,
    json: JsonElement?,
    charged: Boolean,
    unwrap: String? = null,
): JsonObject {
    val raw = execute(method, path, query, json, charged, ai.vaquill.sdk.RequestOptions())
    val top = raw.json as? JsonObject ?: throw badShape(raw, path)
    return if (unwrap == null) top else top[unwrap] as? JsonObject ?: throw badShape(raw, "$path.$unwrap")
}

internal inline fun <reified T> VaquillClient.paginate(
    style: PageStyle,
    itemsKey: String,
    params: Map<String, Any?>,
    maxPages: Int?,
    maxItems: Int?,
    noinline fetch: suspend (Map<String, Any?>) -> JsonObject,
): Paginator<T> = Paginator(logger, fetch, style, itemsKey, params, maxPages, maxItems) { el ->
    try {
        VaquillJson.decodeFromJsonElement(serializer<T>(), el)
    } catch (e: SerializationException) {
        throw ResponseParseException("A page item did not match the expected shape: ${e.message?.take(200)}", cause = e)
    }
}
