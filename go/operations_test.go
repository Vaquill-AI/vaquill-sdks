package vaquill

import (
	"context"
	"encoding/json"
	"net/http"
	"net/url"
	"os"
	"reflect"
	"sort"
	"strings"
	"testing"
	"time"
)

type opCase struct {
	id     string
	call   func(c *Client, opts ...CallOption) error
	method string
	path   string // escaped path as sent on the wire
	query  string
	body   string
}

func e[T any](_ T, err error) error { return err }

func operationCases() []opCase {
	ctx := context.Background()
	return []opCase{
		{"get_pricing", func(c *Client, o ...CallOption) error {
			return e(c.Pricing.Get(ctx, &GetPricingParams{Region: Ptr("US")}, o...))
		}, "GET", "/api/v1/api-credits/pricing", "region=US", ""},
		{"list_boards", func(c *Client, o ...CallOption) error {
			return e(c.Boards.List(ctx, &ListBoardsParams{CorpusType: Ptr("USC"), State: Ptr("wa"), Limit: Ptr(5), Offset: Ptr(2)}, o...))
		}, "GET", "/api/v1/boards", "corpusType=USC&state=wa&limit=5&offset=2", ""},
		{"get_credit_balance", func(c *Client, o ...CallOption) error { return e(c.Credits.Balance(ctx, o...)) },
			"GET", "/api/v1/credits/balance", "", ""},
		{"get_session_laws_batch", func(c *Client, o ...CallOption) error {
			return e(c.SessionLaws.GetBatch(ctx, &SessionLawBatchRequest{Ids: []string{"a", "b"}, Jurisdiction: Ptr("wa"), IncludeBody: Ptr(true)}, o...))
		}, "POST", "/api/v1/us/session-laws/batch", "", `{"ids":["a","b"],"jurisdiction":"wa","includeBody":true}`},
		{"get_session_law_changes", func(c *Client, o ...CallOption) error {
			return e(c.SessionLaws.Changes(ctx, &GetSessionLawChangesParams{SinceID: Ptr(0), Jurisdiction: Ptr("wa"), Limit: Ptr(10)}, o...))
		}, "GET", "/api/v1/us/session-laws/changes", "sinceId=0&jurisdiction=wa&limit=10", ""},
		{"list_session_laws", func(c *Client, o ...CallOption) error {
			return e(c.SessionLaws.List(ctx, "wa", &ListSessionLawsParams{Session: Ptr("2025"), Series: []string{"act", "law"}, HasText: Ptr(false), ApprovedFrom: Date(time.Date(2025, 1, 2, 0, 0, 0, 0, time.UTC)), Limit: Ptr(3)}, o...))
		}, "GET", "/api/v1/us/session-laws/list", "jurisdiction=wa&session=2025&series=act&series=law&hasText=false&approvedFrom=2025-01-02&limit=3", ""},
		{"search_session_laws", func(c *Client, o ...CallOption) error {
			return e(c.SessionLaws.Search(ctx, &SessionLawSearchRequest{Query: "water", Jurisdiction: Ptr("wa"), Series: []string{"act"}, Limit: Ptr(5)}, o...))
		}, "POST", "/api/v1/us/session-laws/search", "", `{"query":"water","jurisdiction":"wa","series":["act"],"limit":5}`},
		{"get_session_law", func(c *Client, o ...CallOption) error {
			return e(c.SessionLaws.Get(ctx, "us1/wa 2025", &GetSessionLawParams{Jurisdiction: Ptr("wa")}, o...))
		}, "GET", "/api/v1/us/session-laws/us1%2Fwa%202025", "jurisdiction=wa", ""},
		{"get_session_law_body", func(c *Client, o ...CallOption) error {
			return e(c.SessionLaws.GetBody(ctx, "sl1", &GetSessionLawBodyParams{Cursor: Ptr("c"), StartChar: Ptr(5), ExpectTextSHA256: Ptr("abc"), Version: Ptr(2), IncludeUnverified: Ptr(true)}, o...))
		}, "GET", "/api/v1/us/session-laws/sl1/body", "cursor=c&startChar=5&expectTextSha256=abc&version=2&includeUnverified=true", ""},
		{"get_session_law_versions", func(c *Client, o ...CallOption) error { return e(c.SessionLaws.Versions(ctx, "sl1", o...)) },
			"GET", "/api/v1/us/session-laws/sl1/versions", "", ""},
		{"count_statute_sections", func(c *Client, o ...CallOption) error {
			return e(c.Statutes.Count(ctx, &StatuteCountRequest{State: StringOrList{"wa"}, CorpusType: StringOrList{"STATE", "REGULATION"}, TitleNumber: Ptr(42)}, o...))
		}, "POST", "/api/v1/us/statutes/count", "", `{"state":"wa","corpusType":["STATE","REGULATION"],"titleNumber":42}`},
		{"list_statutes_coverage", func(c *Client, o ...CallOption) error {
			return e(c.Statutes.Coverage(ctx, &ListStatutesCoverageParams{State: Ptr("wa")}, o...))
		}, "GET", "/api/v1/us/statutes/coverage", "state=wa", ""},
		{"list_statute_divisions", func(c *Client, o ...CallOption) error {
			return e(c.Statutes.Divisions(ctx, "USC", &ListStatuteDivisionsParams{TitleNumber: Ptr(42), ExcludeRepealed: Ptr(true), Cursor: Ptr("c")}, o...))
		}, "GET", "/api/v1/us/statutes/divisions", "corpusType=USC&titleNumber=42&excludeRepealed=true&cursor=c", ""},
		{"extract_statute_citations", func(c *Client, o ...CallOption) error {
			return e(c.Statutes.ExtractCitations(ctx, &ExtractCitationsRequest{Text: "see 42 U.S.C. 1983", Resolve: Ptr(true)}, o...))
		}, "POST", "/api/v1/us/statutes/extract-citations", "", `{"text":"see 42 U.S.C. 1983","resolve":true}`},
		{"get_part_rulemaking", func(c *Client, o ...CallOption) error {
			return e(c.Statutes.PartRulemaking(ctx, 40, "60/A", &GetPartRulemakingParams{Years: Ptr(3)}, o...))
		}, "GET", "/api/v1/us/statutes/part/40/60%2FA/rulemaking", "years=3", ""},
		{"resolve_statute_citation", func(c *Client, o ...CallOption) error {
			return e(c.Statutes.Resolve(ctx, "42 U.S.C. § 1983", &ResolveStatuteCitationParams{State: Ptr("federal")}, o...))
		}, "GET", "/api/v1/us/statutes/resolve", "cite=42+U.S.C.+%C2%A7+1983&state=federal", ""},
		{"resolve_statute_citations_batch", func(c *Client, o ...CallOption) error {
			return e(c.Statutes.ResolveBatch(ctx, &StatuteResolveBatchRequest{Citations: []string{"a", "b"}, State: Ptr("wa")}, o...))
		}, "POST", "/api/v1/us/statutes/resolve", "", `{"citations":["a","b"],"state":"wa"}`},
		{"search_statutes", func(c *Client, o ...CallOption) error {
			return e(c.Statutes.Search(ctx, &StatuteSearchRequest{Query: "negligence", State: StringOrList{"wa"}, Limit: Ptr(5), IncludeBody: Ptr(false), Fields: []string{"actId"}}, o...))
		}, "POST", "/api/v1/us/statutes/search", "", `{"query":"negligence","state":"wa","limit":5,"includeBody":false,"fields":["actId"]}`},
		{"get_section", func(c *Client, o ...CallOption) error { return e(c.Statutes.GetSection(ctx, "usc/42/1983", o...)) },
			"GET", "/api/v1/us/statutes/section/usc%2F42%2F1983", "", ""},
		{"get_section_body", func(c *Client, o ...CallOption) error {
			return e(c.Statutes.GetSectionBody(ctx, "a1", &GetSectionBodyParams{Format: Ptr("plain"), Structured: Ptr(true), Pinpoint: Ptr("(c)(1)"), AsOf: Ptr("2020-01-01")}, o...))
		}, "GET", "/api/v1/us/statutes/section/a1/body", "format=plain&structured=true&pinpoint=%28c%29%281%29&asOf=2020-01-01", ""},
		{"get_section_changes", func(c *Client, o ...CallOption) error {
			return e(c.Statutes.SectionChanges(ctx, "a1", &GetSectionChangesParams{Limit: Ptr(5), SinceID: Ptr(1), BeforeID: Ptr(9), ChangeKind: []string{"added", "removed"}, Order: Ptr("asc")}, o...))
		}, "GET", "/api/v1/us/statutes/section/a1/changes", "limit=5&sinceId=1&beforeId=9&changeKind=added&changeKind=removed&order=asc", ""},
		{"get_section_cited_by", func(c *Client, o ...CallOption) error {
			return e(c.Statutes.CitedBy(ctx, "a1", &GetSectionCitedByParams{Limit: Ptr(4)}, o...))
		}, "GET", "/api/v1/us/statutes/section/a1/cited-by", "limit=4", ""},
		{"get_section_cross_state", func(c *Client, o ...CallOption) error {
			return e(c.Statutes.CrossState(ctx, "a1", &GetSectionCrossStateParams{Limit: Ptr(4)}, o...))
		}, "GET", "/api/v1/us/statutes/section/a1/cross-state", "limit=4", ""},
		{"get_section_definitions", func(c *Client, o ...CallOption) error { return e(c.Statutes.Definitions(ctx, "a1", o...)) },
			"GET", "/api/v1/us/statutes/section/a1/definitions", "", ""},
		{"get_section_enactments", func(c *Client, o ...CallOption) error { return e(c.Statutes.Enactments(ctx, "a1", o...)) },
			"GET", "/api/v1/us/statutes/section/a1/enactments", "", ""},
		{"get_section_neighbors", func(c *Client, o ...CallOption) error {
			return e(c.Statutes.Neighbors(ctx, "a1", &GetSectionNeighborsParams{Limit: Ptr(2)}, o...))
		}, "GET", "/api/v1/us/statutes/section/a1/related", "limit=2", ""},
		{"get_section_rulemaking", func(c *Client, o ...CallOption) error { return e(c.Statutes.SectionRulemaking(ctx, "a1", o...)) },
			"GET", "/api/v1/us/statutes/section/a1/rulemaking", "", ""},
		{"get_sections_batch", func(c *Client, o ...CallOption) error {
			return e(c.Statutes.GetSectionsBatch(ctx, &StatuteSectionsRequest{ActIds: []string{"a1", "a2"}, IncludeBody: Ptr(true)}, o...))
		}, "POST", "/api/v1/us/statutes/sections", "", `{"actIds":["a1","a2"],"includeBody":true}`},
		{"list_watches", func(c *Client, o ...CallOption) error {
			return e(c.Watches.List(ctx, &ListWatchesParams{Limit: Ptr(7), Offset: Ptr(1)}, o...))
		}, "GET", "/api/v1/watches", "limit=7&offset=1", ""},
		{"create_watch", func(c *Client, o ...CallOption) error {
			return e(c.Watches.Create(ctx, &CreateWatchRequest{CorpusType: "STATE", State: Ptr("wa"), Channel: Ptr("webhook"), WebhookURL: Ptr("https://example.test/hook"),
				WebhookAuth: &WebhookAuthRequest{Scheme: Ptr("bearer"), Secret: Ptr("s")}, Scope: map[string]string{"chapter": "9"}}, o...))
		}, "POST", "/api/v1/watches", "", `{"corpusType":"STATE","state":"wa","channel":"webhook","webhookUrl":"https://example.test/hook","webhookAuth":{"scheme":"bearer","secret":"s"},"scope":{"chapter":"9"}}`},
		{"delete_watch", func(c *Client, o ...CallOption) error { return c.Watches.Delete(ctx, "w 1", o...) },
			"DELETE", "/api/v1/watches/w%201", "", ""},
		{"update_watch", func(c *Client, o ...CallOption) error {
			return e(c.Watches.Update(ctx, "w1", &UpdateWatchRequest{IsActive: Ptr(false), EmailAddress: Ptr("a@b.test")}, o...))
		}, "PATCH", "/api/v1/watches/w1", "", `{"isActive":false,"emailAddress":"a@b.test"}`},
		{"list_watch_changes", func(c *Client, o ...CallOption) error {
			return e(c.Watches.Changes(ctx, "w1", &ListWatchChangesParams{Limit: Ptr(5), Since: Time(time.Date(2026, 1, 2, 3, 4, 5, 0, time.UTC)), ChangeKind: []string{"amended"}, Order: Ptr("desc")}, o...))
		}, "GET", "/api/v1/watches/w1/changes", "limit=5&since=2026-01-02T03%3A04%3A05Z&changeKind=amended&order=desc", ""},
		{"get_watch_change_diff", func(c *Client, o ...CallOption) error { return e(c.Watches.ChangeDiff(ctx, "w1", 42, o...)) },
			"GET", "/api/v1/watches/w1/changes/42/diff", "", ""},
		{"list_watch_deliveries", func(c *Client, o ...CallOption) error {
			return e(c.Watches.Deliveries(ctx, "w1", &ListWatchDeliveriesParams{Limit: Ptr(9)}, o...))
		}, "GET", "/api/v1/watches/w1/deliveries", "limit=9", ""},
		{"test_watch", func(c *Client, o ...CallOption) error { return e(c.Watches.Test(ctx, "w1", o...)) },
			"POST", "/api/v1/watches/w1/test", "", ""},
	}
}

