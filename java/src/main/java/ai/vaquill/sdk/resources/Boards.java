package ai.vaquill.sdk.resources;

import ai.vaquill.sdk.internal.Transport;
import ai.vaquill.sdk.models.BoardResponse;
import ai.vaquill.sdk.models.ListBoardsParams;
import ai.vaquill.sdk.pagination.PageStyles;
import ai.vaquill.sdk.pagination.Paginator;
import java.util.LinkedHashMap;
import java.util.Map;

/** The sources a watch can follow (free), with an auto-paging iterator. */
public final class Boards extends BoardsBase {
    /**
     * Creates the namespace. Use {@code Vaquill.boards()} instead.
     *
     * @param transport the transport
     */
    public Boards(Transport transport) {
        super(transport);
    }

    /**
     * Iterates every board across pages (free; page size defaults to 500).
     *
     * @param params optional filters, or null
     * @return the paginator
     */
    public Paginator<BoardResponse> iterList(ListBoardsParams params) {
        Map<String, Object> q = Pages.merge(new LinkedHashMap<String, Object>(), params == null ? null : params.toQuery());
        q.putIfAbsent("limit", 500L);
        q.putIfAbsent("offset", 0L);
        return Paginator.of(Pages.get(transport, "/api/v1/boards", false, true), PageStyles.hasMoreOffset(),
                "boards", q, Pages.parser(BoardResponse.class), transport.executor());
    }
}
