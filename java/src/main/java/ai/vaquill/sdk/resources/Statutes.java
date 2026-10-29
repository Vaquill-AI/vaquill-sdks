package ai.vaquill.sdk.resources;

import ai.vaquill.sdk.RequestOptions;
import ai.vaquill.sdk.internal.IdempotencyKeys;
import ai.vaquill.sdk.internal.Paths;
import ai.vaquill.sdk.internal.Transport;
import ai.vaquill.sdk.models.GetSectionChangesParams;
import ai.vaquill.sdk.models.ListStatuteDivisionsParams;
import ai.vaquill.sdk.models.StatuteChangeEvent;
import ai.vaquill.sdk.models.StatuteResolveBatchItem;
import ai.vaquill.sdk.models.StatuteResolveBatchRequest;
import ai.vaquill.sdk.models.StatuteResolveBatchResponse;
import ai.vaquill.sdk.models.StatuteResult;
import ai.vaquill.sdk.models.StatuteSearchRequest;
import ai.vaquill.sdk.models.StatuteSectionsRequest;
import ai.vaquill.sdk.models.StatuteSectionsResponse;
import ai.vaquill.sdk.models.UsDivisionNode;
import ai.vaquill.sdk.pagination.PageStyles;
import ai.vaquill.sdk.pagination.Paginator;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.CompletableFuture;

/**
 * US statutes, regulations, court rules and constitutions: search, resolve a citation, read a
 * section, browse the hierarchy and follow change history.
 *
 * <p>Besides the generated operations this class adds auto-paging iterators ({@link #iterSearch},
 * {@link #iterDivisions}, {@link #iterSectionChanges}) and chunking batch helpers
 * ({@link #resolveBatchAll}, {@link #getSectionsAll}). Every page or chunk is charged, so combine
 * them with {@code maxCredits} on the client and {@code maxPages}/{@code maxItems} on the iterator.
 */
public final class Statutes extends StatutesBase {
    /** Citations per call of {@code POST /us/statutes/resolve} (the spec's cap). */
    public static final int RESOLVE_BATCH_MAX = 500;
    /** Section ids per call of {@code POST /us/statutes/sections} (the spec's cap). */
    public static final int SECTIONS_BATCH_MAX = 50;

    /**
     * Creates the namespace. Use {@code Vaquill.statutes()} instead.
     *
     * @param transport the transport
     */
    public Statutes(Transport transport) {
        super(transport);
    }

    /**
     * Iterates {@link #search} results across pages. Every page is charged: set a guard.
     *
     * @param request the search; its {@code offset}, when set, is where iteration starts
     * @return the paginator
     */
    public Paginator<StatuteResult> iterSearch(StatuteSearchRequest request) {
        Map<String, Object> params = Pages.wire(request);
        params.putIfAbsent("offset", 0L);
        return Paginator.of(Pages.post(transport, "/api/v1/us/statutes/search"), PageStyles.nextOffsetOrHasMore(),
                "results", params, Pages.parser(StatuteResult.class), transport.executor());
    }

    /**
     * Iterates {@link #divisions} across pages with the {@code nextCursor}. Every page is charged.
     *
     * @param corpusType the corpus to browse
     * @param params optional filters, or null
     * @return the paginator
     */
    public Paginator<UsDivisionNode> iterDivisions(String corpusType, ListStatuteDivisionsParams params) {
        Map<String, Object> q = new LinkedHashMap<String, Object>();
        q.put("corpusType", corpusType);
        q = Pages.merge(q, params == null ? null : params.toQuery());
        return Paginator.of(Pages.get(transport, "/api/v1/us/statutes/divisions", true, false), PageStyles.cursor(),
                "divisions", q, Pages.parser(UsDivisionNode.class), transport.executor());
    }

    /**
     * Iterates a section's changes across pages: newest first, or oldest first with {@code order=asc}.
     * Every page is charged.
     *
     * @param actId the section id
     * @param params optional filters (limit defaults to 50), or null
     * @return the paginator
     */
    public Paginator<StatuteChangeEvent> iterSectionChanges(String actId, GetSectionChangesParams params) {
        Map<String, Object> q = Pages.merge(new LinkedHashMap<String, Object>(), params == null ? null : params.toQuery());
        q.putIfAbsent("limit", 50L);
        q.putIfAbsent("order", "desc");
        String style = "asc".equals(q.get("order")) ? "sinceId" : "beforeId";
        return Paginator.of(
                Pages.get(transport, "/api/v1/us/statutes/section/" + Paths.seg(actId) + "/changes", true, false),
                PageStyles.hasMoreId(style), "changes", q, Pages.parser(StatuteChangeEvent.class), transport.executor());
    }

