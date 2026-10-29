package vaquill

import (
	"context"
	"errors"
	"fmt"
	"net/http"
	"net/url"
	"strings"
	"sync"
	"testing"
	"time"
)

func TestNewClientKeyValidation(t *testing.T) {
	t.Setenv(APIKeyEnv, "")
	cases := []struct {
		name string
		opts []Option
		want string
	}{
		{"missing", nil, "No API key"},
		{"blank", []Option{WithAPIKey("   ")}, "No API key"},
		{"prefix", []Option{WithAPIKey("sk_live_abcdef")}, "start with 'vq_key_'"},
		{"inner space", []Option{WithAPIKey("vq_key_ab cd")}, "Invalid API key"},
		{"non ascii", []Option{WithAPIKey("vq_key_é")}, "Invalid API key"},
		{"negative retries", []Option{WithAPIKey(testKey), WithMaxRetries(-1)}, "max retries"},
		{"negative timeout", []Option{WithAPIKey(testKey), WithTimeout(-time.Second)}, "timeout"},
		{"negative cap", []Option{WithAPIKey(testKey), WithMaxCredits(-1)}, "max credits"},
		{"bad url", []Option{WithAPIKey(testKey), WithBaseURL("not a url")}, "invalid base URL"},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			_, err := NewClient(tc.opts...)
			var ce *ConfigError
			if !errors.As(err, &ce) {
				t.Fatalf("err = %v, want *ConfigError", err)
			}
			contains(t, err.Error(), tc.want)
			if strings.Contains(err.Error(), "sk_live") {
				t.Error("error echoed the key")
			}
		})
	}
}

func TestNewClientFromEnvAndTrim(t *testing.T) {
	t.Setenv(APIKeyEnv, testKey+"\n")
	t.Setenv(BaseURLEnv, "http://localhost:9/")
	c, err := NewClient()
	if err != nil {
		t.Fatal(err)
	}
	if c.BaseURL() != "http://localhost:9" {
		t.Errorf("BaseURL = %q", c.BaseURL())
	}
	c2, _ := NewClient(WithAPIKey(testKey), WithBaseURL("http://example.test"))
	if c2.BaseURL() != "http://example.test" {
		t.Errorf("option must beat env: %q", c2.BaseURL())
	}
	c.Close()
}

func TestDefaultBaseURL(t *testing.T) {
	t.Setenv(BaseURLEnv, "")
	c, err := NewClient(WithAPIKey(testKey))
	if err != nil || c.BaseURL() != DefaultBaseURL {
		t.Fatalf("c=%v err=%v", c, err)
	}
}

func TestHeaders(t *testing.T) {
	f := newFake(t, nil)
	c, _ := newTestClient(t, f,
		WithUserAgentSuffix("myapp/1.2"),
		WithDefaultHeaders(map[string]string{"X-Team": "a", "AUTHORIZATION": "Bearer evil", "idempotency-key": "evil-evil-evil-evil"}))
	_, err := c.Credits.Balance(context.Background(), WithRequestHeader("x-team", "b"), WithRequestHeader("X-Extra", "1"))
	if err != nil {
		t.Fatal(err)
	}
	h := f.last(t).Header
	if got := h.Get("Authorization"); got != "Bearer "+testKey {
		t.Errorf("Authorization = %q", got)
	}
	if h.Get("Idempotency-Key") != "" {
		t.Error("free call must not carry an Idempotency-Key, and a default header cannot add one")
	}
	if got := h.Get("X-Team"); got != "b" {
		t.Errorf("per-call header must win case-insensitively, got %q", got)
	}
	if h.Get("X-Extra") != "1" || h.Get("Accept") != "application/json" {
		t.Errorf("headers = %v", h)
	}
	ua := h.Get("User-Agent")
	if !strings.HasPrefix(ua, "vaquill-go/"+Version+" ") || !strings.HasSuffix(ua, " myapp/1.2") {
		t.Errorf("User-Agent = %q", ua)
	}
}

