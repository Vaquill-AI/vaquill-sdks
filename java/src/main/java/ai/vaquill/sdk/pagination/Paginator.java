package ai.vaquill.sdk.pagination;

import com.fasterxml.jackson.databind.JsonNode;
import java.lang.System.Logger.Level;
import java.util.ArrayList;
import java.util.Collections;
import java.util.Iterator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.NoSuchElementException;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.Executor;
import java.util.function.Function;
import java.util.stream.Stream;
import java.util.stream.StreamSupport;

/**
 * Auto-paging iterator over offset, cursor and id-window list endpoints. Iterate it for items, call
 * {@link #pages()} for whole pages, or use {@link #stream()}.
 *
 * <p><b>WARNING:</b> on charged endpoints every page spends credits. Iterating a whole result set
 * can cost far more than one call, so set {@link #maxPages(int)} or {@link #maxItems(int)} unless you
 * intend to read everything. When a guard stops iteration early, {@link #isTruncated()} is true (this
 * includes a {@code maxItems} that cut items off the last page). When the server repeats the offset or
 * cursor it was just sent, or answers an empty page with {@code hasMore: true}, iteration stops and
 * {@link #isStuck()} is true, rather than looping and spending credits on the same page.
 *
 * <p>A paginator is single use and not thread safe.
 *
 * @param <T> the item type
 */
public final class Paginator<T> implements Iterable<T> {
    private static final System.Logger LOG = System.getLogger("ai.vaquill.sdk");

    private final Function<Map<String, Object>, JsonNode> fetch;
    private final PageStyle style;
    private final Function<JsonNode, List<JsonNode>> itemsOf;
    private final Function<JsonNode, T> parse;
    private final Executor executor;

    private Map<String, Object> params;
    private Integer maxPages;
    private Integer maxItems;
    private int pagesRead;
    private long count;
    private boolean truncated;
    private boolean stuck;

    private Paginator(Function<Map<String, Object>, JsonNode> fetch, PageStyle style,
            Function<JsonNode, List<JsonNode>> itemsOf, Map<String, Object> params,
            Function<JsonNode, T> parse, Executor executor) {
        this.fetch = fetch;
        this.style = style;
        this.itemsOf = itemsOf;
        this.parse = parse;
        this.executor = executor;
        Map<String, Object> start = new LinkedHashMap<String, Object>();
        for (Map.Entry<String, Object> e : params.entrySet()) {
            if (e.getValue() != null) {
                start.put(e.getKey(), e.getValue() instanceof Number && !(e.getValue() instanceof Double)
                        ? Long.valueOf(((Number) e.getValue()).longValue()) : e.getValue());
            }
        }
        this.params = start;
    }

    /**
     * Creates a paginator over a list member of each page. Used by the resource classes.
     *
     * @param <T> the item type
     * @param fetch fetches one page given its parameters (wire names)
     * @param style how to find the next page
     * @param itemsKey the response member holding the page's items
     * @param params the first page's parameters
     * @param parse converts one item to {@code T}
     * @param executor runs {@link #toListAsync()}
     * @return the paginator
     */
    public static <T> Paginator<T> of(Function<Map<String, Object>, JsonNode> fetch, PageStyle style,
            final String itemsKey, Map<String, Object> params, Function<JsonNode, T> parse, Executor executor) {
        return new Paginator<T>(fetch, style, body -> {
            JsonNode arr = body.get(itemsKey);
            List<JsonNode> out = new ArrayList<JsonNode>();
            if (arr != null && arr.isArray()) {
                for (JsonNode n : arr) {
                    out.add(n);
                }
            }
            return out;
        }, params, parse, executor);
    }

    /**
     * Creates a paginator whose single "item" per page is the whole page (used to read a long text).
     *
     * @param <T> the page type
     * @param fetch fetches one page
     * @param style how to find the next page
     * @param params the first page's parameters
     * @param parse converts a page to {@code T}
     * @param executor runs {@link #toListAsync()}
     * @return the paginator
     */
    public static <T> Paginator<T> ofPages(Function<Map<String, Object>, JsonNode> fetch, PageStyle style,
            Map<String, Object> params, Function<JsonNode, T> parse, Executor executor) {
        return new Paginator<T>(fetch, style, body -> Collections.singletonList(body), params, parse, executor);
    }

