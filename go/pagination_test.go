package vaquill

import (
	"context"
	"errors"
	"fmt"
	"net/http"
	"strings"
	"testing"
)

func TestStylesNext(t *testing.T) {
	p := func(kv ...any) map[string]any {
		m := map[string]any{}
		for i := 0; i < len(kv); i += 2 {
			m[kv[i].(string)] = kv[i+1]
		}
		return m
	}
	items := func(ids ...int64) []any {
		var out []any
		for _, id := range ids {
			out = append(out, map[string]any{"id": id})
		}
		return out
	}
	cases := []struct {
		name   string
		style  pageStyle
		params map[string]any
		body   map[string]any
		items  []any
		want   map[string]any
	}{
		{"offset next", offsetStyle{"offset", "nextOffset"}, p("offset", int64(0)), p("nextOffset", int64(10)), nil, p("offset", int64(10))},
		{"offset last", offsetStyle{"offset", "nextOffset"}, p("offset", int64(0)), p("nextOffset", nil), nil, nil},
		{"cursor next", cursorStyle{}, p("a", "b"), p("nextCursor", "c2"), nil, p("a", "b", "cursor", "c2")},
		{"cursor empty", cursorStyle{}, p(), p("nextCursor", ""), nil, nil},
		{"cursor null", cursorStyle{}, p(), p("nextCursor", nil), nil, nil},
		{"id back", idWindowStyle{"beforeId"}, p("limit", int64(2)), p(), items(9, 7), p("limit", int64(2), "beforeId", int64(7))},
		{"id short page", idWindowStyle{"beforeId"}, p("limit", int64(3)), p(), items(9, 7), nil},
		{"id empty", idWindowStyle{"sinceId"}, p(), p(), nil, nil},
		{"id no limit", idWindowStyle{"sinceId"}, p(), p(), items(4), p("sinceId", int64(4))},
		{"id missing", idWindowStyle{"sinceId"}, p(), p(), []any{map[string]any{}}, nil},
		{"hasMoreOffset flag", hasMoreOffset{}, p("offset", int64(5), "limit", int64(2)), p("hasMore", true), items(1, 2), p("offset", int64(7), "limit", int64(2))},
		{"hasMoreOffset false", hasMoreOffset{}, p("offset", int64(5)), p("hasMore", false), items(1), nil},
		{"hasMoreOffset no flag full", hasMoreOffset{}, p("limit", int64(2)), p(), items(1, 2), p("limit", int64(2), "offset", int64(2))},
		{"hasMoreOffset no flag short", hasMoreOffset{}, p("limit", int64(3)), p(), items(1, 2), nil},
		{"hasMoreOffset empty", hasMoreOffset{}, p(), p("hasMore", true), nil, nil},
		{"nextOffset wins", nextOffsetOrHasMore{}, p("offset", int64(0)), p("nextOffset", int64(20), "hasMore", true), items(1), p("offset", int64(20))},
		{"hasMore steps", nextOffsetOrHasMore{}, p("offset", int64(10)), p("nextOffset", nil, "hasMore", true), items(1, 2, 3), p("offset", int64(13))},
		{"hybrid last", nextOffsetOrHasMore{}, p("offset", int64(0)), p("hasMore", false), items(1), nil},
		{"hasMoreID stops", hasMoreID{"sinceId"}, p("limit", int64(1)), p("hasMore", false), items(1), nil},
		{"hasMoreID goes", hasMoreID{"sinceId"}, p("limit", int64(1)), p("hasMore", true), items(5), p("limit", int64(1), "sinceId", int64(5))},
		{"body cursor", hasMoreCursor{}, p("startChar", int64(0), "version", int64(2)), p("nextCursor", "n", "hasMore", true, "pageEnd", int64(10), "totalChars", int64(50)), nil, p("version", int64(2), "cursor", "n")},
		{"body last page", hasMoreCursor{}, p(), p("nextCursor", "n", "pageEnd", int64(50), "totalChars", int64(50)), nil, nil},
		{"body hasMore false", hasMoreCursor{}, p(), p("nextCursor", "n", "hasMore", false), nil, nil},
		{"body no cursor", hasMoreCursor{}, p(), p("hasMore", true), nil, nil},
	}
	for _, tc := range cases {
		got := tc.style.next(tc.params, tc.body, tc.items)
		if fmt.Sprint(got) != fmt.Sprint(tc.want) {
			t.Errorf("%s: got %v want %v", tc.name, got, tc.want)
		}
	}
}

