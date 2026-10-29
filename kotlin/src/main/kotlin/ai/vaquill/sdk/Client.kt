package ai.vaquill.sdk

import ai.vaquill.sdk.resources.Boards
import ai.vaquill.sdk.resources.Credits
import ai.vaquill.sdk.resources.Pricing
import ai.vaquill.sdk.resources.SessionLaws
import ai.vaquill.sdk.resources.Statutes
import ai.vaquill.sdk.resources.Watches
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.TimeoutCancellationException
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.delay
import kotlinx.coroutines.ensureActive
import kotlinx.coroutines.future.await
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeout
import kotlinx.serialization.SerializationException
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonPrimitive
import java.io.IOException
import java.net.ConnectException
import java.net.NoRouteToHostException
import java.net.URI
import java.net.UnknownHostException
import java.net.http.HttpClient
import java.net.http.HttpConnectTimeoutException
import java.net.http.HttpRequest
import java.net.http.HttpResponse
import java.net.http.HttpTimeoutException
import java.nio.channels.UnresolvedAddressException
import java.time.Duration
import java.util.concurrent.ExecutorService
import java.util.concurrent.Executors
import java.util.concurrent.atomic.DoubleAdder
import kotlin.random.Random

/** Per-call overrides accepted by every resource method. */
public data class RequestOptions(
    /** Total time for each HTTP attempt. [Duration.ZERO] disables the timeout. */
    val timeout: Duration? = null,
    val maxRetries: Int? = null,
    /** 16 to 255 visible ASCII characters. Charged calls get a generated key when this is null. */
    val idempotencyKey: String? = null,
    /** Extra headers; `Authorization` and `Idempotency-Key` cannot be overridden. */
    val headers: Map<String, String>? = null,
)

internal class ClientConfig(
    val apiKey: String,
    val baseUrl: String,
    val timeout: Duration,
    val maxRetries: Int,
    val defaultHeaders: Map<String, String>,
    val idempotencyKeys: Boolean,
    val maxCredits: Double?,
    val logger: VaquillLogger,
    val sleeper: suspend (Long) -> Unit,
    val random: Random,
)

/** State shared by a client and every client derived from it with [VaquillClient.withOptions]. */
internal class Shared(val http: HttpClient, val executor: ExecutorService?) {
    val spent = DoubleAdder()
    val chargeLock = Mutex()
    val deprecationsSeen: MutableSet<String> = java.util.concurrent.ConcurrentHashMap.newKeySet()
}

private val RESTRICTED_HEADERS = setOf("host", "content-length", "connection", "expect", "upgrade", "transfer-encoding")

/**
 * Client for the Vaquill US Data API. Create one, share it, and [close] it when done.
 *
 * ```kotlin
 * val client = VaquillClient { apiKey = "vq_key_..."; maxCredits = 25.0 }
 * val hits = client.statutes.search("adverse possession", SearchFilters(state = "tx", limit = 5))
 * ```
 *
 * Charged calls are checked against `maxCredits` and counted in [creditsSpent]. All calls are
 * `suspend` functions and safe to issue from many coroutines at once.
 */