    /**
     * Resolves any number of citations by chunking {@link #resolveBatch}. Charged.
     *
     * <p>Sends at most {@value #RESOLVE_BATCH_MAX} citations per call and returns the results of every
     * call as one flat list, in order. Exact repeats are sent once. The {@code maxCredits} guard is
     * checked before each chunk, so a guard reached part way throws and the later chunks are not sent.
     * A caller's idempotency key is suffixed with the chunk number after the first chunk.
     *
     * @param citations the citations
     * @param state jurisdiction hint for bare citations, or null
     * @param corpusType corpus hint, or null
     * @param options per-call overrides, or null
     * @return one result per distinct citation, in input order
     */
    public List<StatuteResolveBatchItem> resolveBatchAll(List<String> citations, String state, String corpusType,
            RequestOptions options) {
        List<StatuteResolveBatchItem> results = new ArrayList<StatuteResolveBatchItem>();
        List<List<String>> chunks = Pages.chunks(citations, RESOLVE_BATCH_MAX);
        for (int i = 0; i < chunks.size(); i++) {
            StatuteResolveBatchRequest request = StatuteResolveBatchRequest.builder()
                    .citations(chunks.get(i)).state(state).corpusType(corpusType).build();
            StatuteResolveBatchResponse r = resolveBatch(request, chunkOptions(options, i));
            if (r.getResults() != null) {
                results.addAll(r.getResults());
            }
        }
        return results;
    }

    /**
     * {@link #resolveBatchAll(List, String, String, RequestOptions)} without hints or options.
     *
     * @param citations the citations
     * @return the results
     */
    public List<StatuteResolveBatchItem> resolveBatchAll(List<String> citations) {
        return resolveBatchAll(citations, null, null, null);
    }

    /**
     * Asynchronous form of {@link #resolveBatchAll(List, String, String, RequestOptions)}.
     *
     * @param citations the citations
     * @param state jurisdiction hint, or null
     * @param corpusType corpus hint, or null
     * @param options per-call overrides, or null
     * @return the future results
     */
    public CompletableFuture<List<StatuteResolveBatchItem>> resolveBatchAllAsync(List<String> citations, String state,
            String corpusType, RequestOptions options) {
        return transport.supplyAsync(() -> resolveBatchAll(citations, state, corpusType, options));
    }

    /**
     * Fetches any number of sections by chunking {@link #getSectionsBatch}. Charged.
     *
     * <p>Sends at most {@value #SECTIONS_BATCH_MAX} ids per call. Ids with no match are dropped (use
     * {@code getSectionsBatch} to see {@code notFound}). Spend guard and idempotency behave as in
     * {@link #resolveBatchAll(List, String, String, RequestOptions)}.
     *
     * @param actIds the section ids
     * @param includeBody also return each section's text (the body price applies), or null
     * @param options per-call overrides, or null
     * @return the sections found, in input order
     */
    public List<StatuteResult> getSectionsAll(List<String> actIds, Boolean includeBody, RequestOptions options) {
        List<StatuteResult> sections = new ArrayList<StatuteResult>();
        List<List<String>> chunks = Pages.chunks(actIds, SECTIONS_BATCH_MAX);
        for (int i = 0; i < chunks.size(); i++) {
            StatuteSectionsRequest.Builder b = StatuteSectionsRequest.builder().actIds(chunks.get(i));
            if (includeBody != null) {
                b.includeBody(includeBody);
            }
            StatuteSectionsResponse r = getSectionsBatch(b.build(), chunkOptions(options, i));
            if (r.getSections() != null) {
                sections.addAll(r.getSections());
            }
        }
        return sections;
    }

    /**
     * {@link #getSectionsAll(List, Boolean, RequestOptions)} without the body or options.
     *
     * @param actIds the section ids
     * @return the sections
     */
    public List<StatuteResult> getSectionsAll(List<String> actIds) {
        return getSectionsAll(actIds, null, null);
    }

    /**
     * Asynchronous form of {@link #getSectionsAll(List, Boolean, RequestOptions)}.
     *
     * @param actIds the section ids
     * @param includeBody also return text, or null
     * @param options per-call overrides, or null
     * @return the future sections
     */
    public CompletableFuture<List<StatuteResult>> getSectionsAllAsync(List<String> actIds, Boolean includeBody,
            RequestOptions options) {
        return transport.supplyAsync(() -> getSectionsAll(actIds, includeBody, options));
    }

    static RequestOptions chunkOptions(RequestOptions options, int index) {
        if (options == null || options.getIdempotencyKey() == null || index == 0) {
            return options;
        }
        return options.withIdempotencyKey(IdempotencyKeys.forChunk(options.getIdempotencyKey(), index));
    }
}
