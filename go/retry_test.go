package vaquill

import (
	"context"
	"errors"
	"net/http"
	"net/http/httptest"
	"sync/atomic"
	"testing"
	"time"
)

var now0 = time.Date(2026, 10, 29, 12, 0, 0, 0, time.UTC)

func TestBackoffDelay(t *testing.T) {
	cases := []struct {
		n      int
		rnd    float64
		lo, hi time.Duration
	}{
		{0, 0, 500 * time.Millisecond, 500 * time.Millisecond},
		{1, 0, time.Second, time.Second},
		{2, 0, 2 * time.Second, 2 * time.Second},
		{10, 0, 8 * time.Second, 8 * time.Second},
		{0, 1, 375 * time.Millisecond, 375 * time.Millisecond},
		{10, 1, 6 * time.Second, 6 * time.Second},
	}
	for _, tc := range cases {
		if got := backoffDelay(tc.n, func() float64 { return tc.rnd }); got < tc.lo || got > tc.hi {
			t.Errorf("backoff(%d, %v) = %v, want %v..%v", tc.n, tc.rnd, got, tc.lo, tc.hi)
		}
	}
}

func TestParseRetryAfter(t *testing.T) {
	hdr := func(kv ...string) http.Header {
		h := http.Header{}
		for i := 0; i < len(kv); i += 2 {
			h.Set(kv[i], kv[i+1])
		}
		return h
	}
	cases := []struct {
		name string
		h    http.Header
		want time.Duration
		ok   bool
	}{
		{"none", hdr(), 0, false},
		{"seconds", hdr("Retry-After", "3"), 3 * time.Second, true},
		{"fraction", hdr("Retry-After", "1.5"), 1500 * time.Millisecond, true},
		{"ms wins", hdr("Retry-After-Ms", "250", "Retry-After", "9"), 250 * time.Millisecond, true},
		{"negative clamps", hdr("Retry-After", "-4"), 0, true},
		{"nan ignored", hdr("Retry-After", "NaN"), 0, false},
		{"inf ignored", hdr("Retry-After", "Inf"), 0, false},
		{"bad ms stops", hdr("Retry-After-Ms", "x", "Retry-After", "9"), 0, false},
		{"garbage", hdr("Retry-After", "soon"), 0, false},
		{"http date", hdr("Retry-After", now0.Add(7*time.Second).UTC().Format(http.TimeFormat)), 7 * time.Second, true},
		{"past date", hdr("Retry-After", now0.Add(-time.Hour).UTC().Format(http.TimeFormat)), 0, true},
	}
	for _, tc := range cases {
		got, ok := parseRetryAfter(tc.h, now0)
		if ok != tc.ok || got != tc.want {
			t.Errorf("%s: got %v,%v want %v,%v", tc.name, got, ok, tc.want, tc.ok)
		}
	}
}

func apiErr(status int, code string, retryable *bool, after *float64, h http.Header) *APIError {
	if h == nil {
		h = http.Header{}
	}
	return &APIError{StatusCode: status, Code: code, Retryable: retryable, RetryAfterSeconds: after, Headers: h}
}

func TestStatusRetryable(t *testing.T) {
	no, yes := false, true
	cases := []struct {
		e    *APIError
		want bool
	}{
		{apiErr(429, "", nil, nil, nil), true},
		{apiErr(408, "", nil, nil, nil), true},
		{apiErr(500, "", nil, nil, nil), true},
		{apiErr(503, "", nil, nil, nil), true},
		{apiErr(501, "", nil, nil, nil), false},
		{apiErr(400, "", nil, nil, nil), false},
		{apiErr(404, "", nil, nil, nil), false},
		{apiErr(402, "insufficient_credits", nil, nil, nil), false},
		{apiErr(429, "daily_cap_exceeded", nil, nil, nil), false},
		{apiErr(429, "rate_limited", &no, nil, nil), false},
		{apiErr(409, "idempotency_in_progress", nil, nil, nil), true},
		{apiErr(409, "idempotency_in_progress", &yes, nil, nil), true},
		{apiErr(422, "upstream_timeout", nil, nil, nil), true},
		{apiErr(409, "idempotency_replay_unavailable", nil, nil, nil), false},
	}
	for _, tc := range cases {
		if got := statusRetryable(tc.e); got != tc.want {
			t.Errorf("status %d code %q: got %v want %v", tc.e.StatusCode, tc.e.Code, got, tc.want)
		}
	}
}

