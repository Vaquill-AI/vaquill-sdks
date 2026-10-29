package vaquill

import (
	"context"
	"net/url"
	"strings"
	"testing"
	"time"
)

func TestPathSegment(t *testing.T) {
	ok := map[string]string{
		"abc":                  "abc",
		"42 U.S.C. 1983":       "42%20U.S.C.%201983",
		"a/b":                  "a%2Fb",
		"a?b#c":                "a%3Fb%23c",
		"100%":                 "100%25",
		"x:y@z$&+=,;":          "x%3Ay%40z%24%26%2B%3D%2C%3B",
		"~-._":                 "~-._",
		"§ 1-1":                "%C2%A7%201-1",
		"..a":                  "..a",
		"a..":                  "a..",
		"%2e%2e":               "%252e%252e",
		strings.Repeat("x", 3): "xxx",
	}
	for in, want := range ok {
		got, err := pathSegment(in)
		if err != nil || got != want {
			t.Errorf("pathSegment(%q) = %q, %v; want %q", in, got, err, want)
		}
	}
	for _, bad := range []string{"", ".", ".."} {
		var ce *ConfigError
		if _, err := pathSegment(bad); err == nil {
			t.Errorf("%q accepted", bad)
		} else if ce, _ = err.(*ConfigError); ce == nil {
			t.Errorf("%q: err type %T", bad, err)
		}
	}
}

func TestPathfHandlesTypes(t *testing.T) {
	got, err := pathf("/a/{x}/b/{n}/{m}/{o}", "x", "v/1", "n", 7, "m", int64(8), "o", 1.5)
	if err != nil || got != "/a/v%2F1/b/7/8/1.5" {
		t.Errorf("got %q, %v", got, err)
	}
	if _, err := pathf("/a/{x}", "x", ".."); err == nil {
		t.Error("'..' must be rejected")
	}
}

func TestSlashInIDStaysOneSegmentOnTheWire(t *testing.T) {
	f := newFake(t, nil)
	c, _ := newTestClient(t, f)
	if _, err := c.Statutes.GetSection(context.Background(), "usc/42/1983"); err != nil {
		t.Fatal(err)
	}
	r := f.last(t)
	if r.EscapedPath != "/api/v1/us/statutes/section/usc%2F42%2F1983" {
		t.Errorf("escaped path = %q", r.EscapedPath)
	}
}

func TestBuildQuery(t *testing.T) {
	type params struct {
		Limit *int         `json:"limit,omitempty"`
		Flag  *bool        `json:"flag,omitempty"`
		Off   *bool        `json:"off,omitempty"`
		Kinds []string     `json:"kinds,omitempty"`
		Since *time.Time   `json:"since,omitempty"`
		Zero  *int         `json:"zero,omitempty"`
		Name  *string      `json:"name,omitempty"`
		Skip  *string      `json:"skip,omitempty"`
		Ratio *float64     `json:"ratio,omitempty"`
		Multi StringOrList `json:"multi,omitempty"`
	}
	since := time.Date(2026, 10, 29, 8, 30, 0, 0, time.FixedZone("x", 3600))
	q, err := buildQuery(&params{
		Limit: Ptr(25), Flag: Ptr(true), Off: Ptr(false), Kinds: []string{"added", "amended"},
		Since: &since, Zero: Ptr(0), Name: Ptr("a b&c=d"), Ratio: Ptr(0.25), Multi: StringOrList{"x", "y"},
	}, "cite", "42 U.S.C. 1983")
	if err != nil {
		t.Fatal(err)
	}
	want := url.Values{
		"limit": {"25"}, "flag": {"true"}, "off": {"false"}, "kinds": {"added", "amended"},
		"since": {"2026-10-29T08:30:00+01:00"}, "zero": {"0"}, "name": {"a b&c=d"}, "ratio": {"0.25"},
		"multi": {"x", "y"}, "cite": {"42 U.S.C. 1983"},
	}
	for k, w := range want {
		g := q[k]
		if strings.Join(g, "|") != strings.Join(w, "|") {
			t.Errorf("%s = %v, want %v", k, g, w)
		}
	}
	if _, has := q["skip"]; has || len(q) != len(want) {
		t.Errorf("unset members must be omitted: %v", q)
	}
	enc := q.Encode()
	if !strings.Contains(enc, "kinds=added&kinds=amended") || !strings.Contains(enc, "since=2026-10-29T08%3A30%3A00%2B01%3A00") {
		t.Errorf("encoded = %s", enc)
	}
	// nil params and nil typed pointers.
	var np *params
	q, err = buildQuery(np, "a", "b")
	if err != nil || q.Get("a") != "b" || len(q) != 1 {
		t.Errorf("nil params: %v %v", q, err)
	}
	if q, _ = buildQuery(nil); len(q) != 0 {
		t.Errorf("nil: %v", q)
	}
}

