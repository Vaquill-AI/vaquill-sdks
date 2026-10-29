package vaquill

import (
	"context"
	"encoding/json"
	"iter"
	"reflect"
)

// WARNING: on charged endpoints every page spends credits. Iterating a whole result set can
// cost far more than one call. Always set WithMaxPages or WithMaxItems unless you intend to
// read everything. When a guard stops iteration early, Truncated reports true (including a
// WithMaxItems that cut items off the last page). When the server repeats the offset or cursor it
// was just sent, or answers an empty page with hasMore true, iteration stops and Stuck reports
// true, rather than looping and spending credits on the same page.

type pageConfig struct {
	maxPages *int
	maxItems *int
	call     []CallOption
}

// PageOption configures an iterator.
type PageOption func(*pageConfig)

// WithMaxPages stops iteration after n pages.
func WithMaxPages(n int) PageOption { return func(c *pageConfig) { c.maxPages = &n } }

// WithMaxItems stops iteration after n items, cutting the last page if needed.
func WithMaxItems(n int) PageOption { return func(c *pageConfig) { c.maxItems = &n } }

// WithPageCallOptions applies call options (timeout, retries, headers) to every page request.
// A fixed WithIdempotencyKey is suffixed per page, because every page has a different request.
func WithPageCallOptions(opts ...CallOption) PageOption {
	return func(c *pageConfig) { c.call = append(c.call, opts...) }
}

func newPageConfig(opts []PageOption) *pageConfig {
	c := &pageConfig{}
	for _, o := range opts {
		if o != nil {
			o(c)
		}
	}
	return c
}

type pageStyle interface {
	// next returns the params for the next page, or nil when this was the last.
	next(params, body map[string]any, items []any) map[string]any
}

func withParam(params map[string]any, k string, v any) map[string]any {
	out := make(map[string]any, len(params)+1)
	for pk, pv := range params {
		out[pk] = pv
	}
	out[k] = v
	return out
}

func asInt(v any) (int64, bool) {
	switch x := v.(type) {
	case int64:
		return x, true
	case int:
		return int64(x), true
	case float64:
		if x == float64(int64(x)) {
			return int64(x), true
		}
	case json.Number:
		i, err := x.Int64()
		return i, err == nil
	}
	return 0, false
}

// offsetStyle: "offset" request param, "nextOffset" response member (null on the last page).
type offsetStyle struct{ param, nextKey string }

func (s offsetStyle) next(params, body map[string]any, _ []any) map[string]any {
	if body[s.nextKey] == nil {
		return nil
	}
	return withParam(params, s.param, body[s.nextKey])
}

// cursorStyle: opaque "cursor" request param, "nextCursor" response member.
type cursorStyle struct{}

func (cursorStyle) next(params, body map[string]any, _ []any) map[string]any {
	if s, _ := body["nextCursor"].(string); s != "" {
		return withParam(params, "cursor", s)
	}
	return nil
}

// idWindowStyle: sinceId (forward) or beforeId (back) from the last item's id. Stops on an empty
// page, or a short page when limit is set.
type idWindowStyle struct{ param string }

func (s idWindowStyle) next(params, _ map[string]any, items []any) map[string]any {
	if len(items) == 0 {
		return nil
	}
	if limit, ok := asInt(params["limit"]); ok && int64(len(items)) < limit {
		return nil
	}
	last, _ := items[len(items)-1].(map[string]any)
	id := last["id"]
	if id == nil {
		return nil
	}
	return withParam(params, s.param, id)
}

// hasMoreOffset: offset paging for responses with hasMore but no nextOffset.
type hasMoreOffset struct{}

func (hasMoreOffset) next(params, body map[string]any, items []any) map[string]any {
	more, ok := body["hasMore"].(bool)
	if !ok {
		limit, _ := asInt(params["limit"])
		more = limit > 0 && int64(len(items)) >= limit
	}
	if !more || len(items) == 0 {
		return nil
	}
	off, _ := asInt(params["offset"])
	return withParam(params, "offset", off+int64(len(items)))
}

// nextOffsetOrHasMore follows nextOffset when the server gives one (Boolean search) and otherwise
// steps by the rows returned while hasMore is true (hybrid search).
type nextOffsetOrHasMore struct{}

func (nextOffsetOrHasMore) next(params, body map[string]any, items []any) map[string]any {
	if body["nextOffset"] != nil {
		return withParam(params, "offset", body["nextOffset"])
	}
	if more, _ := body["hasMore"].(bool); more && len(items) > 0 {
		off, _ := asInt(params["offset"])
		return withParam(params, "offset", off+int64(len(items)))
	}
	return nil
}

// hasMoreID: sinceId / beforeId paging that also stops when the server says hasMore false.
type hasMoreID struct{ param string }

func (s hasMoreID) next(params, body map[string]any, items []any) map[string]any {
	if more, ok := body["hasMore"].(bool); ok && !more {
		return nil
	}
	return idWindowStyle(s).next(params, body, items)
}

// hasMoreCursor: cursor paging that stops when hasMore is false or pageEnd reaches totalChars.
// Later pages are addressed by the cursor alone, so startChar is dropped after the first page.
type hasMoreCursor struct{}

func (hasMoreCursor) next(params, body map[string]any, _ []any) map[string]any {
	nxt, _ := body["nextCursor"].(string)
	if nxt == "" {
		return nil
	}
	if more, ok := body["hasMore"].(bool); ok && !more {
		return nil
	}
	end, eok := asInt(body["pageEnd"])
	total, tok := asInt(body["totalChars"])
	if eok && tok && end >= total {
		return nil
	}
	out := make(map[string]any, len(params))
	for k, v := range params {
		if k != "startChar" {
			out[k] = v
		}
	}
	out["cursor"] = nxt
	return out
}