func TestDelayForStatus(t *testing.T) {
	zero := func() float64 { return 0 }
	sec := func(f float64) *float64 { return &f }
	h := http.Header{}
	h.Set("Retry-After", "2")
	if d, ok := delayForStatus(apiErr(429, "", nil, sec(30), h), 0, true, now0, zero); !ok || d != 2*time.Second {
		t.Errorf("header must win over envelope: %v %v", d, ok)
	}
	if d, ok := delayForStatus(apiErr(429, "", nil, sec(30), nil), 0, true, now0, zero); !ok || d != 30*time.Second {
		t.Errorf("envelope retryAfterSeconds: %v %v", d, ok)
	}
	if d, ok := delayForStatus(apiErr(503, "", nil, nil, nil), 1, true, now0, zero); !ok || d != time.Second {
		t.Errorf("backoff: %v %v", d, ok)
	}
	if _, ok := delayForStatus(apiErr(429, "", nil, sec(121), nil), 0, true, now0, zero); ok {
		t.Error("a wait over 120s must surface the error")
	}
	if _, ok := delayForStatus(apiErr(500, "", nil, nil, nil), 0, false, now0, zero); ok {
		t.Error("5xx on a charged call without a key must not be replayed")
	}
	if _, ok := delayForStatus(apiErr(429, "", nil, nil, nil), 0, false, now0, zero); !ok {
		t.Error("a 429 was never processed, so it is safe to retry without a key")
	}
	if d, ok := delayForStatus(apiErr(429, "", nil, sec(-5), nil), 0, true, now0, zero); !ok || d != 0 {
		t.Errorf("negative envelope wait clamps to 0: %v %v", d, ok)
	}
}

func TestRetryOn429HonoursRetryAfterAndSucceeds(t *testing.T) {
	f := newFake(t, func(w http.ResponseWriter, r *http.Request, n int) {
		if n < 3 {
			w.Header().Set("Retry-After", "2")
			writeJSON(w, 429, `{"detail":"slow down","code":"rate_limited"}`)
			return
		}
		writeJSON(w, 200, `{"creditsConsumed":1}`)
	})
	c, sl := newTestClient(t, f)
	if _, err := c.Statutes.Count(context.Background(), &StatuteCountRequest{}); err != nil {
		t.Fatal(err)
	}
	if got := sl.all(); len(got) != 2 || got[0] != 2*time.Second {
		t.Errorf("sleeps = %v", got)
	}
	reqs := f.requests()
	if len(reqs) != 3 {
		t.Fatalf("attempts = %d", len(reqs))
	}
	k := reqs[0].Header.Get("Idempotency-Key")
	if k == "" || reqs[1].Header.Get("Idempotency-Key") != k || reqs[2].Header.Get("Idempotency-Key") != k {
		t.Error("the same Idempotency-Key must be reused on every retry")
	}
	if reqs[2].Body != reqs[0].Body {
		t.Error("body must be replayed intact")
	}
}

func TestRetryExhaustionReturnsLastError(t *testing.T) {
	f := newFake(t, func(w http.ResponseWriter, r *http.Request, n int) {
		writeJSON(w, 503, `{"detail":"down","code":"service_unavailable"}`)
	})
	c, sl := newTestClient(t, f, WithMaxRetries(2))
	_, err := c.Credits.Balance(context.Background())
	var ise *InternalServerError
	if !errors.As(err, &ise) {
		t.Fatalf("err = %v", err)
	}
	if len(f.requests()) != 3 || len(sl.all()) != 2 {
		t.Errorf("attempts=%d sleeps=%d", len(f.requests()), len(sl.all()))
	}
	// Per-call override.
	if _, err := c.Credits.Balance(context.Background(), WithRequestMaxRetries(0)); err == nil {
		t.Error("want error")
	}
	if len(f.requests()) != 4 {
		t.Errorf("per-call WithRequestMaxRetries(0) must not retry, requests=%d", len(f.requests()))
	}
}

func TestChargedCallWithoutKeyDoesNotRetry5xx(t *testing.T) {
	f := newFake(t, func(w http.ResponseWriter, r *http.Request, n int) {
		writeJSON(w, 500, `{"detail":"boom"}`)
	})
	c, sl := newTestClient(t, f, WithAutoIdempotencyKeys(false))
	_, err := c.Statutes.Count(context.Background(), &StatuteCountRequest{})
	if err == nil || len(f.requests()) != 1 || len(sl.all()) != 0 {
		t.Fatalf("err=%v requests=%d sleeps=%d", err, len(f.requests()), len(sl.all()))
	}
	if f.last(t).Header.Get("Idempotency-Key") != "" {
		t.Error("auto keys are disabled")
	}
	// An explicit key makes the replay safe.
	_, _ = c.Statutes.Count(context.Background(), &StatuteCountRequest{}, WithIdempotencyKey("my-own-key-123456"))
	if len(f.requests()) != 4 {
		t.Errorf("with an explicit key the 5xx is retried: requests=%d", len(f.requests()))
	}
	// A free call is replay safe too.
	before := len(f.requests())
	_, _ = c.Credits.Balance(context.Background())
	if len(f.requests())-before != 3 {
		t.Errorf("free call retried %d times", len(f.requests())-before-1)
	}
}