public class VaquillClient internal constructor(
    internal val cfg: ClientConfig,
    internal val shared: Shared,
    private val ownsHttp: Boolean,
) : AutoCloseable {
    public val statutes: Statutes = Statutes(this)
    public val sessionLaws: SessionLaws = SessionLaws(this)
    public val watches: Watches = Watches(this)
    public val boards: Boards = Boards(this)
    public val credits: Credits = Credits(this)
    public val pricing: Pricing = Pricing(this)

    /** Base URL requests are sent to. */
    public val baseUrl: String get() = cfg.baseUrl

    /** Credits consumed by charged calls since construction (shared with derived clients). */
    public val creditsSpent: Double get() = shared.spent.sum()

    internal val logger: VaquillLogger = RedactingLogger(cfg.logger, cfg.apiKey)

    override fun toString(): String = "VaquillClient(baseUrl=${cfg.baseUrl})"

    /** Release the threads this client owns. A derived client does not close the shared transport. */
    override fun close() {
        if (!ownsHttp) return
        shared.executor?.shutdown()
        try {
            HttpClient::class.java.getMethod("close").invoke(shared.http) // JDK 21+
        } catch (_: ReflectiveOperationException) {
        } catch (_: RuntimeException) {
        }
    }

    /**
     * Run [block] and return its result with the status, headers and metering metadata of the
     * HTTP response behind it. If the block makes several requests the last response is reported.
     *
     * ```kotlin
     * val r = client.withResponse { credits.balance() }
     * println("${r.requestId} ${r.creditsConsumed}")
     * ```
     */
    public suspend fun <T> withResponse(block: suspend VaquillClient.() -> T): ApiResponse<T> {
        val capture = ResponseCapture()
        val data = withContext(capture) { block() }
        val raw = capture.last ?: throw VaquillException("No request was made inside withResponse.")
        return ApiResponse(data, raw.status, raw.headers, raw.json)
    }

    /** A copy with overrides. Shares the HTTP transport, the spend total and the charge lock. */
    public fun withOptions(block: Builder.() -> Unit): VaquillClient {
        val b = Builder().apply {
            apiKey = cfg.apiKey
            baseUrl = cfg.baseUrl
            timeout = cfg.timeout
            maxRetries = cfg.maxRetries
            defaultHeaders = cfg.defaultHeaders.toMutableMap()
            idempotencyKeys = cfg.idempotencyKeys
            maxCredits = cfg.maxCredits
            logger = cfg.logger
            sleeper = cfg.sleeper
            random = cfg.random
        }
        b.block()
        return VaquillClient(b.toConfig(), shared, ownsHttp = false)
    }

    /**
     * Escape hatch for endpoints newer than this SDK. Returns the body as plain JSON (null for an
     * empty body). `charged = true` adds an idempotency key, the spend-guard check and counting.
     */
    public suspend fun rawRequest(
        method: String,
        path: String,
        query: Map<String, Any?>? = null,
        body: JsonElement? = null,
        charged: Boolean = false,
        options: RequestOptions = RequestOptions(),
    ): JsonElement? = execute(method, path, query, body, charged, options).json

    // ---------------------------------------------------------------- transport

    internal suspend inline fun <reified T> call(
        method: String,
        path: String,
        query: Map<String, Any?>? = null,
        json: JsonElement? = null,
        charged: Boolean = false,
        options: RequestOptions = RequestOptions(),
    ): T {
        val raw = execute(method, path, query, json, charged, options)
        try {
            return VaquillJson.decodeFromJsonElement(kotlinx.serialization.serializer<T>(), raw.json ?: JsonNull)
        } catch (e: SerializationException) {
            throw parseFailure(raw, e)
        } catch (e: IllegalArgumentException) {
            throw parseFailure(raw, e)
        }
    }

    internal fun parseFailure(raw: RawResponse, e: Exception): ResponseParseException = ResponseParseException(
        "Response did not match the expected shape: ${e.message?.take(200)}",
        requestId = raw.headers[REQUEST_ID_HEADER],
        statusCode = raw.status,
        cause = e,
    )

    internal suspend fun execute(
        method: String,
        path: String,
        query: Map<String, Any?>?,
        json: JsonElement?,
        charged: Boolean,
        options: RequestOptions,
    ): RawResponse {
        if (charged && cfg.maxCredits != null) {
            // Check-then-act must be exact: hold the lock from the check until the call is counted.
            return shared.chargeLock.withLock {
                checkSpend(true)
                run(method, path, query, json, true, options)
            }
        }
        return run(method, path, query, json, charged, options)
    }

    private fun checkSpend(charged: Boolean) {
        val cap = cfg.maxCredits
        if (charged && cap != null && creditsSpent >= cap) {
            throw SpendGuardExceededException("Spend guard reached: ${"%g".format(creditsSpent)} of ${"%g".format(cap)} credits used.")
        }
    }

    private fun keyFor(charged: Boolean, given: String?): String? = when {
        given != null -> Idempotency.validate(given)
        charged && cfg.idempotencyKeys -> Idempotency.newKey()
        else -> null
    }

    private fun userAgent(): String =
        "vaquill-kotlin/$SDK_VERSION kotlin/${KotlinVersion.CURRENT} java/${System.getProperty("java.version")} " +
            System.getProperty("os.name", "unknown").lowercase().replace(' ', '-')

    internal fun headersFor(key: String?, extra: Map<String, String>?, hasBody: Boolean): Map<String, String> {
        val out = linkedMapOf("user-agent" to userAgent(), "accept" to "application/json")
        val protected = setOf("authorization", IDEMPOTENCY_HEADER.lowercase())
        for (source in listOf(cfg.defaultHeaders, extra ?: emptyMap())) {
            for ((name, value) in source) {
                val n = name.lowercase()
                require(n !in RESTRICTED_HEADERS) { "The header '$name' is managed by the HTTP transport and cannot be set." }
                if (n !in protected) out[n] = value
            }
        }
        out["authorization"] = "Bearer ${cfg.apiKey}"
        if (key != null) out[IDEMPOTENCY_HEADER.lowercase()] = key
        if (hasBody) out["content-type"] = "application/json"
        return out
    }

    private suspend fun run(
        method: String,
        path: String,
        query: Map<String, Any?>?,
        json: JsonElement?,
        charged: Boolean,
        options: RequestOptions,
    ): RawResponse {
        val key = keyFor(charged, options.idempotencyKey)
        val retries = options.maxRetries ?: cfg.maxRetries
        require(retries >= 0) { "maxRetries must be >= 0." }
        val timeout = options.timeout ?: cfg.timeout
        val q = encodeQuery(query)
        val url = cfg.baseUrl + (if (path.startsWith("/")) path else "/$path") + (if (q.isEmpty()) "" else "?$q")
        val payload = json?.let { VaquillJson.encodeToString(JsonElement.serializer(), it) }
        var attempt = 0
        while (true) {
            val request = buildRequest(method, url, payload, headersFor(key, options.headers, payload != null), timeout)
            logger.log(LogLevel.DEBUG, "Request $method $url key=${key?.let(Idempotency::redact)}")
            val response: HttpResponse<ByteArray> = try {
                sendOnce(request, timeout)
            } catch (e: TimeoutCancellationException) {
                currentCoroutineContext().ensureActive()
                if (attempt < retries && Retry.connectionErrorIsRetryable(false, method, key != null)) {
                    attempt = backoff("timeout", attempt, retries); continue
                }
                throw ApiTimeoutException(e)
            } catch (e: CancellationException) {
                throw e
            } catch (e: IOException) {
                val chain = generateSequence<Throwable>(e) { it.cause }.toList()
                val connect = chain.any {
                    it is ConnectException || it is HttpConnectTimeoutException || it is UnknownHostException ||
                        it is NoRouteToHostException || it is UnresolvedAddressException
                }
                if (attempt < retries && Retry.connectionErrorIsRetryable(connect, method, key != null)) {
                    attempt = backoff(e.javaClass.simpleName, attempt, retries); continue
                }
                throw if (chain.any { it is HttpTimeoutException }) ApiTimeoutException(e) else ApiConnectionException("Connection error.", e)
            }
            val headers = Headers.of(response.headers().map())
            val status = response.statusCode()
            noteDeprecation(method, path, headers)
            val text = String(response.body(), Charsets.UTF_8)
            if (status in 200..299) return finish(status, headers, text, charged, key)
            val error = makeStatusError(status, headers, parseErrorBody(text))
            val replaySafe = key != null || !charged
            val wait = if (attempt < retries) Retry.delayForStatus(error, attempt, replaySafe) else null
            if (wait == null) throw error
            logger.log(LogLevel.DEBUG, "Retrying after status $status in ${"%.2f".format(wait)}s (retry ${attempt + 1} of $retries)")
            cfg.sleeper((wait * 1000).toLong())
            attempt++
        }
    }

    private suspend fun backoff(why: String, attempt: Int, retries: Int): Int {
        val wait = Retry.backoffDelay(attempt, cfg.random)
        logger.log(LogLevel.DEBUG, "Retrying after $why in ${"%.2f".format(wait)}s (retry ${attempt + 1} of $retries)")
        cfg.sleeper((wait * 1000).toLong())
        return attempt + 1
    }

    private fun buildRequest(method: String, url: String, payload: String?, headers: Map<String, String>, timeout: Duration): HttpRequest {
        val b = HttpRequest.newBuilder(URI.create(url))
        for ((k, v) in headers) b.header(k, v)
        if (!timeout.isZero) b.timeout(timeout)
        val publisher = if (payload != null) HttpRequest.BodyPublishers.ofString(payload) else HttpRequest.BodyPublishers.noBody()
        return b.method(method.uppercase(), publisher).build()
    }

    private suspend fun sendOnce(request: HttpRequest, timeout: Duration): HttpResponse<ByteArray> {
        val send = suspend { shared.http.sendAsync(request, HttpResponse.BodyHandlers.ofByteArray()).await() }
        return if (timeout.isZero) send() else withTimeout(timeout.toMillis()) { send() }
    }

    private fun parseErrorBody(text: String): JsonElement? {
        if (text.isBlank()) return null
        return try {
            VaquillJson.parseToJsonElement(text)
        } catch (_: SerializationException) {
            JsonPrimitive(text)
        }
    }

    private suspend fun finish(status: Int, headers: Headers, text: String, charged: Boolean, key: String?): RawResponse {
        if (headers[IDEMPOTENCY_STATUS_HEADER].equals("unavailable", ignoreCase = true)) {
            logger.log(LogLevel.WARN, "Server could not deduplicate this request (idempotency store unavailable).")
        }
        val json = if (text.isBlank()) {
            null
        } else {
            try {
                VaquillJson.parseToJsonElement(text)
            } catch (e: SerializationException) {
                throw ResponseParseException(
                    "Response was not valid JSON (status $status).", headers[REQUEST_ID_HEADER], status, e,
                )
            }
        }
        val raw = RawResponse(status, headers, json)
        if (charged) shared.spent.add(ApiResponse(Unit, status, headers, json).creditsChargedThisCall)
        currentCoroutineContext()[ResponseCapture]?.last = raw
        logger.log(LogLevel.DEBUG, "Response $status key=${key?.let(Idempotency::redact)}")
        return raw
    }

    /** One warning per (method, path) per client family when the server flags an endpoint. */
    private fun noteDeprecation(method: String, path: String, headers: Headers) {
        val deprecation = headers["Deprecation"]
        val sunset = headers["Sunset"]
        if (deprecation == null && sunset == null) return
        if (!shared.deprecationsSeen.add("$method $path")) return
        val details = listOfNotNull(deprecation?.let { "Deprecation: $it" }, sunset?.let { "Sunset: $it" }).joinToString(", ")
        logger.log(LogLevel.WARN, "$method $path is deprecated ($details).")
    }

    /** Builder for [VaquillClient]. */
    public class Builder internal constructor() {
        /** Defaults to the `VAQUILL_API_KEY` environment variable. */
        public var apiKey: String? = null

        /** Defaults to `VAQUILL_BASE_URL`, then `https://api.vaquill.ai`. */
        public var baseUrl: String? = null

        /** Total time for each HTTP attempt; [Duration.ZERO] disables it. Default 60 seconds. */
        public var timeout: Duration = Defaults.TIMEOUT

        /** Retries after the first attempt. Default 2. */
        public var maxRetries: Int = Defaults.MAX_RETRIES

        /** Headers sent on every request (names are matched case-insensitively). */
        public var defaultHeaders: MutableMap<String, String> = mutableMapOf()

        /** Generate an `Idempotency-Key` for every charged call. Default true. */
        public var idempotencyKeys: Boolean = true

        /** Client-side spend cap in credits for charged calls. Null means no cap. */
        public var maxCredits: Double? = null

        /** Log sink; API keys are redacted before they reach it. */
        public var logger: VaquillLogger = VaquillLogger.system()

        /** Supply your own `java.net.http.HttpClient` (the SDK then never closes it). */
        public var httpClient: HttpClient? = null

        internal var sleeper: suspend (Long) -> Unit = { delay(it) }
        internal var random: Random = Random.Default

        public fun defaultHeader(name: String, value: String): Builder = apply { defaultHeaders[name] = value }

        internal fun toConfig(): ClientConfig {
            require(maxRetries >= 0) { "maxRetries must be >= 0." }
            require(!timeout.isNegative) { "timeout must not be negative." }
            val resolvedBase = (baseUrl ?: System.getenv(Defaults.BASE_URL_ENV)?.takeIf { it.isNotBlank() } ?: Defaults.BASE_URL).trimEnd('/')
            return ClientConfig(
                apiKey = resolveApiKey(apiKey),
                baseUrl = resolvedBase,
                timeout = timeout,
                maxRetries = maxRetries,
                defaultHeaders = defaultHeaders.toMap(),
                idempotencyKeys = idempotencyKeys,
                maxCredits = maxCredits,
                logger = logger,
                sleeper = sleeper,
                random = random,
            )
        }

        public fun build(): VaquillClient {
            val cfg = toConfig()
            val given = httpClient
            if (given != null) return VaquillClient(cfg, Shared(given, null), ownsHttp = false)
            val executor = Executors.newCachedThreadPool { r -> Thread(r, "vaquill-http").apply { isDaemon = true } }
            val http = HttpClient.newBuilder()
                .version(HttpClient.Version.HTTP_1_1)
                .connectTimeout(Defaults.CONNECT_TIMEOUT)
                .followRedirects(HttpClient.Redirect.NEVER)
                .executor(executor)
                .build()
            return VaquillClient(cfg, Shared(http, executor), ownsHttp = true)
        }
    }

    public companion object {
        /** `VaquillClient { apiKey = "vq_key_..." }`. */
        public operator fun invoke(block: Builder.() -> Unit = {}): VaquillClient = Builder().apply(block).build()

        /** Builder entry point for callers that prefer not to use the DSL. */
        @JvmStatic
        public fun builder(): Builder = Builder()

        private fun resolveApiKey(given: String?): String {
            val key = (given ?: System.getenv(Defaults.API_KEY_ENV))?.trim()
            if (key.isNullOrEmpty()) {
                throw VaquillException("No API key. Set apiKey or the ${Defaults.API_KEY_ENV} variable.")
            }
            // The key is deliberately never echoed in the messages below.
            require(key.all { it.code in 33..126 }) {
                "Invalid API key: it contains control, whitespace or non-ASCII characters. Check for a stray newline or quote in the value."
            }
            if (!key.startsWith(Defaults.API_KEY_PREFIX)) {
                throw VaquillException("Invalid API key: Vaquill keys start with '${Defaults.API_KEY_PREFIX}'.")
            }
            return key
        }
    }
}