    /**
     * Stops after this many pages. Set before iterating.
     *
     * @param pages at least 1
     * @return this
     */
    public Paginator<T> maxPages(int pages) {
        if (pages < 1) {
            throw new IllegalArgumentException("maxPages must be at least 1.");
        }
        requireFresh();
        this.maxPages = pages;
        return this;
    }

    /**
     * Stops after this many items. Set before iterating.
     *
     * @param items at least 1
     * @return this
     */
    public Paginator<T> maxItems(int items) {
        if (items < 1) {
            throw new IllegalArgumentException("maxItems must be at least 1.");
        }
        requireFresh();
        this.maxItems = items;
        return this;
    }

    private void requireFresh() {
        if (pagesRead > 0) {
            throw new IllegalStateException("Set guards before iteration starts.");
        }
    }

    /** @return true when a guard left rows unread */
    public boolean isTruncated() {
        return truncated;
    }

    /** @return true when iteration stopped because the server repeated its paging position */
    public boolean isStuck() {
        return stuck;
    }

    /** @return the number of pages fetched so far */
    public int getPagesRead() {
        return pagesRead;
    }

    private boolean exhausted() {
        if (params == null) {
            return true;
        }
        if ((maxPages != null && pagesRead >= maxPages) || (maxItems != null && count >= maxItems)) {
            truncated = true;
            return true;
        }
        return false;
    }

    private List<T> take() {
        Map<String, Object> used = params;
        JsonNode body = fetch.apply(new LinkedHashMap<String, Object>(used));
        if (body == null || !body.isObject()) {
            params = null;
            pagesRead++;
            return Collections.emptyList();
        }
        List<JsonNode> raw = itemsOf.apply(body);
        JsonNode more = body.get("hasMore");
        if (raw.isEmpty() && more != null && more.isBoolean() && more.asBoolean()) {
            params = null;
            markStuck("an empty page with hasMore true");
        } else {
            params = style.next(used, body, raw);
            if (params != null && params.equals(used)) {
                params = null;
                markStuck("the offset or cursor it was just sent");
            }
        }
        pagesRead++;
        if (maxItems != null && raw.size() > maxItems - count) {
            raw = new ArrayList<JsonNode>(raw.subList(0, (int) (maxItems - count)));
            truncated = true;
        }
        count += raw.size();
        List<T> out = new ArrayList<T>(raw.size());
        for (JsonNode n : raw) {
            out.add(parse.apply(n));
        }
        return out;
    }

    private void markStuck(String what) {
        stuck = true;
        LOG.log(Level.WARNING, "Pagination stopped: the server answered " + what + ". Not fetching again.");
    }

    /**
     * Iterates whole pages, fetching lazily; use this to control cost.
     *
     * @return the pages
     */
    public Iterable<List<T>> pages() {
        return () -> new Iterator<List<T>>() {
            @Override
            public boolean hasNext() {
                return !exhausted();
            }

            @Override
            public List<T> next() {
                if (exhausted()) {
                    throw new NoSuchElementException();
                }
                return take();
            }
        };
    }

    @Override
    public Iterator<T> iterator() {
        final Iterator<List<T>> pageIt = pages().iterator();
        return new Iterator<T>() {
            private Iterator<T> current = Collections.<T>emptyList().iterator();

            @Override
            public boolean hasNext() {
                while (!current.hasNext() && pageIt.hasNext()) {
                    current = pageIt.next().iterator();
                }
                return current.hasNext();
            }

            @Override
            public T next() {
                if (!hasNext()) {
                    throw new NoSuchElementException();
                }
                return current.next();
            }
        };
    }

    /** @return a sequential stream of items; pages are fetched lazily as the stream is consumed */
    public Stream<T> stream() {
        return StreamSupport.stream(spliterator(), false);
    }

    /**
     * Reads everything the guards allow.
     *
     * @return all items
     */
    public List<T> toList() {
        List<T> out = new ArrayList<T>();
        for (T t : this) {
            out.add(t);
        }
        return out;
    }

    /** @return a future for {@link #toList()}, run on the SDK's executor */
    public CompletableFuture<List<T>> toListAsync() {
        return CompletableFuture.supplyAsync(this::toList, executor);
    }
}