func TestToMapNormalisesNumbers(t *testing.T) {
	m, err := toMap(struct {
		A int64   `json:"a"`
		B float64 `json:"b"`
		C *string `json:"c"`
		D []int   `json:"d"`
	}{A: 1 << 60, B: 1.5, D: []int{1}})
	if err != nil {
		t.Fatal(err)
	}
	if m["a"] != int64(1<<60) || m["b"] != 1.5 {
		t.Errorf("m = %#v", m)
	}
	if _, has := m["c"]; has {
		t.Error("null members are dropped")
	}
	if d, ok := m["d"].([]any); !ok || d[0] != int64(1) {
		t.Errorf("d = %#v", m["d"])
	}
	if _, err := toMap(42); err == nil {
		t.Error("a non-object must error")
	}
	if _, err := toMap(make(chan int)); err == nil {
		t.Error("an unencodable value must error")
	}
	m2, _ := toMap(map[string]any{"x": 1, "y": nil})
	if len(m2) != 1 {
		t.Errorf("map input: %v", m2)
	}
}

func TestQueryScalarAndStringOrList(t *testing.T) {
	now := time.Date(2026, 1, 2, 3, 4, 5, 0, time.UTC)
	for in, want := range map[any]string{
		"s": "s", true: "true", false: "false", now: "2026-01-02T03:04:05Z", &now: "2026-01-02T03:04:05Z",
		3: "3", int64(4): "4", 1.5: "1.5", float64(2): "2", 2 * time.Second: "2s",
	} {
		if got := queryScalar(in); got != want {
			t.Errorf("queryScalar(%v) = %q, want %q", in, got, want)
		}
	}
	if queryScalar(struct{}{}) != "{}" {
		t.Error("fallback")
	}
	var s StringOrList
	if err := s.UnmarshalJSON([]byte(`"one"`)); err != nil || len(s) != 1 || s[0] != "one" {
		t.Errorf("scalar decode: %v %v", s, err)
	}
	if err := s.UnmarshalJSON([]byte(`["a","b"]`)); err != nil || len(s) != 2 {
		t.Errorf("array decode: %v %v", s, err)
	}
	if s.UnmarshalJSON([]byte(`12`)) == nil || s.UnmarshalJSON([]byte(`"x`)) == nil {
		t.Error("invalid forms must error")
	}
	b, _ := StringOrList(nil).MarshalJSON()
	if string(b) != "null" {
		t.Errorf("nil marshals to %s", b)
	}
	b, _ = StringOrList{"a", "b"}.MarshalJSON()
	if string(b) != `["a","b"]` {
		t.Errorf("marshal %s", b)
	}
	if *Ptr(7) != 7 {
		t.Error("Ptr")
	}
}

func TestStringOrListSingleIsScalar(t *testing.T) {
	b, _ := StringOrList{"USC"}.MarshalJSON()
	if string(b) != `"USC"` {
		t.Errorf("single value marshals as %s", b)
	}
}
