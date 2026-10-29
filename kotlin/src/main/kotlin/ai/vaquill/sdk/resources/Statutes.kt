package ai.vaquill.sdk.resources

import ai.vaquill.sdk.CursorStyle
import ai.vaquill.sdk.HasMoreId
import ai.vaquill.sdk.Idempotency
import ai.vaquill.sdk.NextOffsetOrHasMore
import ai.vaquill.sdk.Paginator
import ai.vaquill.sdk.RequestOptions
import ai.vaquill.sdk.VaquillClient
import ai.vaquill.sdk.body
import ai.vaquill.sdk.models.ExtractCitationsResponse
import ai.vaquill.sdk.models.PartRulemakingResponse
import ai.vaquill.sdk.models.SectionEnactmentsResponse
import ai.vaquill.sdk.models.SectionRulemakingResponse
import ai.vaquill.sdk.models.StatuteBodyResponse
import ai.vaquill.sdk.models.StatuteChangeEvent
import ai.vaquill.sdk.models.StatuteChangesResponse
import ai.vaquill.sdk.models.StatuteCitedByResponse
import ai.vaquill.sdk.models.StatuteCountResponse
import ai.vaquill.sdk.models.StatuteCrossStateResponse
import ai.vaquill.sdk.models.StatuteDefinitionsResponse
import ai.vaquill.sdk.models.StatuteNeighborsResponse
import ai.vaquill.sdk.models.StatuteResolveBatchItem
import ai.vaquill.sdk.models.StatuteResolveBatchResponse
import ai.vaquill.sdk.models.StatuteResolveResponse
import ai.vaquill.sdk.models.StatuteResult
import ai.vaquill.sdk.models.StatuteSearchResponse
import ai.vaquill.sdk.models.StatuteSectionResponse
import ai.vaquill.sdk.models.StatuteSectionsResponse
import ai.vaquill.sdk.models.UsDivisionNode
import ai.vaquill.sdk.models.UsStatutesCoverageEnvelope
import ai.vaquill.sdk.models.UsStatutesDivisionsResponse
import ai.vaquill.sdk.seg
import ai.vaquill.sdk.strs
import ai.vaquill.sdk.unique
import ai.vaquill.sdk.wireParams

/**
 * Filters for [Statutes.search] and [Statutes.iterSearch]. Unset members are not sent, so the
 * server default applies. A single-element list is sent as a plain string.
 */
public data class SearchFilters(
    val state: String? = null,
    val corpusType: List<String>? = null,
    val actStatus: String? = null,
    val agency: List<String>? = null,
    val article: List<String>? = null,
    val changedSince: String? = null,
    val chapter: List<String>? = null,
    val code: List<String>? = null,
    val documentType: String? = null,
    val excerptChars: Int? = null,
    val excludeRepealed: Boolean? = null,
    val fields: List<String>? = null,
    val includeBody: Boolean? = null,
    val includePinpoint: Boolean? = null,
    val limit: Int? = null,
    val matchType: String? = null,
    val part: List<String>? = null,
    val publishedFrom: String? = null,
    val publishedTo: String? = null,
    val source: String? = null,
    val titleNumber: Int? = null,
    val yearFrom: Int? = null,
    val yearTo: Int? = null,
) {
    internal fun members(): Array<Pair<String, Any?>> = arrayOf(
        "state" to state, "corpusType" to strs(corpusType), "actStatus" to actStatus, "agency" to strs(agency),
        "article" to strs(article), "changedSince" to changedSince, "chapter" to strs(chapter),
        "code" to strs(code), "documentType" to documentType, "excerptChars" to excerptChars,
        "excludeRepealed" to excludeRepealed, "fields" to fields, "includeBody" to includeBody,
        "includePinpoint" to includePinpoint, "limit" to limit, "matchType" to matchType,
        "part" to strs(part), "publishedFrom" to publishedFrom, "publishedTo" to publishedTo,
        "source" to source, "titleNumber" to titleNumber, "yearFrom" to yearFrom, "yearTo" to yearTo,
    )
}

