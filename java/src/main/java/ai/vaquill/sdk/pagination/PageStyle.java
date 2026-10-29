package ai.vaquill.sdk.pagination;

import com.fasterxml.jackson.databind.JsonNode;
import java.util.List;
import java.util.Map;

/** Decides the parameters of the next page from the page just read. */
@FunctionalInterface
public interface PageStyle {
    /**
     * Computes the next request parameters.
     *
     * @param params the parameters of the page just fetched
     * @param body the page's JSON body
     * @param items the page's items
     * @return the parameters of the next page, or null when this was the last
     */
    Map<String, Object> next(Map<String, Object> params, JsonNode body, List<JsonNode> items);
}