func TestWithOptionsSharesSpendAndHTTP(t *testing.T) {
	f := newFake(t, func(w http.ResponseWriter, r *http.Request, n int) { writeJSON(w, 200, `{"creditsConsumed":2}`) })
	c, _ := newTestClient(t, f)
	d, err := c.WithOptions(WithMaxCredits(3), WithDefaultHeaders(map[string]string{"X-A": "1"}))
	if err != nil {
		t.Fatal(err)
	}
	d.sleep = c.sleep
	if d.http != c.http || d.spend != c.spend {
		t.Fatal("derived client must share the http client and the spend tracker")
	}
	ctx := context.Background()
	if _, err := d.Statutes.Count(ctx, &StatuteCountRequest{}); err != nil {
		t.Fatal(err)
	}
	if _, err := c.Statutes.Count(ctx, &StatuteCountRequest{}); err != nil {
		t.Fatal(err)
	}
	if c.CreditsSpent() != 4 || d.CreditsSpent() != 4 {
		t.Errorf("spent = %v / %v, want 4", c.CreditsSpent(), d.CreditsSpent())
	}
	if _, err := d.Statutes.Count(ctx, &StatuteCountRequest{}); !errors.Is(err, ErrSpendGuard) {
		t.Errorf("err = %v, want spend guard", err)
	}
	if _, err := c.Statutes.Count(ctx, &StatuteCountRequest{}); err != nil {
		t.Errorf("the parent has no cap: %v", err)
	}
	e, err := d.WithOptions(WithoutMaxCredits(), WithAPIKey(testKey+"x"))
	if err != nil {
		t.Fatal(err)
	}
	if e.cfg.maxCredits != nil || e.cfg.apiKey != testKey+"x" {
		t.Error("overrides not applied")
	}
	if _, err := d.WithOptions(WithBaseURL("%%")); err == nil {
		t.Error("invalid derived config must error")
	}
}

type memLogger struct {
	mu    sync.Mutex
	lines []string
}

func (m *memLogger) add(level, msg string, args []any) {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.lines = append(m.lines, level+" "+msg+" "+fmt.Sprint(args...))
}
func (m *memLogger) Debug(msg string, args ...any) { m.add("D", msg, args) }
func (m *memLogger) Warn(msg string, args ...any)  { m.add("W", msg, args) }
func (m *memLogger) text() string {
	m.mu.Lock()
	defer m.mu.Unlock()
	return strings.Join(m.lines, "\n")
}

func TestLoggerRedactsKeyAndDeprecationWarnsOnce(t *testing.T) {
	f := newFake(t, func(w http.ResponseWriter, r *http.Request, n int) {
		w.Header().Set("Deprecation", "true")
		w.Header().Set("Sunset", "Wed, 11 Nov 2026 23:59:59 GMT")
		w.Header().Set("Idempotency-Status", "unavailable")
		writeJSON(w, 200, `{"creditsConsumed":0}`)
	})
	lg := &memLogger{}
	c, _ := newTestClient(t, f, WithLogger(lg), WithDefaultHeaders(map[string]string{"X-Key-Echo": testKey}))
	ctx := context.Background()
	for i := 0; i < 3; i++ {
		if _, err := c.Statutes.Count(ctx, &StatuteCountRequest{}); err != nil {
			t.Fatal(err)
		}
	}
	out := lg.text()
	if strings.Contains(out, testKey) {
		t.Fatalf("log leaked the API key:\n%s", out)
	}
	if n := strings.Count(out, "is deprecated"); n != 1 {
		t.Errorf("deprecation warnings = %d, want 1\n%s", n, out)
	}
	contains(t, out, "Sunset: Wed, 11 Nov 2026")
	contains(t, out, "could not deduplicate")
	// The redactor also scrubs errors and Stringers handed to the logger.
	r := redactor{inner: lg, key: testKey}
	r.Warn("x "+testKey, errors.New(testKey), time.Second)
	if strings.Contains(lg.text(), testKey) {
		t.Error("redactor leaked the key")
	}
}