func opServer(t *testing.T) *fake {
	return newFake(t, func(w http.ResponseWriter, r *http.Request, n int) {
		switch {
		case r.Method == "DELETE":
			w.WriteHeader(204)
		case r.Method == "POST" && r.URL.Path == "/api/v1/watches":
			writeJSON(w, 201, `{}`)
		default:
			writeJSON(w, 200, `{}`)
		}
	})
}

func sameQuery(t *testing.T, got, want string) {
	t.Helper()
	g, _ := url.ParseQuery(got)
	w, _ := url.ParseQuery(want)
	if !reflect.DeepEqual(g, w) {
		t.Errorf("query = %v, want %v", g, w)
	}
}

func TestEveryOperationSendsTheRightRequest(t *testing.T) {
	cases := operationCases()
	byID := map[string]OperationInfo{}
	for _, op := range Operations {
		byID[op.ID] = op
	}
	for _, tc := range cases {
		t.Run(tc.id, func(t *testing.T) {
			f := opServer(t)
			c, _ := newTestClient(t, f)
			if err := tc.call(c); err != nil {
				t.Fatal(err)
			}
			reqs := f.requests()
			if len(reqs) != 1 {
				t.Fatalf("requests = %d, want exactly 1", len(reqs))
			}
			r := reqs[0]
			if r.Method != tc.method || r.EscapedPath != tc.path {
				t.Errorf("%s %s, want %s %s", r.Method, r.EscapedPath, tc.method, tc.path)
			}
			sameQuery(t, r.RawQuery, tc.query)
			if tc.body == "" {
				if r.Body != "" || r.Header.Get("Content-Type") != "" {
					t.Errorf("no body expected, got %q (%s)", r.Body, r.Header.Get("Content-Type"))
				}
			} else {
				jsonEqual(t, r.Body, tc.body)
				if r.Header.Get("Content-Type") != "application/json" {
					t.Errorf("Content-Type = %q", r.Header.Get("Content-Type"))
				}
			}
			info, ok := byID[tc.id]
			if !ok {
				t.Fatalf("%s missing from Operations", tc.id)
			}
			if info.Method != tc.method {
				t.Errorf("Operations method %s", info.Method)
			}
			if hasKey := r.Header.Get("Idempotency-Key") != ""; hasKey != info.Charged {
				t.Errorf("charged=%v but Idempotency-Key present=%v", info.Charged, hasKey)
			}
		})
	}
}

