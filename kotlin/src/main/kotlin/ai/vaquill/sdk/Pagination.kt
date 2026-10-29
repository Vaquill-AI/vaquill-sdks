package ai.vaquill.sdk

import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.flow
import kotlinx.coroutines.flow.toList
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.intOrNull
import kotlinx.serialization.json.longOrNull

/** How to compute the next page's parameters from a response. Null means this was the last page. */
internal fun interface PageStyle {
    fun nextParams(params: Map<String, Any?>, body: JsonObject, items: List<JsonElement>): Map<String, Any?>?
}

private fun JsonObject.prim(key: String): JsonPrimitive? = (this[key] as? JsonPrimitive)?.takeIf { it !is kotlinx.serialization.json.JsonNull }

private fun JsonObject.bool(key: String): Boolean? = prim(key)?.booleanOrNull

/** `offset` request param, `nextOffset` response member (null on the last page). */
internal object OffsetStyle : PageStyle {
    override fun nextParams(params: Map<String, Any?>, body: JsonObject, items: List<JsonElement>) =
        body.prim("nextOffset")?.let { params + ("offset" to (it.longOrNull ?: it.content)) }
}

/** Opaque `cursor` request param, `nextCursor` response member. */
internal object CursorStyle : PageStyle {
    override fun nextParams(params: Map<String, Any?>, body: JsonObject, items: List<JsonElement>) =
        body.prim("nextCursor")?.contentOrNull?.takeIf { it.isNotEmpty() }?.let { params + ("cursor" to it) }
}

/** `sinceId` (walking forward) or `beforeId` (walking back) from the last item's id. */
internal class IdWindowStyle(private val param: String, private val idKey: String = "id") : PageStyle {
    override fun nextParams(params: Map<String, Any?>, body: JsonObject, items: List<JsonElement>): Map<String, Any?>? {
        if (items.isEmpty()) return null
        val limit = params["limit"] as? Int
        if (limit != null && items.size < limit) return null
        val lastId = (items.last() as? JsonObject)?.prim(idKey)?.let { it.longOrNull ?: it.contentOrNull } ?: return null
        return params + (param to lastId)
    }
}

/** Offset paging for responses with `hasMore` but no `nextOffset`. */
internal object HasMoreOffset : PageStyle {
    override fun nextParams(params: Map<String, Any?>, body: JsonObject, items: List<JsonElement>): Map<String, Any?>? {
        val more = body.bool("hasMore") ?: ((params["limit"] as? Int ?: 0).let { it > 0 && items.size >= it })
        if (!more || items.isEmpty()) return null
        return params + ("offset" to ((params["offset"] as? Number)?.toLong() ?: 0L) + items.size)
    }
}

/** `nextOffset` when the server gives one, otherwise step by the rows returned while `hasMore` is true. */
internal object NextOffsetOrHasMore : PageStyle {
    override fun nextParams(params: Map<String, Any?>, body: JsonObject, items: List<JsonElement>): Map<String, Any?>? {
        body.prim("nextOffset")?.let { return params + ("offset" to (it.longOrNull ?: it.content)) }
        if (body.bool("hasMore") == true && items.isNotEmpty()) {
            return params + ("offset" to ((params["offset"] as? Number)?.toLong() ?: 0L) + items.size)
        }
        return null
    }
}

/** Id-window paging that also stops when the server says `hasMore: false`. */
internal class HasMoreId(param: String) : PageStyle {
    private val inner = IdWindowStyle(param)

    override fun nextParams(params: Map<String, Any?>, body: JsonObject, items: List<JsonElement>) =
        if (body.bool("hasMore") == false) null else inner.nextParams(params, body, items)
}

/** `cursor` paging that stops when `hasMore` is false or `pageEnd` reaches `totalChars`. */
internal object HasMoreCursor : PageStyle {
    override fun nextParams(params: Map<String, Any?>, body: JsonObject, items: List<JsonElement>): Map<String, Any?>? {
        val next = body.prim("nextCursor")?.contentOrNull
        if (next.isNullOrEmpty() || body.bool("hasMore") == false) return null
        val end = body.prim("pageEnd")?.intOrNull
        val total = body.prim("totalChars")?.intOrNull
        if (end != null && total != null && end >= total) return null
        return params.filterKeys { it != "startChar" } + ("cursor" to next)
    }
}

/**
 * Auto-paging over a list endpoint, as cold [Flow]s.
 *
 * WARNING: on charged endpoints every page spends credits. Iterating a whole result set can cost
 * far more than one call. Always set `maxPages` or `maxItems` unless you intend to read everything.
 *
 * When a guard stops iteration early, [truncated] is true (this includes a `maxItems` that cut
 * items off the last page). When the server repeats the offset or cursor it was just sent, or
 * answers an empty page with `hasMore: true`, iteration stops and [stuck] is true, rather than
 * looping and spending credits on the same page. Both flags describe the most recent collection.
 */
public class Paginator<T> internal constructor(
    private val logger: VaquillLogger,
    private val fetch: suspend (Map<String, Any?>) -> JsonObject,
    private val style: PageStyle,
    private val itemsKey: String,
    private val params: Map<String, Any?>,
    private val maxPages: Int?,
    private val maxItems: Int?,
    private val parse: (JsonElement) -> T,
) {
    @Volatile
    public var truncated: Boolean = false
        private set

    @Volatile
    public var stuck: Boolean = false
        private set

    /** Each page as a list. Use this to control cost. */
    public fun pages(): Flow<List<T>> = flow {
        truncated = false
        stuck = false
        var next: Map<String, Any?>? = params
        var pages = 0
        var count = 0
        while (next != null) {
            if ((maxPages != null && pages >= maxPages) || (maxItems != null && count >= maxItems)) {
                truncated = true
                return@flow
            }
            val used: Map<String, Any?> = next
            val bodyObj = fetch(used)
            var raw: List<JsonElement> = (bodyObj[itemsKey] as? JsonArray)?.toList() ?: emptyList()
            if (raw.isEmpty() && bodyObj.bool("hasMore") == true) {
                next = null
                markStuck("an empty page with hasMore true")
            } else {
                next = style.nextParams(used, bodyObj, raw)
                if (next != null && next == used) {
                    next = null
                    markStuck("the offset or cursor it was just sent")
                }
            }
            pages++
            if (maxItems != null && raw.size > maxItems - count) {
                raw = raw.take(maxItems - count)
                truncated = true
            }
            count += raw.size
            emit(raw.map(parse))
        }
    }

    /** Every item across pages. */
    public fun items(): Flow<T> = flow { pages().collect { page -> page.forEach { emit(it) } } }

    /** Collect every item into a list. */
    public suspend fun toList(): List<T> = items().toList()

    private fun markStuck(what: String) {
        stuck = true
        logger.log(LogLevel.WARN, "Pagination stopped: the server answered $what. Not fetching again.")
    }
}