// searchServer pages a fixed result set through "offset" with hasMore and no nextOffset.
func searchServer(t *testing.T, total, perPage int) *fake {
	var f *fake
	f = newFake(t, func(w http.ResponseWriter, r *http.Request, n int) {
		var req struct {
			Offset int `json:"offset"`
		}
		_ = jsonUnmarshal([]byte(f.requests()[n-1].Body), &req)
		end := req.Offset + perPage
		if end > total {
			end = total
		}
		var rows []string
		for i := req.Offset; i < end; i++ {
			rows = append(rows, fmt.Sprintf(`{"actId":"A%d"}`, i))
		}
		w.Header().Set("Content-Type", "application/json")
		_, _ = fmt.Fprintf(w, `{"results":[%s],"hasMore":%v,"nextOffset":null,"creditsConsumed":1}`, strings.Join(rows, ","), end < total)
	})
	return f
}

func TestIterSearchWalksAllPages(t *testing.T) {
	f := searchServer(t, 25, 10)
	c, _ := newTestClient(t, f)
	p, err := c.Statutes.IterSearch(context.Background(), &StatuteSearchRequest{Query: "x"})
	if err != nil {
		t.Fatal(err)
	}
	var ids []string
	for it, err := range p.All() {
		if err != nil {
			t.Fatal(err)
		}
		ids = append(ids, it.ActID)
	}
	if len(ids) != 25 || ids[24] != "A24" || p.Truncated() || p.Stuck() {
		t.Errorf("ids=%d truncated=%v stuck=%v", len(ids), p.Truncated(), p.Stuck())
	}
	if len(f.requests()) != 3 || c.CreditsSpent() != 3 {
		t.Errorf("requests=%d spent=%v", len(f.requests()), c.CreditsSpent())
	}
	keys := map[string]bool{}
	for _, r := range f.requests() {
		keys[r.Header.Get("Idempotency-Key")] = true
	}
	if len(keys) != 3 {
		t.Error("each page is its own charged call with its own key")
	}
}

func TestIterSearchGuards(t *testing.T) {
	f := searchServer(t, 25, 10)
	c, _ := newTestClient(t, f)
	ctx := context.Background()

	p, _ := c.Statutes.IterSearch(ctx, &StatuteSearchRequest{Query: "x"}, WithMaxPages(2))
	got, err := p.Collect()
	if err != nil || len(got) != 20 || !p.Truncated() {
		t.Errorf("max pages: n=%d truncated=%v err=%v", len(got), p.Truncated(), err)
	}

	p, _ = c.Statutes.IterSearch(ctx, &StatuteSearchRequest{Query: "x"}, WithMaxItems(15))
	got, _ = p.Collect()
	if len(got) != 15 || !p.Truncated() {
		t.Errorf("max items: n=%d truncated=%v", len(got), p.Truncated())
	}

	before := len(f.requests())
	p, _ = c.Statutes.IterSearch(ctx, &StatuteSearchRequest{Query: "x"}, WithMaxPages(0))
	got, _ = p.Collect()
	if len(got) != 0 || !p.Truncated() || len(f.requests()) != before {
		t.Error("zero pages must fetch nothing")
	}

	// Items fit exactly: no truncation flagged when the guard is not what ended the walk.
	p, _ = c.Statutes.IterSearch(ctx, &StatuteSearchRequest{Query: "x"}, WithMaxItems(25))
	got, _ = p.Collect()
	if len(got) != 25 || p.Truncated() {
		t.Errorf("exact fit: n=%d truncated=%v", len(got), p.Truncated())
	}

	// Pages() yields whole pages, and breaking early stops fetching.
	before = len(f.requests())
	p, _ = c.Statutes.IterSearch(ctx, &StatuteSearchRequest{Query: "x"})
	for page, err := range p.Pages() {
		if err != nil || len(page) != 10 {
			t.Fatalf("page=%d err=%v", len(page), err)
		}
		break
	}
	if len(f.requests())-before != 1 {
		t.Error("breaking out of Pages must stop fetching")
	}
	if _, err := c.Statutes.IterSearch(ctx, nil); err == nil {
		t.Error("nil request")
	}
}