type specDoc struct {
	Paths map[string]map[string]struct {
		OperationID string `json:"operationId"`
		Parameters  []struct {
			Name string `json:"name"`
			In   string `json:"in"`
		} `json:"parameters"`
	} `json:"paths"`
}

func TestOperationsMatchSpec(t *testing.T) {
	raw, err := os.ReadFile("../openapi/vaquill-us.json")
	if err != nil {
		t.Fatal(err)
	}
	var spec specDoc
	if err := json.Unmarshal(raw, &spec); err != nil {
		t.Fatal(err)
	}
	type want struct {
		method, path string
		charged      bool
	}
	wants := map[string]want{}
	for path, item := range spec.Paths {
		for m, op := range item {
			if op.OperationID == "" {
				continue
			}
			charged := false
			for _, p := range op.Parameters {
				if p.In == "header" && p.Name == "Idempotency-Key" {
					charged = true
				}
			}
			wants[op.OperationID] = want{strings.ToUpper(m), path, charged}
		}
	}
	if len(wants) != 36 || len(Operations) != 36 {
		t.Fatalf("spec has %d operations, Operations has %d, want 36", len(wants), len(Operations))
	}
	c, _ := NewClient(WithAPIKey(testKey))
	cv := reflect.ValueOf(c).Elem()
	for _, op := range Operations {
		w, ok := wants[op.ID]
		if !ok {
			t.Errorf("%s is not in the spec", op.ID)
			continue
		}
		if op.Method != w.method || op.Path != w.path || op.Charged != w.charged {
			t.Errorf("%s: got %s %s charged=%v, spec %s %s charged=%v", op.ID, op.Method, op.Path, op.Charged, w.method, w.path, w.charged)
		}
		svc := cv.FieldByName(op.Service)
		if !svc.IsValid() || !svc.MethodByName(op.GoMethod).IsValid() {
			t.Errorf("%s: no method %s.%s", op.ID, op.Service, op.GoMethod)
		}
	}
	covered := map[string]bool{}
	for _, tc := range operationCases() {
		covered[tc.id] = true
	}
	var missing []string
	for id := range wants {
		if !covered[id] {
			missing = append(missing, id)
		}
	}
	sort.Strings(missing)
	if len(missing) > 0 {
		t.Errorf("operations without a request test: %v", missing)
	}
	if !sort.SliceIsSorted(Operations, func(i, j int) bool { return Operations[i].ID < Operations[j].ID }) {
		t.Error("Operations must be sorted by ID")
	}
}