/** Hierarchy filters for [Statutes.divisions] and [Statutes.iterDivisions]. */
public data class DivisionFilters(
    val state: String? = null,
    val titleNumber: Int? = null,
    val code: String? = null,
    val chapter: String? = null,
    val part: String? = null,
    val article: String? = null,
    val excludeRepealed: Boolean? = null,
    val actStatus: String? = null,
    val subchapter: String? = null,
    val act: String? = null,
    val title: String? = null,
    val subtitle: String? = null,
    val division: String? = null,
    val subdivision: String? = null,
    val subpart: String? = null,
    val subjectGroup: String? = null,
) {
    internal fun members(): Array<Pair<String, Any?>> = arrayOf(
        "state" to state, "titleNumber" to titleNumber, "code" to code, "chapter" to chapter, "part" to part,
        "article" to article, "excludeRepealed" to excludeRepealed, "actStatus" to actStatus,
        "subchapter" to subchapter, "act" to act, "title" to title, "subtitle" to subtitle,
        "division" to division, "subdivision" to subdivision, "subpart" to subpart, "subjectGroup" to subjectGroup,
    )
}

/**
 * `client.statutes`: search, retrieve and follow US primary law. Every method except [coverage]
 * is charged: it sends an automatic `Idempotency-Key`, is checked against the client's
 * `maxCredits` and is counted in `creditsSpent`.
 */
public class Statutes internal constructor(private val client: VaquillClient) {
    private val base = "$API/us/statutes"

    /** Search statutes, regulations and rules. Charged. */
    public suspend fun search(
        query: String,
        filters: SearchFilters = SearchFilters(),
        offset: Int? = null,
        options: RequestOptions = RequestOptions(),
    ): StatuteSearchResponse = client.call(
        "POST", "$base/search", json = body("query" to query, *filters.members(), "offset" to offset),
        charged = true, options = options,
    )

    /**
     * Iterate every search result across pages. WARNING: every page is charged, so always set
     * [maxPages] or [maxItems] unless you intend to read everything.
     */
    public fun iterSearch(
        query: String,
        filters: SearchFilters = SearchFilters(),
        maxPages: Int? = null,
        maxItems: Int? = null,
    ): Paginator<StatuteResult> = client.paginate(
        NextOffsetOrHasMore, "results", wireParams("query" to query, *filters.members(), "offset" to 0L), maxPages, maxItems,
    ) { p -> client.fetchObject("POST", "$base/search", null, body(p), charged = true) }

    /** Resolve one citation (`"42 U.S.C. 1983"`) to its section. Charged. */
    public suspend fun resolve(
        cite: String,
        state: String? = null,
        corpusType: String? = null,
        options: RequestOptions = RequestOptions(),
    ): StatuteResolveResponse = client.call(
        "GET", "$base/resolve", query = wireParams("cite" to cite, "state" to state, "corpusType" to corpusType),
        charged = true, options = options,
    )

    /** Resolve up to 500 citations in one call. Charged. */
    public suspend fun resolveBatch(
        citations: List<String>,
        state: String? = null,
        corpusType: String? = null,
        options: RequestOptions = RequestOptions(),
    ): StatuteResolveBatchResponse = client.call(
        "POST", "$base/resolve", json = body("citations" to citations, "state" to state, "corpusType" to corpusType),
        charged = true, options = options,
    )

    /**
     * Resolve any number of citations: duplicates removed, sent in chunks of [RESOLVE_BATCH_MAX].
     * Each chunk is a separate charged call; a caller idempotency key is suffixed per chunk.
     */
    public suspend fun resolveBatchAll(
        citations: List<String>,
        state: String? = null,
        corpusType: String? = null,
        options: RequestOptions = RequestOptions(),
    ): List<StatuteResolveBatchItem> {
        val results = mutableListOf<StatuteResolveBatchItem>()
        unique(citations).chunked(RESOLVE_BATCH_MAX).forEachIndexed { i, chunk ->
            val r = resolveBatch(chunk, state, corpusType, options.copy(idempotencyKey = Idempotency.forChunk(options.idempotencyKey, i)))
            results += r.results.orEmpty()
        }
        return results
    }