func TestStuckOnRepeatedOffsetAndEmptyHasMore(t *testing.T) {
	f := newFake(t, func(w http.ResponseWriter, r *http.Request, n int) {
		writeJSON(w, 200, `{"results":[{"actId":"A"}],"hasMore":true,"nextOffset":0}`)
	})
	c, _ := newTestClient(t, f)
	p, _ := c.Statutes.IterSearch(context.Background(), &StatuteSearchRequest{Query: "x"})
	got, err := p.Collect()
	if err != nil || len(got) != 1 || !p.Stuck() || len(f.requests()) != 1 {
		t.Errorf("repeat offset: n=%d stuck=%v requests=%d err=%v", len(got), p.Stuck(), len(f.requests()), err)
	}
	lg := &memLogger{}
	c2, _ := newTestClient(t, newFake(t, func(w http.ResponseWriter, r *http.Request, n int) {
		writeJSON(w, 200, `{"results":[],"hasMore":true}`)
	}), WithLogger(lg))
	p, _ = c2.Statutes.IterSearch(context.Background(), &StatuteSearchRequest{Query: "x"})
	got, _ = p.Collect()
	if len(got) != 0 || !p.Stuck() {
		t.Errorf("empty+hasMore: n=%d stuck=%v", len(got), p.Stuck())
	}
	contains(t, lg.text(), "Pagination stopped")
}

func TestPaginationErrorsSurfaceOnce(t *testing.T) {
	f := newFake(t, func(w http.ResponseWriter, r *http.Request, n int) {
		if n == 2 {
			writeJSON(w, 404, `{"detail":"gone"}`)
			return
		}
		writeJSON(w, 200, `{"results":[{"actId":"A"}],"hasMore":true}`)
	})
	c, _ := newTestClient(t, f)
	p, _ := c.Statutes.IterSearch(context.Background(), &StatuteSearchRequest{Query: "x"})
	var n, errs int
	for _, err := range p.All() {
		if err != nil {
			errs++
			var nf *NotFoundError
			if !errors.As(err, &nf) {
				t.Errorf("err = %v", err)
			}
			continue
		}
		n++
	}
	if n != 1 || errs != 1 {
		t.Errorf("items=%d errors=%d", n, errs)
	}

	// A malformed item surfaces as a parse error.
	c2, _ := newTestClient(t, newFake(t, func(w http.ResponseWriter, r *http.Request, n int) {
		writeJSON(w, 200, `{"results":[{"actId":5}]}`)
	}))
	p, _ = c2.Statutes.IterSearch(context.Background(), &StatuteSearchRequest{Query: "x"})
	if _, err := p.Collect(); !errors.Is(err, ErrResponseParse) {
		t.Errorf("err = %v", err)
	}
	// A body that is not an object.
	c3, _ := newTestClient(t, newFake(t, func(w http.ResponseWriter, r *http.Request, n int) { writeJSON(w, 200, `[1]`) }))
	p, _ = c3.Statutes.IterSearch(context.Background(), &StatuteSearchRequest{Query: "x"})
	if _, err := p.Collect(); !errors.Is(err, ErrResponseParse) {
		t.Errorf("array body: %v", err)
	}
}

