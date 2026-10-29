package ai.vaquill.sdk

import com.sun.net.httpserver.HttpServer
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import java.io.File
import java.net.InetAddress
import java.net.InetSocketAddress
import java.util.concurrent.CopyOnWriteArrayList
import java.util.concurrent.ExecutorService
import java.util.concurrent.Executors

const val TEST_KEY = "vq_key_testkey0123456789abcdef"

class Req(val method: String, val rawPath: String, val rawQuery: String?, val headers: Map<String, String>, val body: String) {
    fun header(name: String): String? = headers[name.lowercase()]
    fun json(): JsonElement = Json.parseToJsonElement(body)
}

class Reply(
    val status: Int = 200,
    val body: String = "{}",
    val headers: Map<String, String> = emptyMap(),
    val delayMs: Long = 0,
    val abort: Boolean = false,
)

/** A local HTTP server that records requests and answers from a script or a function. */
class FakeServer : AutoCloseable {
    private val server: HttpServer = HttpServer.create(InetSocketAddress(InetAddress.getLoopbackAddress(), 0), 0)
    val requests = CopyOnWriteArrayList<Req>()

    @Volatile
    var responder: (Req, Int) -> Reply = { _, _ -> Reply() }

    init {
        server.createContext("/") { ex ->
            val bytes = ex.requestBody.readBytes()
            val headers = ex.requestHeaders.entries.associate { it.key.lowercase() to it.value.first() }
            val req = Req(ex.requestMethod, ex.requestURI.rawPath, ex.requestURI.rawQuery, headers, String(bytes))
            val n = synchronized(requests) { requests.add(req); requests.size }
            val reply = responder(req, n)
            if (reply.delayMs > 0) Thread.sleep(reply.delayMs)
            if (reply.abort) {
                ex.close()
            } else {
                val out = reply.body.toByteArray()
                reply.headers.forEach { (k, v) -> ex.responseHeaders.add(k, v) }
                ex.responseHeaders.add("Content-Type", "application/json")
                if (reply.status == 204) {
                    ex.sendResponseHeaders(204, -1)
                } else {
                    ex.sendResponseHeaders(reply.status, out.size.toLong())
                    ex.responseBody.write(out)
                }
                ex.close()
            }
        }
        server.executor = Executors.newFixedThreadPool(16)
        server.start()
    }

    val url: String get() = "http://127.0.0.1:${server.address.port}"

    /** Answer with each reply in turn; the last one repeats. */
    fun script(vararg replies: Reply) {
        responder = { _, n -> replies[minOf(n, replies.size) - 1] }
    }

    override fun close() {
        server.stop(0)
        (server.executor as ExecutorService).shutdownNow()
    }
}

class Sleeps {
    val millis = CopyOnWriteArrayList<Long>()
}

fun client(server: FakeServer, sleeps: Sleeps = Sleeps(), block: VaquillClient.Builder.() -> Unit = {}): VaquillClient =
    VaquillClient {
        apiKey = TEST_KEY
        baseUrl = server.url
        logger = VaquillLogger.NONE
        sleeper = { sleeps.millis.add(it) }
        block()
    }

/** The frozen OpenAPI contract, read from `../openapi/vaquill-us.json`. */
object Spec {
    val root: JsonObject = Json.parseToJsonElement(File(System.getProperty("vaquill.spec")).readText()).jsonObject
    val schemas: JsonObject = root["components"]!!.jsonObject["schemas"]!!.jsonObject

    class Op(val id: String, val method: String, val path: String, val charged: Boolean, val status: String, val response: JsonObject?, val hasBody: Boolean)

    val operations: List<Op> = root["paths"]!!.jsonObject.flatMap { (path, item) ->
        item.jsonObject.filterKeys { it in setOf("get", "post", "put", "patch", "delete") }.map { (m, op) ->
            val o = op.jsonObject
            val params = o["parameters"]?.jsonArray ?: JsonArray(emptyList())
            val charged = params.any { it.jsonObject["name"]?.jsonPrimitive?.content == "Idempotency-Key" }
            val ok = o["responses"]!!.jsonObject.keys.first { it.startsWith("2") }
            val schema = o["responses"]!!.jsonObject[ok]!!.jsonObject["content"]?.jsonObject?.get("application/json")?.jsonObject?.get("schema")?.jsonObject
            Op(o["operationId"]!!.jsonPrimitive.content, m.uppercase(), path, charged, ok, schema, o["requestBody"] != null)
        }
    }

    private fun resolve(s: JsonObject): JsonObject = s["\$ref"]?.jsonPrimitive?.content?.let { schemas[it.substringAfterLast('/')]!!.jsonObject } ?: s

    /** A document that satisfies [schema]: required members only unless [full]. */
    fun sample(schema: JsonObject, full: Boolean = false, depth: Int = 0): JsonElement {
        val s = resolve(schema)
        s["anyOf"]?.let { any ->
            val pick = any.jsonArray.map { it.jsonObject }.first { it["type"]?.jsonPrimitive?.content != "null" }
            return sample(pick, full, depth)
        }
        s["enum"]?.let { return it.jsonArray.first() }
        return when (s["type"]?.jsonPrimitive?.content) {
            "object" -> {
                val props = s["properties"]?.jsonObject ?: return JsonObject(emptyMap())
                val required = s["required"]?.jsonArray?.map { it.jsonPrimitive.content }?.toSet() ?: emptySet()
                JsonObject(
                    props.filter { (k, _) -> k in required || (full && depth < 3) }
                        .mapValues { (_, v) -> sample(v.jsonObject, full, depth + 1) },
                )
            }
            "array" -> {
                val items = s["items"]?.jsonObject
                if (full && depth < 3 && items != null) JsonArray(listOf(sample(items, full, depth + 1))) else JsonArray(emptyList())
            }
            "string" -> JsonPrimitive(if (s["format"]?.jsonPrimitive?.content == "date") "2026-01-01" else "x")
            "integer" -> JsonPrimitive(1)
            "number" -> JsonPrimitive(1)
            "boolean" -> JsonPrimitive(true)
            else -> JsonPrimitive("x")
        }
    }
}
