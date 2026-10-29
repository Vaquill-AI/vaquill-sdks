package ai.vaquill.sdk.resources

import ai.vaquill.sdk.HasMoreId
import ai.vaquill.sdk.HasMoreOffset
import ai.vaquill.sdk.Paginator
import ai.vaquill.sdk.RequestOptions
import ai.vaquill.sdk.VaquillClient
import ai.vaquill.sdk.body
import ai.vaquill.sdk.models.BoardResponse
import ai.vaquill.sdk.models.BoardsEnvelope
import ai.vaquill.sdk.models.ApiCreditPricingResponse
import ai.vaquill.sdk.models.ChangeDiffEnvelope
import ai.vaquill.sdk.models.ChangeResponse
import ai.vaquill.sdk.models.ChangesEnvelope
import ai.vaquill.sdk.models.DeliveriesEnvelope
import ai.vaquill.sdk.models.ExternalCreditBalanceResponse
import ai.vaquill.sdk.models.WatchEnvelope
import ai.vaquill.sdk.models.WatchResponse
import ai.vaquill.sdk.models.WatchTestEnvelope
import ai.vaquill.sdk.models.WatchesEnvelope
import ai.vaquill.sdk.seg
import ai.vaquill.sdk.wireParams
import kotlinx.serialization.json.JsonObject

/** `client.watches`: law-change alerts. Free except [changeDiff]. */
public class Watches internal constructor(private val client: VaquillClient) {
    private val base = "$API/watches"

    /** List your watches. Free. */
    public suspend fun list(limit: Int? = null, offset: Int? = null, options: RequestOptions = RequestOptions()): WatchesEnvelope =
        client.call("GET", base, query = wireParams("limit" to limit, "offset" to offset), options = options)

    /** Iterate all your watches across pages. Free. */
    public fun iterList(limit: Int = 100, maxPages: Int? = null, maxItems: Int? = null): Paginator<WatchResponse> =
        client.paginate(HasMoreOffset, "watches", wireParams("limit" to limit, "offset" to 0L), maxPages, maxItems) { p ->
            client.fetchObject("GET", base, p, null, charged = false, unwrap = "data")
        }

    /**
     * Watch a corpus source and get a webhook or email when it changes. Free.
     *
     * @param corpusType Corpus to watch (see `boards.list`).
     * @param channel `"webhook"` (default), `"email"` or `"both"`.
     * @param webhookAuth Extra auth the server attaches to each delivery, as JSON (see the API reference).
     * @param scope Narrow the watch (see the API reference).
     */
    public suspend fun create(
        corpusType: String,
        state: String? = null,
        channel: String? = null,
        webhookUrl: String? = null,
        webhookSecret: String? = null,
        webhookAuth: JsonObject? = null,
        emailAddress: String? = null,
        scope: JsonObject? = null,
        options: RequestOptions = RequestOptions(),
    ): WatchEnvelope = client.call(
        "POST", base,
        json = body(
            "corpusType" to corpusType, "state" to state, "channel" to channel, "webhookUrl" to webhookUrl,
            "webhookSecret" to webhookSecret, "webhookAuth" to webhookAuth, "emailAddress" to emailAddress, "scope" to scope,
        ),
        options = options,
    )

    /** Change a watch. Only the arguments you pass are updated. Free. */
    public suspend fun update(
        watchId: String,
        webhookUrl: String? = null,
        webhookSecret: String? = null,
        webhookAuth: JsonObject? = null,
        emailAddress: String? = null,
        isActive: Boolean? = null,
        scope: JsonObject? = null,
        options: RequestOptions = RequestOptions(),
    ): WatchEnvelope = client.call(
        "PATCH", "$base/${seg(watchId)}",
        json = body(
            "webhookUrl" to webhookUrl, "webhookSecret" to webhookSecret, "webhookAuth" to webhookAuth,
            "emailAddress" to emailAddress, "isActive" to isActive, "scope" to scope,
        ),
        options = options,
    )

    /** Delete a watch. Free. */
    public suspend fun delete(watchId: String, options: RequestOptions = RequestOptions()) {
        client.execute("DELETE", "$base/${seg(watchId)}", null, null, false, options)
    }

    /** Send a test event to the watch's channel. Free. */
    public suspend fun test(watchId: String, options: RequestOptions = RequestOptions()): WatchTestEnvelope =
        client.call("POST", "$base/${seg(watchId)}/test", options = options)