func TestDefaultLoggerWarnDoesNotPanic(t *testing.T) {
	var l Logger = stdWarnLogger{}
	l.Debug("ignored")
	l.Warn("msg", "k", "v")
}

func TestResponseInfo(t *testing.T) {
	f := newFake(t, func(w http.ResponseWriter, r *http.Request, n int) {
		w.Header().Set("X-Request-ID", "req_1")
		w.Header().Set("Idempotent-Replayed", "true")
		w.Header().Set("X-RateLimit-Limit", "60")
		w.Header().Set("X-RateLimit-Remaining", "59")
		w.Header().Set("X-RateLimit-Reset", "12.5")
		writeJSON(w, 200, `{"data":{},"meta":{"creditsConsumed":3,"processingTimeMs":1}}`)
	})
	c, _ := newTestClient(t, f)
	var info ResponseInfo
	_, err := c.Watches.ChangeDiff(context.Background(), "w1", 7, WithResponse(&info))
	if err != nil {
		t.Fatal(err)
	}
	if info.StatusCode != 200 || info.RequestID != "req_1" || !info.IdempotentReplayed {
		t.Errorf("info = %+v", info)
	}
	if info.CreditsConsumed == nil || *info.CreditsConsumed != 3 {
		t.Errorf("CreditsConsumed = %v (meta.creditsConsumed must be read)", info.CreditsConsumed)
	}
	if info.CreditsChargedThisCall() != 0 || c.CreditsSpent() != 0 {
		t.Error("a replay must not count toward spend")
	}
	if info.RateLimit.Limit == nil || *info.RateLimit.Limit != 60 || *info.RateLimit.Reset != 12.5 || info.RateLimit.LimitDay != nil {
		t.Errorf("rate limit = %+v", info.RateLimit)
	}
	if len(info.Body) == 0 {
		t.Error("raw body missing")
	}
}

func TestResponseParseErrors(t *testing.T) {
	cases := []struct {
		name, body string
		status     int
	}{
		{"invalid json", `{not json`, 200},
		{"wrong shape", `{"count":"many"}`, 200},
		{"empty", ``, 200},
		{"null", `null`, 200},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			f := newFake(t, func(w http.ResponseWriter, r *http.Request, n int) {
				w.Header().Set("X-Request-ID", "req_9")
				writeJSON(w, tc.status, tc.body)
			})
			c, _ := newTestClient(t, f)
			_, err := c.Statutes.Count(context.Background(), &StatuteCountRequest{})
			var pe *ResponseParseError
			if !errors.As(err, &pe) || !errors.Is(err, ErrResponseParse) {
				t.Fatalf("err = %v, want *ResponseParseError", err)
			}
			if pe.RequestID != "req_9" || pe.StatusCode != 200 {
				t.Errorf("pe = %+v", pe)
			}
			contains(t, err.Error(), "request_id=req_9")
			var base Error
			if !errors.As(err, &base) {
				t.Error("must satisfy the Error interface")
			}
		})
	}
}

func TestTimeoutAndCancellation(t *testing.T) {
	release := make(chan struct{})
	f := newFake(t, func(w http.ResponseWriter, r *http.Request, n int) {
		select {
		case <-release:
		case <-r.Context().Done():
		}
	})
	t.Cleanup(func() { close(release) })
	c, _ := newTestClient(t, f, WithTimeout(40*time.Millisecond), WithMaxRetries(0))
	_, err := c.Credits.Balance(context.Background())
	var te *TimeoutError
	if !errors.As(err, &te) || !te.Timeout() {
		t.Fatalf("err = %v, want *TimeoutError", err)
	}
	var ce *ConnectionError
	if !errors.As(err, &ce) {
		t.Error("TimeoutError is a ConnectionError")
	}
	if !errors.Is(err, context.DeadlineExceeded) {
		t.Error("TimeoutError should unwrap to the deadline")
	}

	ctx, cancel := context.WithCancel(context.Background())
	time.AfterFunc(30*time.Millisecond, cancel)
	c2, _ := newTestClient(t, f, WithTimeout(0))
	if _, err := c2.Credits.Balance(ctx); !errors.Is(err, context.Canceled) {
		t.Errorf("err = %v, want context.Canceled", err)
	}
	// A per-call timeout of zero disables the client timeout.
	c3, _ := newTestClient(t, f, WithTimeout(10*time.Millisecond), WithMaxRetries(0))
	ctx2, cancel2 := context.WithTimeout(context.Background(), 60*time.Millisecond)
	defer cancel2()
	if _, err := c3.Credits.Balance(ctx2, WithRequestTimeout(0)); !errors.Is(err, context.DeadlineExceeded) {
		t.Errorf("err = %v, want the caller's deadline", err)
	}
}