func TestChargedOperationCount(t *testing.T) {
	n := 0
	for _, op := range Operations {
		if op.Charged {
			n++
		}
	}
	if n != 25 {
		t.Errorf("charged operations = %d, want 25 (see python/docs/OPERATIONS.md)", n)
	}
}

func TestBatchAllHelpers(t *testing.T) {
	f := newFake(t, func(w http.ResponseWriter, r *http.Request, n int) {
		var body map[string][]string
		_ = json.Unmarshal([]byte(f0(t, n)), &body)
		switch r.URL.Path {
		case "/api/v1/us/statutes/resolve":
			var rows []string
			for _, c := range body["citations"] {
				rows = append(rows, `{"citation":"`+c+`"}`)
			}
			writeJSON(w, 200, `{"results":[`+strings.Join(rows, ",")+`]}`)
		case "/api/v1/us/statutes/sections":
			var rows []string
			for _, c := range body["actIds"] {
				rows = append(rows, `{"actId":"`+c+`"}`)
			}
			writeJSON(w, 200, `{"sections":[`+strings.Join(rows, ",")+`]}`)
		default:
			var rows []string
			for _, c := range body["ids"] {
				rows = append(rows, `{"sessionLawId":"`+c+`"}`)
			}
			writeJSON(w, 200, `{"laws":[`+strings.Join(rows, ",")+`]}`)
		}
	})
	fakeRef = f
	c, _ := newTestClient(t, f)
	ctx := context.Background()
	gen := func(n int, dup bool) []string {
		var out []string
		for i := 0; i < n; i++ {
			out = append(out, "c"+itoa(i))
		}
		if dup {
			out = append(out, "c0", "c1")
		}
		return out
	}
	res, err := c.Statutes.ResolveBatchAll(ctx, &StatuteResolveBatchRequest{Citations: gen(1203, true), State: Ptr("wa")}, WithIdempotencyKey("batch-key-1234567890"))
	if err != nil || len(res) != 1203 {
		t.Fatalf("resolve: n=%d err=%v", len(res), err)
	}
	reqs := f.requests()
	if len(reqs) != 3 {
		t.Fatalf("resolve chunks = %d, want 3 (500+500+203)", len(reqs))
	}
	wantKeys := []string{"batch-key-1234567890", "batch-key-1234567890-1", "batch-key-1234567890-2"}
	for i, r := range reqs {
		if r.Header.Get("Idempotency-Key") != wantKeys[i] {
			t.Errorf("chunk %d key %q", i, r.Header.Get("Idempotency-Key"))
		}
		contains(t, r.Body, `"state":"wa"`)
	}

	secs, err := c.Statutes.GetSectionsAll(ctx, &StatuteSectionsRequest{ActIds: gen(120, true)})
	if err != nil || len(secs) != 120 {
		t.Fatalf("sections: n=%d err=%v", len(secs), err)
	}
	if got := len(f.requests()) - 3; got != 3 {
		t.Errorf("sections chunks = %d, want 3 (50+50+20)", got)
	}
	laws, err := c.SessionLaws.GetBatchAll(ctx, &SessionLawBatchRequest{Ids: gen(401, false)})
	if err != nil || len(laws) != 401 {
		t.Fatalf("laws: n=%d err=%v", len(laws), err)
	}
	if got := len(f.requests()) - 6; got != 3 {
		t.Errorf("law chunks = %d, want 3 (200+200+1)", got)
	}
	// Empty input sends nothing.
	before := len(f.requests())
	if r, err := c.Statutes.ResolveBatchAll(ctx, &StatuteResolveBatchRequest{}); err != nil || len(r) != 0 || len(f.requests()) != before {
		t.Errorf("empty: %v %v", r, err)
	}
	for _, err := range []error{
		e(c.Statutes.ResolveBatchAll(ctx, nil)), e(c.Statutes.GetSectionsAll(ctx, nil)), e(c.SessionLaws.GetBatchAll(ctx, nil)),
	} {
		if err == nil {
			t.Error("nil request must error")
		}
	}
}

func TestBatchAllStopsOnError(t *testing.T) {
	f := newFake(t, func(w http.ResponseWriter, r *http.Request, n int) {
		if n == 2 {
			writeJSON(w, 402, `{"detail":"out of credits","code":"insufficient_credits"}`)
			return
		}
		writeJSON(w, 200, `{"results":[{"citation":"x"}]}`)
	})
	c, _ := newTestClient(t, f)
	var cites []string
	for i := 0; i < 1100; i++ {
		cites = append(cites, "c"+itoa(i))
	}
	got, err := c.Statutes.ResolveBatchAll(context.Background(), &StatuteResolveBatchRequest{Citations: cites})
	if !errorsIs(err, ErrInsufficientCredits) || len(got) != 1 || len(f.requests()) != 2 {
		t.Errorf("got=%d err=%v requests=%d (partial results of finished chunks are returned)", len(got), err, len(f.requests()))
	}
}