    /**
     * List the changes a watch has recorded. Free.
     *
     * @param limit Page size, 1 to 200 (server default 50).
     * @param sinceId Only changes with a larger id (walk forward, with `order = "asc"`).
     * @param beforeId Only changes with a smaller id (walk back through history).
     * @param since Only changes detected after this RFC 3339 timestamp.
     */
    public suspend fun changes(
        watchId: String,
        limit: Int? = null,
        sinceId: Long? = null,
        beforeId: Long? = null,
        since: String? = null,
        changeKind: List<String>? = null,
        order: String? = null,
        options: RequestOptions = RequestOptions(),
    ): ChangesEnvelope = client.call(
        "GET", "$base/${seg(watchId)}/changes",
        query = wireParams(
            "limit" to limit, "sinceId" to sinceId, "beforeId" to beforeId, "since" to since,
            "changeKind" to changeKind, "order" to order,
        ),
        options = options,
    )

    /** Iterate a watch's changes across pages (free). Newest first unless `order = "asc"`. */
    public fun iterChanges(
        watchId: String,
        limit: Int = 50,
        since: String? = null,
        changeKind: List<String>? = null,
        order: String = "desc",
        maxPages: Int? = null,
        maxItems: Int? = null,
    ): Paginator<ChangeResponse> = client.paginate(
        HasMoreId(if (order == "asc") "sinceId" else "beforeId"), "changes",
        wireParams("limit" to limit, "since" to since, "changeKind" to changeKind, "order" to order), maxPages, maxItems,
    ) { p -> client.fetchObject("GET", "$base/${seg(watchId)}/changes", p, null, charged = false, unwrap = "data") }

    /** Before and after text of one change. Charged. */
    public suspend fun changeDiff(watchId: String, changeId: Long, options: RequestOptions = RequestOptions()): ChangeDiffEnvelope =
        client.call("GET", "$base/${seg(watchId)}/changes/$changeId/diff", charged = true, options = options)

    /** Recent webhook and email deliveries for a watch, with delivery health. Free. */
    public suspend fun deliveries(watchId: String, limit: Int? = null, options: RequestOptions = RequestOptions()): DeliveriesEnvelope =
        client.call("GET", "$base/${seg(watchId)}/deliveries", query = wireParams("limit" to limit), options = options)
}

/** `client.boards`: the sources a watch can follow (free). */
public class Boards internal constructor(private val client: VaquillClient) {
    private val path = "$API/boards"

    /** List the sources you can watch, with `lastRetrievedAt` and `cadence`. Free. */
    public suspend fun list(
        corpusType: String? = null,
        state: String? = null,
        limit: Int? = null,
        offset: Int? = null,
        options: RequestOptions = RequestOptions(),
    ): BoardsEnvelope = client.call(
        "GET", path, query = wireParams("corpusType" to corpusType, "state" to state, "limit" to limit, "offset" to offset),
        options = options,
    )

    /** Iterate every board across pages. Free, so no credit guard is needed. */
    public fun iterList(
        corpusType: String? = null,
        state: String? = null,
        limit: Int = 500,
        maxPages: Int? = null,
        maxItems: Int? = null,
    ): Paginator<BoardResponse> = client.paginate(
        HasMoreOffset, "boards", wireParams("corpusType" to corpusType, "state" to state, "limit" to limit, "offset" to 0L),
        maxPages, maxItems,
    ) { p -> client.fetchObject("GET", path, p, null, charged = false, unwrap = "data") }
}

/** `client.credits`: your credit balance (free). */
public class Credits internal constructor(private val client: VaquillClient) {
    /** Credits this key's account can spend right now, from live buckets. Free. */
    public suspend fun balance(options: RequestOptions = RequestOptions()): ExternalCreditBalanceResponse =
        client.call("GET", "$API/credits/balance", options = options)
}

/** `client.pricing`: the credit price of every endpoint (free). */
public class Pricing internal constructor(private val client: VaquillClient) {
    /** The full pricing matrix: credits and USD per endpoint. Free. */
    public suspend fun get(region: String? = null, options: RequestOptions = RequestOptions()): ApiCreditPricingResponse =
        client.call("GET", "$API/api-credits/pricing", query = wireParams("region" to region), options = options)
}