func TestIterSectionChangesIDWindow(t *testing.T) {
	// 5 changes, newest id first, 2 per page.
	f := newFake(t, func(w http.ResponseWriter, r *http.Request, n int) {
		before := int64(100)
		if v := r.URL.Query().Get("beforeId"); v != "" {
			_, _ = fmt.Sscan(v, &before)
		}
		var rows []string
		for id := before - 1; id >= 96 && len(rows) < 2; id-- {
			rows = append(rows, fmt.Sprintf(`{"id":%d}`, id))
		}
		writeJSON(w, 200, `{"changes":[`+strings.Join(rows, ",")+`],"creditsConsumed":1}`)
	})
	c, _ := newTestClient(t, f)
	p, err := c.Statutes.IterSectionChanges(context.Background(), "usc/1", &GetSectionChangesParams{Limit: Ptr(2)})
	if err != nil {
		t.Fatal(err)
	}
	got, err := p.Collect()
	if err != nil || len(got) != 4 {
		t.Fatalf("got %d err %v", len(got), err)
	}
	last := f.requests()
	if q := last[1].RawQuery; !strings.Contains(q, "beforeId=98") || !strings.Contains(q, "order=desc") || !strings.Contains(q, "limit=2") {
		t.Errorf("second page query = %q", q)
	}
	if !strings.Contains(last[0].EscapedPath, "usc%2F1") {
		t.Errorf("path = %q", last[0].EscapedPath)
	}
	// Ascending walks with sinceId.
	p, _ = c.Statutes.IterSectionChanges(context.Background(), "a", &GetSectionChangesParams{Order: Ptr("asc"), Limit: Ptr(1)}, WithMaxPages(2))
	_, _ = p.Collect()
	reqs := f.requests()
	if !strings.Contains(reqs[len(reqs)-1].RawQuery, "sinceId=") {
		t.Errorf("asc query = %q", reqs[len(reqs)-1].RawQuery)
	}
}

func TestIterEnvelopeAndOffsetEndpoints(t *testing.T) {
	f := newFake(t, func(w http.ResponseWriter, r *http.Request, n int) {
		off := r.URL.Query().Get("offset")
		more := off == "0"
		next := `null`
		rows := `{"id":"b1"},{"id":"b2"}`
		if !more {
			rows = `{"id":"b3"}`
		}
		_ = next
		writeJSON(w, 200, fmt.Sprintf(`{"data":{"boards":[%s],"hasMore":%v,"total":3},"meta":{"processingTimeMs":1,"creditsConsumed":0}}`, rows, more))
	})
	c, _ := newTestClient(t, f)
	p, err := c.Boards.IterList(context.Background(), &ListBoardsParams{State: Ptr("wa")})
	if err != nil {
		t.Fatal(err)
	}
	got, err := p.Collect()
	if err != nil || len(got) != 3 {
		t.Fatalf("boards = %d, %v", len(got), err)
	}
	reqs := f.requests()
	if !strings.Contains(reqs[0].RawQuery, "limit=500") || !strings.Contains(reqs[0].RawQuery, "state=wa") || !strings.Contains(reqs[1].RawQuery, "offset=2") {
		t.Errorf("queries = %q, %q", reqs[0].RawQuery, reqs[1].RawQuery)
	}
	if reqs[0].Header.Get("Idempotency-Key") != "" || c.CreditsSpent() != 0 {
		t.Error("boards are free")
	}
}

func TestIterBodyPages(t *testing.T) {
	f := newFake(t, func(w http.ResponseWriter, r *http.Request, n int) {
		q := r.URL.Query()
		switch q.Get("cursor") {
		case "":
			writeJSON(w, 200, `{"text":"aaa","pageStart":0,"pageEnd":3,"totalChars":6,"hasMore":true,"nextCursor":"c1","creditsConsumed":1}`)
		case "c1":
			writeJSON(w, 200, `{"text":"bbb","pageStart":3,"pageEnd":6,"totalChars":6,"hasMore":false,"nextCursor":null,"creditsConsumed":1}`)
		}
	})
	c, _ := newTestClient(t, f)
	p, err := c.SessionLaws.IterBody(context.Background(), "us1", &GetSessionLawBodyParams{StartChar: Ptr(0), Version: Ptr(2)})
	if err != nil {
		t.Fatal(err)
	}
	pages, err := p.Collect()
	if err != nil || len(pages) != 2 || *pages[0].Text != "aaa" || *pages[1].Text != "bbb" {
		t.Fatalf("pages=%+v err=%v", pages, err)
	}
	reqs := f.requests()
	if strings.Contains(reqs[1].RawQuery, "startChar") || !strings.Contains(reqs[1].RawQuery, "cursor=c1") || !strings.Contains(reqs[1].RawQuery, "version=2") {
		t.Errorf("second page query = %q", reqs[1].RawQuery)
	}
	if !strings.Contains(reqs[0].RawQuery, "startChar=0") {
		t.Errorf("first page query = %q", reqs[0].RawQuery)
	}
}