    /** One section by id (or citation). Charged. */
    public suspend fun getSection(actId: String, options: RequestOptions = RequestOptions()): StatuteSectionResponse =
        client.call("GET", "$base/section/${seg(actId)}", charged = true, options = options)

    /** A section's body text; `asOf` reads it as it stood on a past date. Charged. */
    public suspend fun getSectionBody(
        actId: String,
        format: String? = null,
        structured: Boolean? = null,
        pinpoint: String? = null,
        asOf: String? = null,
        options: RequestOptions = RequestOptions(),
    ): StatuteBodyResponse = client.call(
        "GET", "$base/section/${seg(actId)}/body",
        query = wireParams("format" to format, "structured" to structured, "pinpoint" to pinpoint, "asOf" to asOf),
        charged = true, options = options,
    )

    /** Neighbouring sections (`/related`). Charged. */
    public suspend fun neighbors(actId: String, limit: Int? = null, options: RequestOptions = RequestOptions()): StatuteNeighborsResponse =
        client.call("GET", "$base/section/${seg(actId)}/related", query = wireParams("limit" to limit), charged = true, options = options)

    /** Up to 50 sections by id in one call. Charged. */
    public suspend fun getSectionsBatch(
        actIds: List<String>,
        includeBody: Boolean? = null,
        options: RequestOptions = RequestOptions(),
    ): StatuteSectionsResponse = client.call(
        "POST", "$base/sections", json = body("actIds" to actIds, "includeBody" to includeBody),
        charged = true, options = options,
    )

    /** Any number of sections: duplicates removed, sent in chunks of [SECTIONS_BATCH_MAX]. Charged per chunk. */
    public suspend fun getSectionsAll(
        actIds: List<String>,
        includeBody: Boolean? = null,
        options: RequestOptions = RequestOptions(),
    ): List<StatuteResult> {
        val sections = mutableListOf<StatuteResult>()
        unique(actIds).chunked(SECTIONS_BATCH_MAX).forEachIndexed { i, chunk ->
            val r = getSectionsBatch(chunk, includeBody, options.copy(idempotencyKey = Idempotency.forChunk(options.idempotencyKey, i)))
            sections += r.sections.orEmpty()
        }
        return sections
    }

    /** Count sections in a scope, or matching a Boolean expression (`matchType = "boolean"`). Charged. */
    public suspend fun count(
        query: String? = null,
        state: String? = null,
        corpusType: List<String>? = null,
        actStatus: String? = null,
        article: List<String>? = null,
        chapter: List<String>? = null,
        code: List<String>? = null,
        excludeRepealed: Boolean? = null,
        matchType: String? = null,
        part: List<String>? = null,
        titleNumber: Int? = null,
        options: RequestOptions = RequestOptions(),
    ): StatuteCountResponse = client.call(
        "POST", "$base/count",
        json = body(
            "query" to query, "state" to state, "corpusType" to strs(corpusType), "actStatus" to actStatus,
            "article" to strs(article), "chapter" to strs(chapter), "code" to strs(code),
            "excludeRepealed" to excludeRepealed, "matchType" to matchType, "part" to strs(part), "titleNumber" to titleNumber,
        ),
        charged = true, options = options,
    )

    /** What the corpus holds per jurisdiction and corpus type. Free. */
    public suspend fun coverage(state: String? = null, options: RequestOptions = RequestOptions()): UsStatutesCoverageEnvelope =
        client.call("GET", "$base/coverage", query = wireParams("state" to state), options = options)

    /** Browse the hierarchy of a corpus. Charged. */
    public suspend fun divisions(
        corpusType: String,
        filters: DivisionFilters = DivisionFilters(),
        cursor: String? = null,
        options: RequestOptions = RequestOptions(),
    ): UsStatutesDivisionsResponse = client.call(
        "GET", "$base/divisions", query = wireParams("corpusType" to corpusType, *filters.members(), "cursor" to cursor),
        charged = true, options = options,
    )