// Paginator walks the pages of a list endpoint. Range over All for items or Pages for whole
// pages. A Paginator is single use and not safe for concurrent iteration.
type Paginator[T any] struct {
	fetch    func(map[string]any) (map[string]any, error)
	style    pageStyle
	itemsKey string // empty: the whole body is the one item
	params   map[string]any
	cfg      *pageConfig
	logger   Logger

	pages, count     int
	truncated, stuck bool
}

func newPaginator[T any](c *Client, cfg *pageConfig, itemsKey string, style pageStyle, params map[string]any, fetch func(map[string]any) (map[string]any, error)) *Paginator[T] {
	return &Paginator[T]{fetch: fetch, style: style, itemsKey: itemsKey, params: params, cfg: cfg, logger: c.logger}
}

// Truncated reports that a page or item guard stopped iteration while more existed.
func (p *Paginator[T]) Truncated() bool { return p.truncated }

// Stuck reports that iteration stopped because the server repeated its paging position.
func (p *Paginator[T]) Stuck() bool { return p.stuck }

// Pages yields one slice per fetched page. On a request or decoding error it yields the error
// once and stops.
func (p *Paginator[T]) Pages() iter.Seq2[[]T, error] {
	return func(yield func([]T, error) bool) {
		for !p.exhausted() {
			body, err := p.fetch(copyParams(p.params))
			if err != nil {
				yield(nil, err)
				return
			}
			items, err := p.take(body)
			if err != nil {
				yield(nil, err)
				return
			}
			if !yield(items, nil) {
				return
			}
		}
	}
}

// All yields every item across pages.
func (p *Paginator[T]) All() iter.Seq2[T, error] {
	return func(yield func(T, error) bool) {
		for page, err := range p.Pages() {
			if err != nil {
				var zero T
				yield(zero, err)
				return
			}
			for _, it := range page {
				if !yield(it, nil) {
					return
				}
			}
		}
	}
}

// Collect reads every item into a slice. The guards still apply.
func (p *Paginator[T]) Collect() ([]T, error) {
	var out []T
	for it, err := range p.All() {
		if err != nil {
			return out, err
		}
		out = append(out, it)
	}
	return out, nil
}

func copyParams(m map[string]any) map[string]any {
	out := make(map[string]any, len(m))
	for k, v := range m {
		out[k] = v
	}
	return out
}

// exhausted reports whether a guard forbids fetching another page, marking truncated if more existed.
func (p *Paginator[T]) exhausted() bool {
	if p.params == nil {
		return true
	}
	if (p.cfg.maxPages != nil && p.pages >= *p.cfg.maxPages) || (p.cfg.maxItems != nil && p.count >= *p.cfg.maxItems) {
		p.truncated = true
		return true
	}
	return false
}

func (p *Paginator[T]) take(body map[string]any) ([]T, error) {
	var raw []any
	if p.itemsKey == "" {
		raw = []any{body}
	} else if l, ok := body[p.itemsKey].([]any); ok {
		raw = l
	}
	used := p.params
	if more, _ := body["hasMore"].(bool); len(raw) == 0 && more {
		p.params = nil
		p.markStuck("an empty page with hasMore true")
	} else {
		p.params = p.style.next(used, body, raw)
		if p.params != nil && reflect.DeepEqual(p.params, used) {
			p.params = nil
			p.markStuck("the offset or cursor it was just sent")
		}
	}
	p.pages++
	if p.cfg.maxItems != nil && len(raw) > *p.cfg.maxItems-p.count {
		keep := *p.cfg.maxItems - p.count
		if keep < 0 {
			keep = 0
		}
		raw = raw[:keep]
		p.truncated = true
	}
	p.count += len(raw)
	out := make([]T, 0, len(raw))
	for _, r := range raw {
		b, err := json.Marshal(r)
		if err != nil {
			return nil, &ResponseParseError{Message: "page item could not be re-encoded: " + err.Error(), Cause: err}
		}
		var it T
		if err := json.Unmarshal(b, &it); err != nil {
			return nil, &ResponseParseError{Message: "page item did not match the expected shape: " + err.Error(), Cause: err}
		}
		out = append(out, it)
	}
	return out, nil
}

func (p *Paginator[T]) markStuck(what string) {
	p.stuck = true
	p.logger.Warn("Pagination stopped: the server answered " + what + ". Not fetching again.")
}

// pageFetch builds the per-page request function. GET pages send params as the query, POST
// pages as the JSON body. unwrap reads the page from the envelope's "data" member.
func (c *Client) pageFetch(ctx context.Context, method, path string, charged, unwrap bool, cfg *pageConfig) func(map[string]any) (map[string]any, error) {
	n := 0
	return func(params map[string]any) (map[string]any, error) {
		r := request{op: "page", method: method, path: path, charged: charged}
		if method == "GET" {
			r.query = encodeQuery(params)
		} else {
			r.body = params
		}
		var rb rawBody
		opts := chunkOptions(cfg.call, n)
		n++
		if err := c.do(ctx, r, &rb, opts); err != nil {
			return nil, err
		}
		var body map[string]any
		if err := decodeNormalized(rb, &body); err != nil || body == nil {
			return nil, &ResponseParseError{Message: "page was not a JSON object", Cause: err}
		}
		if unwrap {
			data, ok := body["data"].(map[string]any)
			if !ok {
				return nil, &ResponseParseError{Message: "page envelope has no data object"}
			}
			return data, nil
		}
		return body, nil
	}
}