func TestOtherIteratorsConstruct(t *testing.T) {
	f := newFake(t, func(w http.ResponseWriter, r *http.Request, n int) {
		if strings.HasPrefix(r.URL.Path, "/api/v1/watches") {
			writeJSON(w, 200, `{"data":{"watches":[{"id":"w"}],"changes":[{"id":4}],"hasMore":false},"meta":{}}`)
			return
		}
		writeJSON(w, 200, `{"divisions":[{"label":"a"}],"results":[{"sessionLawId":"x"}],"changes":[{"id":1}],"nextCursor":null,"hasMore":false}`)
	})
	c, _ := newTestClient(t, f)
	ctx := context.Background()
	expect := func(name string, n int, err error) {
		t.Helper()
		if err != nil || n != 1 {
			t.Errorf("%s: n=%d err=%v", name, n, err)
		}
	}
	p1, err := c.Statutes.IterDivisions(ctx, "USC", &ListStatuteDivisionsParams{TitleNumber: Ptr(42)})
	if err != nil {
		t.Fatal(err)
	}
	r1, err := p1.Collect()
	expect("divisions", len(r1), err)
	p2, _ := c.SessionLaws.IterSearch(ctx, &SessionLawSearchRequest{Query: "x"})
	r2, err := p2.Collect()
	expect("sl search", len(r2), err)
	p3, _ := c.SessionLaws.IterList(ctx, "wa", &ListSessionLawsParams{Session: Ptr("2025")})
	r3, err := p3.Collect()
	expect("sl list", len(r3), err)
	p4, _ := c.SessionLaws.IterChanges(ctx, nil)
	r4, err := p4.Collect()
	expect("sl changes", len(r4), err)
	p5, _ := c.Watches.IterList(ctx, nil)
	r5, err := p5.Collect()
	expect("watches", len(r5), err)
	p6, _ := c.Watches.IterChanges(ctx, "w1", &ListWatchChangesParams{Order: Ptr("asc")})
	r6, err := p6.Collect()
	expect("watch changes", len(r6), err)
	if _, err := c.Watches.IterChanges(ctx, "..", nil); err == nil {
		t.Error("bad segment")
	}
	if _, err := c.Statutes.IterSectionChanges(ctx, "", nil); err == nil {
		t.Error("bad segment")
	}
	if _, err := c.SessionLaws.IterBody(ctx, ".", nil); err == nil {
		t.Error("bad segment")
	}
	if _, err := c.SessionLaws.IterSearch(ctx, nil); err == nil {
		t.Error("nil req")
	}
	reqs := f.requests()
	if !strings.Contains(reqs[3].RawQuery, "sinceId=0") || !strings.Contains(reqs[3].RawQuery, "limit=50") {
		t.Errorf("changes defaults = %q", reqs[3].RawQuery)
	}
	if !strings.Contains(reqs[2].RawQuery, "jurisdiction=wa") {
		t.Errorf("list query = %q", reqs[2].RawQuery)
	}
}

func TestPageCallOptionsKeySuffix(t *testing.T) {
	f := searchServer(t, 15, 10)
	c, _ := newTestClient(t, f)
	p, _ := c.Statutes.IterSearch(context.Background(), &StatuteSearchRequest{Query: "x"},
		WithPageCallOptions(WithIdempotencyKey("page-key-1234567890")))
	if _, err := p.Collect(); err != nil {
		t.Fatal(err)
	}
	reqs := f.requests()
	if reqs[0].Header.Get("Idempotency-Key") != "page-key-1234567890" || reqs[1].Header.Get("Idempotency-Key") != "page-key-1234567890-1" {
		t.Errorf("keys = %q, %q", reqs[0].Header.Get("Idempotency-Key"), reqs[1].Header.Get("Idempotency-Key"))
	}
}