    /** Iterate every division node across pages. Every page is charged: set [maxPages] or [maxItems]. */
    public fun iterDivisions(
        corpusType: String,
        filters: DivisionFilters = DivisionFilters(),
        maxPages: Int? = null,
        maxItems: Int? = null,
    ): Paginator<UsDivisionNode> = client.paginate(
        CursorStyle, "divisions", wireParams("corpusType" to corpusType, *filters.members()), maxPages, maxItems,
    ) { p -> client.fetchObject("GET", "$base/divisions", p, null, charged = true) }

    /** A section's change history. Charged. */
    public suspend fun sectionChanges(
        actId: String,
        limit: Int? = null,
        sinceId: Long? = null,
        beforeId: Long? = null,
        changeKind: List<String>? = null,
        order: String? = null,
        options: RequestOptions = RequestOptions(),
    ): StatuteChangesResponse = client.call(
        "GET", "$base/section/${seg(actId)}/changes",
        query = wireParams("limit" to limit, "sinceId" to sinceId, "beforeId" to beforeId, "changeKind" to changeKind, "order" to order),
        charged = true, options = options,
    )

    /** Iterate a section's changes across pages. Newest first unless `order = "asc"`. Charged per page. */
    public fun iterSectionChanges(
        actId: String,
        limit: Int = 50,
        changeKind: List<String>? = null,
        order: String = "desc",
        maxPages: Int? = null,
        maxItems: Int? = null,
    ): Paginator<StatuteChangeEvent> = client.paginate(
        HasMoreId(if (order == "asc") "sinceId" else "beforeId"), "changes",
        wireParams("limit" to limit, "changeKind" to changeKind, "order" to order), maxPages, maxItems,
    ) { p -> client.fetchObject("GET", "$base/section/${seg(actId)}/changes", p, null, charged = true) }

    /** The session laws that enacted a section. Charged. */
    public suspend fun enactments(actId: String, options: RequestOptions = RequestOptions()): SectionEnactmentsResponse =
        client.call("GET", "$base/section/${seg(actId)}/enactments", charged = true, options = options)

    /** Rulemaking tied to a CFR section. Charged. */
    public suspend fun sectionRulemaking(actId: String, options: RequestOptions = RequestOptions()): SectionRulemakingResponse =
        client.call("GET", "$base/section/${seg(actId)}/rulemaking", charged = true, options = options)

    /** Rulemaking for a CFR part. Charged. */
    public suspend fun partRulemaking(
        title: Int,
        part: String,
        years: Int? = null,
        options: RequestOptions = RequestOptions(),
    ): PartRulemakingResponse = client.call(
        "GET", "$base/part/$title/${seg(part)}/rulemaking", query = wireParams("years" to years),
        charged = true, options = options,
    )

    /** Sections that cite this one. Charged. */
    public suspend fun citedBy(actId: String, limit: Int? = null, options: RequestOptions = RequestOptions()): StatuteCitedByResponse =
        client.call("GET", "$base/section/${seg(actId)}/cited-by", query = wireParams("limit" to limit), charged = true, options = options)

    /** Terms this section defines. Charged. */
    public suspend fun definitions(actId: String, options: RequestOptions = RequestOptions()): StatuteDefinitionsResponse =
        client.call("GET", "$base/section/${seg(actId)}/definitions", charged = true, options = options)

    /** Equivalent sections in other states. Charged. */
    public suspend fun crossState(actId: String, limit: Int? = null, options: RequestOptions = RequestOptions()): StatuteCrossStateResponse =
        client.call("GET", "$base/section/${seg(actId)}/cross-state", query = wireParams("limit" to limit), charged = true, options = options)

    /** Find statute citations in free text, optionally resolving them. Charged. */
    public suspend fun extractCitations(
        text: String,
        state: String? = null,
        resolve: Boolean? = null,
        includeUnresolved: Boolean? = null,
        options: RequestOptions = RequestOptions(),
    ): ExtractCitationsResponse = client.call(
        "POST", "$base/extract-citations",
        json = body("text" to text, "state" to state, "resolve" to resolve, "includeUnresolved" to includeUnresolved),
        charged = true, options = options,
    )
}
