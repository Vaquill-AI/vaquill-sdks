package ai.vaquill.sdk.resources

import ai.vaquill.sdk.CursorStyle
import ai.vaquill.sdk.HasMoreCursor
import ai.vaquill.sdk.HasMoreId
import ai.vaquill.sdk.HasMoreOffset
import ai.vaquill.sdk.Idempotency
import ai.vaquill.sdk.Paginator
import ai.vaquill.sdk.RequestOptions
import ai.vaquill.sdk.VaquillClient
import ai.vaquill.sdk.body
import ai.vaquill.sdk.models.SessionLawBatchLaw
import ai.vaquill.sdk.models.SessionLawBatchResponse
import ai.vaquill.sdk.models.SessionLawBodyResponse
import ai.vaquill.sdk.models.SessionLawChange
import ai.vaquill.sdk.models.SessionLawChangesResponse
import ai.vaquill.sdk.models.SessionLawListResponse
import ai.vaquill.sdk.models.SessionLawResponse
import ai.vaquill.sdk.models.SessionLawSearchResponse
import ai.vaquill.sdk.models.SessionLawSearchResult
import ai.vaquill.sdk.models.SessionLawSummary
import ai.vaquill.sdk.models.SessionLawVersionsResponse
import ai.vaquill.sdk.seg
import ai.vaquill.sdk.unique
import ai.vaquill.sdk.wireParams
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject

/** Filters for [SessionLaws.list] and [SessionLaws.iterList]. Lists are sent as repeated query keys. */
public data class SessionLawListFilters(
    val session: String? = null,
    val series: List<String>? = null,
    val instrumentType: List<String>? = null,
    val approvedFrom: String? = null,
    val approvedTo: String? = null,
    val effectiveFrom: String? = null,
    val effectiveTo: String? = null,
    val hasText: Boolean? = null,
    val textStatus: String? = null,
    val isLaw: Boolean? = null,
    val enactmentOutcome: List<String>? = null,
    val updatedSince: String? = null,
    val q: String? = null,
    val limit: Int? = null,
) {
    internal fun members(): Array<Pair<String, Any?>> = arrayOf(
        "session" to session, "series" to series, "instrumentType" to instrumentType, "approvedFrom" to approvedFrom,
        "approvedTo" to approvedTo, "effectiveFrom" to effectiveFrom, "effectiveTo" to effectiveTo,
        "hasText" to hasText, "textStatus" to textStatus, "isLaw" to isLaw, "enactmentOutcome" to enactmentOutcome,
        "updatedSince" to updatedSince, "q" to q, "limit" to limit,
    )
}

/** `client.sessionLaws`: acts as enacted. Every method is charged. */
public class SessionLaws internal constructor(private val client: VaquillClient) {
    private val base = "$API/us/session-laws"

    /** Search session laws. Charged. */
    public suspend fun search(
        query: String,
        jurisdiction: String? = null,
        session: String? = null,
        series: List<String>? = null,
        instrumentType: List<String>? = null,
        approvedFrom: String? = null,
        approvedTo: String? = null,
        limit: Int? = null,
        offset: Int? = null,
        options: RequestOptions = RequestOptions(),
    ): SessionLawSearchResponse = client.call(
        "POST", "$base/search",
        json = body(
            "query" to query, "jurisdiction" to jurisdiction, "session" to session, "series" to series,
            "instrumentType" to instrumentType, "approvedFrom" to approvedFrom, "approvedTo" to approvedTo,
            "limit" to limit, "offset" to offset,
        ),
        charged = true, options = options,
    )

    /** Iterate search results across pages. Every page is charged: set [maxPages] or [maxItems]. */
    public fun iterSearch(
        query: String,
        jurisdiction: String? = null,
        session: String? = null,
        series: List<String>? = null,
        instrumentType: List<String>? = null,
        approvedFrom: String? = null,
        approvedTo: String? = null,
        limit: Int = 10,
        maxPages: Int? = null,
        maxItems: Int? = null,
    ): Paginator<SessionLawSearchResult> = client.paginate(
        HasMoreOffset, "results",
        wireParams(
            "query" to query, "jurisdiction" to jurisdiction, "session" to session, "series" to series,
            "instrumentType" to instrumentType, "approvedFrom" to approvedFrom, "approvedTo" to approvedTo,
            "limit" to limit, "offset" to 0L,
        ),
        maxPages, maxItems,
    ) { p -> client.fetchObject("POST", "$base/search", null, body(p), charged = true) }

    /** List a jurisdiction's session laws (cursor paged). Charged. */
    public suspend fun list(
        jurisdiction: String,
        filters: SessionLawListFilters = SessionLawListFilters(),
        cursor: String? = null,
        options: RequestOptions = RequestOptions(),
    ): SessionLawListResponse = client.call(
        "GET", "$base/list", query = wireParams("jurisdiction" to jurisdiction, *filters.members(), "cursor" to cursor),
        charged = true, options = options,
    )