func TestConnectionRefusedIsConnectionErrorAndRetried(t *testing.T) {
	f := newFake(t, nil)
	c, sl := newTestClient(t, f, WithMaxRetries(2))
	f.srv.Close()
	_, err := c.Statutes.Count(context.Background(), &StatuteCountRequest{}, WithIdempotencyKey("abcdefghijklmnop"))
	var ce *ConnectionError
	if !errors.As(err, &ce) {
		t.Fatalf("err = %v", err)
	}
	var te *TimeoutError
	if errors.As(err, &te) {
		t.Error("a refused connection is not a timeout")
	}
	if got := len(sl.all()); got != 2 {
		t.Errorf("connect failures must be retried: slept %d times, want 2", got)
	}
}

func TestRawEscapeHatch(t *testing.T) {
	f := newFake(t, func(w http.ResponseWriter, r *http.Request, n int) { writeJSON(w, 200, `{"creditsConsumed":4,"x":1}`) })
	c, _ := newTestClient(t, f)
	q := url.Values{"a": {"1", "2"}}
	info, err := c.Raw(context.Background(), RawRequest{Method: "post", Path: "/api/v1/new", Query: q, Body: map[string]any{"k": "<v>"}, Charged: true})
	if err != nil {
		t.Fatal(err)
	}
	got := f.last(t)
	if got.Method != "POST" || got.RawQuery != "a=1&a=2" || got.Header.Get("Idempotency-Key") == "" || got.Header.Get("Content-Type") != "application/json" {
		t.Errorf("request = %+v", got)
	}
	jsonEqual(t, got.Body, `{"k":"<v>"}`)
	contains(t, got.Body, "<v>") // HTML escaping is off
	if string(info.Body) != `{"creditsConsumed":4,"x":1}` || c.CreditsSpent() != 4 {
		t.Errorf("body=%s spent=%v", info.Body, c.CreditsSpent())
	}
	if _, err := c.Raw(context.Background(), RawRequest{Method: "GET", Path: "/x", Body: make(chan int)}); err == nil {
		t.Error("unencodable body must error")
	}
}

func TestNilRequestAndBadSegmentsAreErrors(t *testing.T) {
	f := newFake(t, nil)
	c, _ := newTestClient(t, f)
	ctx := context.Background()
	if _, err := c.Statutes.Search(ctx, nil); err == nil {
		t.Error("nil request must error")
	}
	for _, seg := range []string{"", ".", ".."} {
		if _, err := c.Statutes.GetSection(ctx, seg); err == nil {
			t.Errorf("segment %q must be rejected", seg)
		}
	}
	if n := len(f.requests()); n != 0 {
		t.Errorf("nothing may be sent, got %d requests", n)
	}
	if _, err := c.Statutes.GetSection(ctx, "x", WithRequestMaxRetries(-1)); err == nil {
		t.Error("negative per-call retries must error")
	}
}

func TestNilContextTolerated(t *testing.T) {
	f := newFake(t, nil)
	c, _ := newTestClient(t, f)
	//lint:ignore SA1012 deliberately passing nil
	if _, err := c.Credits.Balance(nil); err != nil { //nolint:staticcheck
		t.Fatal(err)
	}
}
