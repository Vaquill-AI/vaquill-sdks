package ai.vaquill.sdk.resources;

import ai.vaquill.sdk.internal.Paths;
import ai.vaquill.sdk.internal.Transport;
import ai.vaquill.sdk.models.ChangeResponse;
import ai.vaquill.sdk.models.ListWatchChangesParams;
import ai.vaquill.sdk.models.ListWatchesParams;
import ai.vaquill.sdk.models.WatchResponse;
import ai.vaquill.sdk.pagination.PageStyles;
import ai.vaquill.sdk.pagination.Paginator;
import java.util.LinkedHashMap;
import java.util.Map;

/** Law-change watches (free), with auto-paging iterators. */
public final class Watches extends WatchesBase {
    /**
     * Creates the namespace. Use {@code Vaquill.watches()} instead.
     *
     * @param transport the transport
     */
    public Watches(Transport transport) {
        super(transport);
    }

    /**
     * Iterates all your watches across pages (free; page size defaults to 100).
     *
     * @param params optional paging parameters, or null
     * @return the paginator
     */
    public Paginator<WatchResponse> iterList(ListWatchesParams params) {
        Map<String, Object> q = Pages.merge(new LinkedHashMap<String, Object>(), params == null ? null : params.toQuery());
        q.putIfAbsent("limit", 100L);
        q.putIfAbsent("offset", 0L);
        return Paginator.of(Pages.get(transport, "/api/v1/watches", false, true), PageStyles.hasMoreOffset(),
                "watches", q, Pages.parser(WatchResponse.class), transport.executor());
    }

    /**
     * Iterates a watch's changes across pages (free): newest first, or oldest first with {@code order=asc}.
     *
     * @param watchId the watch id
     * @param params optional filters (limit defaults to 50), or null
     * @return the paginator
     */
    public Paginator<ChangeResponse> iterChanges(String watchId, ListWatchChangesParams params) {
        Map<String, Object> q = Pages.merge(new LinkedHashMap<String, Object>(), params == null ? null : params.toQuery());
        q.putIfAbsent("limit", 50L);
        q.putIfAbsent("order", "desc");
        String style = "asc".equals(q.get("order")) ? "sinceId" : "beforeId";
        return Paginator.of(Pages.get(transport, "/api/v1/watches/" + Paths.seg(watchId) + "/changes", false, true),
                PageStyles.hasMoreId(style), "changes", q, Pages.parser(ChangeResponse.class), transport.executor());
    }
}