    /** Iterate a jurisdiction's session laws across pages. Every page is charged. */
    public fun iterList(
        jurisdiction: String,
        filters: SessionLawListFilters = SessionLawListFilters(),
        maxPages: Int? = null,
        maxItems: Int? = null,
    ): Paginator<SessionLawSummary> = client.paginate(
        CursorStyle, "results", wireParams("jurisdiction" to jurisdiction, *filters.members()), maxPages, maxItems,
    ) { p -> client.fetchObject("GET", "$base/list", p, null, charged = true) }

    /** One session law. Charged. */
    public suspend fun get(sessionLawId: String, jurisdiction: String? = null, options: RequestOptions = RequestOptions()): SessionLawResponse =
        client.call("GET", "$base/${seg(sessionLawId)}", query = wireParams("jurisdiction" to jurisdiction), charged = true, options = options)

    /** One page of a session law's text. Charged. */
    public suspend fun getBody(
        sessionLawId: String,
        cursor: String? = null,
        startChar: Int? = null,
        expectTextSha256: String? = null,
        version: Int? = null,
        includeUnverified: Boolean? = null,
        options: RequestOptions = RequestOptions(),
    ): SessionLawBodyResponse = client.call(
        "GET", "$base/${seg(sessionLawId)}/body",
        query = wireParams(
            "cursor" to cursor, "startChar" to startChar, "expectTextSha256" to expectTextSha256,
            "version" to version, "includeUnverified" to includeUnverified,
        ),
        charged = true, options = options,
    )

    /** Walk a session law's whole text page by page (each page is charged). Emits one [SessionLawBodyResponse] per page. */
    public fun iterBody(
        sessionLawId: String,
        startChar: Int? = null,
        expectTextSha256: String? = null,
        version: Int? = null,
        includeUnverified: Boolean? = null,
        maxPages: Int? = null,
    ): Paginator<SessionLawBodyResponse> = client.paginate(
        HasMoreCursor, PAGES_KEY,
        wireParams(
            "startChar" to startChar, "expectTextSha256" to expectTextSha256, "version" to version,
            "includeUnverified" to includeUnverified,
        ),
        maxPages, null,
    ) { p ->
        val page = client.fetchObject("GET", "$base/${seg(sessionLawId)}/body", p, null, charged = true)
        JsonObject(page + (PAGES_KEY to JsonArray(listOf(page))))
    }

    /** Version history of a session law's text. Charged. */
    public suspend fun versions(sessionLawId: String, options: RequestOptions = RequestOptions()): SessionLawVersionsResponse =
        client.call("GET", "$base/${seg(sessionLawId)}/versions", charged = true, options = options)

    /** Up to 200 session laws by id in one call. Charged. */
    public suspend fun getBatch(
        ids: List<String>,
        jurisdiction: String? = null,
        includeBody: Boolean? = null,
        options: RequestOptions = RequestOptions(),
    ): SessionLawBatchResponse = client.call(
        "POST", "$base/batch", json = body("ids" to ids, "jurisdiction" to jurisdiction, "includeBody" to includeBody),
        charged = true, options = options,
    )

    /** Any number of session laws: duplicates removed, sent in chunks of [SESSION_LAWS_BATCH_MAX]. Charged per chunk. */
    public suspend fun getBatchAll(
        ids: List<String>,
        jurisdiction: String? = null,
        includeBody: Boolean? = null,
        options: RequestOptions = RequestOptions(),
    ): List<SessionLawBatchLaw> {
        val laws = mutableListOf<SessionLawBatchLaw>()
        unique(ids).chunked(SESSION_LAWS_BATCH_MAX).forEachIndexed { i, chunk ->
            val r = getBatch(chunk, jurisdiction, includeBody, options.copy(idempotencyKey = Idempotency.forChunk(options.idempotencyKey, i)))
            laws += r.laws.orEmpty()
        }
        return laws
    }

    /** Session laws added or changed since an id. Charged. */
    public suspend fun changes(
        sinceId: Long? = null,
        jurisdiction: String? = null,
        limit: Int? = null,
        options: RequestOptions = RequestOptions(),
    ): SessionLawChangesResponse = client.call(
        "GET", "$base/changes", query = wireParams("sinceId" to sinceId, "jurisdiction" to jurisdiction, "limit" to limit),
        charged = true, options = options,
    )

    /** Iterate session-law changes forward from [sinceId]. Every page is charged. */
    public fun iterChanges(
        sinceId: Long = 0,
        jurisdiction: String? = null,
        limit: Int = 50,
        maxPages: Int? = null,
        maxItems: Int? = null,
    ): Paginator<SessionLawChange> = client.paginate(
        HasMoreId("sinceId"), "changes",
        wireParams("sinceId" to sinceId, "jurisdiction" to jurisdiction, "limit" to limit), maxPages, maxItems,
    ) { p -> client.fetchObject("GET", "$base/changes", p, null, charged = true) }

    private companion object {
        const val PAGES_KEY = "_pages"
    }
}