func TestNeverRetryCodes(t *testing.T) {
	for _, tc := range []struct {
		status int
		code   string
	}{{402, "insufficient_credits"}, {429, "daily_cap_exceeded"}, {501, ""}, {404, "not_found"}} {
		f := newFake(t, func(w http.ResponseWriter, r *http.Request, n int) {
			writeJSON(w, tc.status, `{"detail":"x","code":"`+tc.code+`"}`)
		})
		c, _ := newTestClient(t, f)
		if _, err := c.Credits.Balance(context.Background()); err == nil {
			t.Fatal("want error")
		}
		if len(f.requests()) != 1 {
			t.Errorf("%d %s retried %d times", tc.status, tc.code, len(f.requests())-1)
		}
	}
}

func TestRetryAfterTooLongSurfacesError(t *testing.T) {
	f := newFake(t, func(w http.ResponseWriter, r *http.Request, n int) {
		w.Header().Set("Retry-After", "600")
		writeJSON(w, 429, `{"detail":"x"}`)
	})
	c, sl := newTestClient(t, f)
	_, err := c.Credits.Balance(context.Background())
	var rl *RateLimitError
	if !errors.As(err, &rl) || len(sl.all()) != 0 {
		t.Fatalf("err=%v sleeps=%v", err, sl.all())
	}
}

func TestCancelDuringBackoff(t *testing.T) {
	f := newFake(t, func(w http.ResponseWriter, r *http.Request, n int) { writeJSON(w, 503, `{}`) })
	c, _ := newTestClient(t, f)
	ctx, cancel := context.WithCancel(context.Background())
	c.sleep = func(ctx context.Context, d time.Duration) error { cancel(); return ctx.Err() }
	if _, err := c.Credits.Balance(ctx); !errors.Is(err, context.Canceled) {
		t.Errorf("err = %v", err)
	}
}

// resetServer closes the connection without answering, which is an ambiguous transport failure.
func resetServer(t *testing.T, hits *atomic.Int32) *httptest.Server {
	t.Helper()
	s := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		hits.Add(1)
		conn, _, _ := w.(http.Hijacker).Hijack()
		_ = conn.Close()
	}))
	t.Cleanup(s.Close)
	return s
}

func TestAmbiguousTransportErrorRetryRules(t *testing.T) {
	var hits atomic.Int32
	s := resetServer(t, &hits)
	mk := func(opts ...Option) *Client {
		c, err := NewClient(append([]Option{WithAPIKey(testKey), WithBaseURL(s.URL), WithMaxRetries(2)}, opts...)...)
		if err != nil {
			t.Fatal(err)
		}
		c.sleep = func(context.Context, time.Duration) error { return nil }
		return c
	}
	ctx := context.Background()

	// GET is retried.
	hits.Store(0)
	_, err := mk().Credits.Balance(ctx)
	var ce *ConnectionError
	if !errors.As(err, &ce) || hits.Load() != 3 {
		t.Errorf("GET: err=%v hits=%d, want 3 hits", err, hits.Load())
	}
	// A charged POST without a key is not retried.
	hits.Store(0)
	_, err = mk(WithAutoIdempotencyKeys(false)).Statutes.Count(ctx, &StatuteCountRequest{})
	if err == nil || hits.Load() != 1 {
		t.Errorf("POST no key: err=%v hits=%d, want 1 hit", err, hits.Load())
	}
	// A charged POST with the auto key is retried.
	hits.Store(0)
	_, err = mk().Statutes.Count(ctx, &StatuteCountRequest{})
	if err == nil || hits.Load() != 3 {
		t.Errorf("POST with key: err=%v hits=%d, want 3 hits", err, hits.Load())
	}
	// A free POST without a key (test_watch) is not retried.
	hits.Store(0)
	_, err = mk().Watches.Test(ctx, "w1")
	if err == nil || hits.Load() != 1 {
		t.Errorf("free POST: err=%v hits=%d, want 1 hit", err, hits.Load())
	}
}

func TestConnectionRetryableMatrix(t *testing.T) {
	other := errors.New("read: connection reset")
	if !connectionRetryable(other, "GET", false) || !connectionRetryable(other, "head", false) {
		t.Error("GET and HEAD are retryable")
	}
	if connectionRetryable(other, "POST", false) || connectionRetryable(other, "DELETE", false) {
		t.Error("POST and DELETE without a key are not")
	}
	if !connectionRetryable(other, "POST", true) {
		t.Error("a key makes it retryable")
	}
	if connectionRetryable(context.Canceled, "GET", true) {
		t.Error("cancellation is never retried")
	}
}
