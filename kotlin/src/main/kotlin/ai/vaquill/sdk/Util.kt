package ai.vaquill.sdk

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import java.time.Instant
import java.time.LocalDate
import java.time.OffsetDateTime
import java.time.ZonedDateTime
import java.time.format.DateTimeFormatter

/** The JSON configuration used for every request and response. */
public val VaquillJson: Json = Json {
    ignoreUnknownKeys = true
    coerceInputValues = true
    explicitNulls = false
    encodeDefaults = false
}

private const val UNRESERVED = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~"
private const val HEX = "0123456789ABCDEF"

internal fun percentEncode(value: String): String {
    val sb = StringBuilder()
    for (b in value.toByteArray(Charsets.UTF_8)) {
        val c = b.toInt() and 0xff
        if (c < 128 && UNRESERVED.indexOf(c.toChar()) >= 0) {
            sb.append(c.toChar())
        } else {
            sb.append('%').append(HEX[c shr 4]).append(HEX[c and 15])
        }
    }
    return sb.toString()
}

/**
 * Percent-encode one path segment (a citation may be passed where an id goes).
 *
 * Rejects an empty segment (it would produce `//`) and `.` or `..`, which a URL parser resolves
 * away and so would silently call another endpoint.
 */
internal fun seg(value: String): String {
    require(value != "" && value != "." && value != "..") {
        "Invalid path segment '$value': it must not be empty, '.' or '..'."
    }
    return percentEncode(value)
}

/** One query value as text: booleans as true/false, instants and dates as unquoted RFC 3339. */
internal fun queryText(v: Any): String = when (v) {
    is Boolean -> if (v) "true" else "false"
    is Instant -> DateTimeFormatter.ISO_INSTANT.format(v)
    is OffsetDateTime -> DateTimeFormatter.ISO_OFFSET_DATE_TIME.format(v)
    is ZonedDateTime -> DateTimeFormatter.ISO_OFFSET_DATE_TIME.format(v)
    is LocalDate -> DateTimeFormatter.ISO_LOCAL_DATE.format(v)
    is Double -> if (v % 1.0 == 0.0 && Math.abs(v) < 1e15) v.toLong().toString() else v.toString()
    is JsonPrimitive -> v.content
    else -> v.toString()
}

/** Encode query parameters. Null values are dropped; lists repeat the key. */
internal fun encodeQuery(params: Map<String, Any?>?): String {
    if (params.isNullOrEmpty()) return ""
    val parts = mutableListOf<String>()
    for ((k, v) in params) {
        when (v) {
            null -> {}
            is Iterable<*> -> v.forEach { if (it != null) parts += "${percentEncode(k)}=${percentEncode(queryText(it))}" }
            else -> parts += "${percentEncode(k)}=${percentEncode(queryText(v))}"
        }
    }
    return parts.joinToString("&")
}

/** Convert a plain Kotlin value to JSON. */
internal fun toJson(v: Any?): JsonElement = when (v) {
    null -> JsonNull
    is JsonElement -> v
    is Boolean -> JsonPrimitive(v)
    is Number -> JsonPrimitive(v)
    is String -> JsonPrimitive(v)
    is Iterable<*> -> JsonArray(v.map { toJson(it) })
    is Map<*, *> -> JsonObject(v.entries.associate { (k, x) -> k.toString() to toJson(x) })
    is Instant, is OffsetDateTime, is ZonedDateTime, is LocalDate -> JsonPrimitive(queryText(v))
    else -> JsonPrimitive(v.toString())
}

/** A request body from named members; unset (null) members are not sent so the server default applies. */
internal fun body(vararg members: Pair<String, Any?>): JsonObject =
    JsonObject(members.filter { it.second != null }.associate { it.first to toJson(it.second) })

/** A body from a members map (used by paginators). */
internal fun body(members: Map<String, Any?>): JsonObject =
    JsonObject(members.filterValues { it != null }.mapValues { toJson(it.value) })

/** A list-or-string union on the wire: a single value is sent as a plain string. */
internal fun strs(values: List<String>?): Any? = when {
    values == null -> null
    values.size == 1 -> values[0]
    else -> values
}

/** The items without exact repeats, first occurrence kept, order preserved. */
internal fun <T> unique(items: List<T>): List<T> = LinkedHashSet(items).toList()

/** Drop unset members. */
internal fun wireParams(vararg members: Pair<String, Any?>): LinkedHashMap<String, Any?> =
    LinkedHashMap<String, Any?>().apply { for ((k, v) in members) if (v != null) put(k, v) }
