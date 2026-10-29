package ai.vaquill.sdk.resources;

import ai.vaquill.sdk.RequestOptions;
import ai.vaquill.sdk.internal.Paths;
import ai.vaquill.sdk.internal.Transport;
import ai.vaquill.sdk.models.GetSessionLawBodyParams;
import ai.vaquill.sdk.models.GetSessionLawChangesParams;
import ai.vaquill.sdk.models.ListSessionLawsParams;
import ai.vaquill.sdk.models.SessionLawBatchLaw;
import ai.vaquill.sdk.models.SessionLawBatchRequest;
import ai.vaquill.sdk.models.SessionLawBatchResponse;
import ai.vaquill.sdk.models.SessionLawBodyResponse;
import ai.vaquill.sdk.models.SessionLawChange;
import ai.vaquill.sdk.models.SessionLawSearchRequest;
import ai.vaquill.sdk.models.SessionLawSearchResult;
import ai.vaquill.sdk.models.SessionLawSummary;
import ai.vaquill.sdk.pagination.PageStyles;
import ai.vaquill.sdk.pagination.Paginator;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.CompletableFuture;

/**
 * US session laws (acts as enacted), with auto-paging iterators ({@link #iterSearch}, {@link #iterList},
 * {@link #iterChanges}, {@link #iterBody}) and the chunking {@link #getBatchAll}. Every page is charged.
 */
public final class SessionLaws extends SessionLawsBase {
    /** Ids per call of {@code POST /us/session-laws/batch} (the spec's cap). */
    public static final int BATCH_MAX = 200;

    /**
     * Creates the namespace. Use {@code Vaquill.sessionLaws()} instead.
     *
     * @param transport the transport
     */
    public SessionLaws(Transport transport) {
        super(transport);
    }

    /**
     * Iterates search results across pages (page size defaults to 10).
     *
     * @param request the search
     * @return the paginator
     */
    public Paginator<SessionLawSearchResult> iterSearch(SessionLawSearchRequest request) {
        Map<String, Object> params = Pages.wire(request);
        params.putIfAbsent("limit", 10L);
        params.putIfAbsent("offset", 0L);
        return Paginator.of(Pages.post(transport, "/api/v1/us/session-laws/search"), PageStyles.hasMoreOffset(),
                "results", params, Pages.parser(SessionLawSearchResult.class), transport.executor());
    }

    /**
     * Iterates {@link #list} across pages with the {@code nextCursor}.
     *
     * @param jurisdiction the state code (required)
     * @param params optional filters, or null
     * @return the paginator
     */
    public Paginator<SessionLawSummary> iterList(String jurisdiction, ListSessionLawsParams params) {
        Map<String, Object> q = new LinkedHashMap<String, Object>();
        q.put("jurisdiction", jurisdiction);
        q = Pages.merge(q, params == null ? null : params.toQuery());
        return Paginator.of(Pages.get(transport, "/api/v1/us/session-laws/list", true, false), PageStyles.cursor(),
                "results", q, Pages.parser(SessionLawSummary.class), transport.executor());
    }

    /**
     * Iterates changes forward from {@code sinceId} (default 0; page size defaults to 50).
     *
     * @param params optional filters, or null
     * @return the paginator
     */
    public Paginator<SessionLawChange> iterChanges(GetSessionLawChangesParams params) {
        Map<String, Object> q = Pages.merge(new LinkedHashMap<String, Object>(), params == null ? null : params.toQuery());
        q.putIfAbsent("sinceId", 0L);
        q.putIfAbsent("limit", 50L);
        return Paginator.of(Pages.get(transport, "/api/v1/us/session-laws/changes", true, false),
                PageStyles.hasMoreId("sinceId"), "changes", q, Pages.parser(SessionLawChange.class), transport.executor());
    }

    /**
     * Reads a law's text page by page, following {@code nextCursor} until {@code hasMore} is false.
     * Yields one {@link SessionLawBodyResponse} per page; concatenate their {@code text}. Every page is
     * charged: a long act is hundreds of pages, so call {@code maxPages}. Stops when {@code hasMore} is
     * false, {@code pageEnd} reaches {@code totalChars}, or the cursor stops advancing.
     *
     * @param sessionLawId the id
     * @param params optional start character, version and so on, or null
     * @return the paginator of pages
     */
    public Paginator<SessionLawBodyResponse> iterBody(String sessionLawId, GetSessionLawBodyParams params) {
        Map<String, Object> q = Pages.merge(new LinkedHashMap<String, Object>(), params == null ? null : params.toQuery());
        return Paginator.ofPages(
                Pages.get(transport, "/api/v1/us/session-laws/" + Paths.seg(sessionLawId) + "/body", true, false),
                PageStyles.bodyCursor(), q, Pages.parser(SessionLawBodyResponse.class), transport.executor());
    }

    /**
     * Fetches any number of session laws by chunking {@link #getBatch}. Charged.
     *
     * <p>Sends at most {@value #BATCH_MAX} ids per call. Ids with no match are dropped (use
     * {@code getBatch} to see {@code notFound}). Spend guard and idempotency behave as in
     * {@link Statutes#resolveBatchAll(List, String, String, RequestOptions)}.
     *
     * @param ids session law ids or citations
     * @param jurisdiction default state for citations, or null
     * @param includeBody include the text of each law, or null
     * @param options per-call overrides, or null
     * @return the laws found, in input order
     */
    public List<SessionLawBatchLaw> getBatchAll(List<String> ids, String jurisdiction, Boolean includeBody,
            RequestOptions options) {
        List<SessionLawBatchLaw> laws = new ArrayList<SessionLawBatchLaw>();
        List<List<String>> chunks = Pages.chunks(ids, BATCH_MAX);
        for (int i = 0; i < chunks.size(); i++) {
            SessionLawBatchRequest.Builder b = SessionLawBatchRequest.builder().ids(chunks.get(i)).jurisdiction(jurisdiction);
            if (includeBody != null) {
                b.includeBody(includeBody);
            }
            SessionLawBatchResponse r = getBatch(b.build(), Statutes.chunkOptions(options, i));
            if (r.getLaws() != null) {
                laws.addAll(r.getLaws());
            }
        }
        return laws;
    }

    /**
     * {@link #getBatchAll(List, String, Boolean, RequestOptions)} with no hints or options.
     *
     * @param ids session law ids or citations
     * @return the laws
     */
    public List<SessionLawBatchLaw> getBatchAll(List<String> ids) {
        return getBatchAll(ids, null, null, null);
    }

    /**
     * Asynchronous form of {@link #getBatchAll(List, String, Boolean, RequestOptions)}.
     *
     * @param ids session law ids or citations
     * @param jurisdiction default state, or null
     * @param includeBody include text, or null
     * @param options per-call overrides, or null
     * @return the future laws
     */
    public CompletableFuture<List<SessionLawBatchLaw>> getBatchAllAsync(List<String> ids, String jurisdiction,
            Boolean includeBody, RequestOptions options) {
        return transport.supplyAsync(() -> getBatchAll(ids, jurisdiction, includeBody, options));
    }
}
