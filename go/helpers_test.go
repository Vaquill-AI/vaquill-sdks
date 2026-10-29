package vaquill

import (
	"context"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"net/http/httptest"
	"strconv"
	"strings"
	"sync"
	"testing"
	"time"
)

const testKey = "vq_key_0123456789abcdef0123456789abcdef" // pragma: allowlist secret

type seen struct {
	Method, Path, EscapedPath, RawQuery, Body string
	Header                                    http.Header
}

type fake struct {
	srv  *httptest.Server
	mu   sync.Mutex
	reqs []seen
}

func (f *fake) requests() []seen {
	f.mu.Lock()
	defer f.mu.Unlock()
	return append([]seen(nil), f.reqs...)
}

func (f *fake) last(t *testing.T) seen {
	t.Helper()
	r := f.requests()
	if len(r) == 0 {
		t.Fatal("no request reached the server")
	}
	return r[len(r)-1]
}

// newFake starts a server whose handler first records the request. respond may be nil (200 {}).
func newFake(t *testing.T, respond func(w http.ResponseWriter, r *http.Request, n int)) *fake {
	t.Helper()
	f := &fake{}
	f.srv = httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		b, _ := io.ReadAll(r.Body)
		f.mu.Lock()
		f.reqs = append(f.reqs, seen{r.Method, r.URL.Path, r.URL.EscapedPath(), r.URL.RawQuery, string(b), r.Header.Clone()})
		n := len(f.reqs)
		f.mu.Unlock()
		if respond == nil {
			w.Header().Set("Content-Type", "application/json")
			_, _ = w.Write([]byte("{}"))
			return
		}
		respond(w, r, n)
	}))
	t.Cleanup(f.srv.Close)
	return f
}

type sleepLog struct {
	mu sync.Mutex
	d  []time.Duration
}

func (s *sleepLog) all() []time.Duration {
	s.mu.Lock()
	defer s.mu.Unlock()
	return append([]time.Duration(nil), s.d...)
}

// newTestClient builds a client against f with sleeping replaced by a recorder and no jitter.
func newTestClient(t *testing.T, f *fake, opts ...Option) (*Client, *sleepLog) {
	t.Helper()
	all := append([]Option{WithAPIKey(testKey), WithBaseURL(f.srv.URL)}, opts...)
	c, err := NewClient(all...)
	if err != nil {
		t.Fatal(err)
	}
	log := &sleepLog{}
	c.sleep = func(ctx context.Context, d time.Duration) error {
		log.mu.Lock()
		log.d = append(log.d, d)
		log.mu.Unlock()
		return ctx.Err()
	}
	c.rnd = func() float64 { return 0 }
	return c, log
}

func writeJSON(w http.ResponseWriter, status int, body string) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_, _ = io.WriteString(w, body)
}

func jsonEqual(t *testing.T, got, want string) {
	t.Helper()
	var g, w any
	if err := json.Unmarshal([]byte(got), &g); err != nil {
		t.Fatalf("got body %q is not JSON: %v", got, err)
	}
	if err := json.Unmarshal([]byte(want), &w); err != nil {
		t.Fatalf("want body %q is not JSON: %v", want, err)
	}
	gb, _ := json.Marshal(g)
	wb, _ := json.Marshal(w)
	if string(gb) != string(wb) {
		t.Errorf("body = %s, want %s", gb, wb)
	}
}

func contains(t *testing.T, s, sub string) {
	t.Helper()
	if !strings.Contains(s, sub) {
		t.Errorf("%q does not contain %q", s, sub)
	}
}

func jsonUnmarshal(b []byte, v any) error { return json.Unmarshal(b, v) }

var fakeRef *fake

// f0 returns the recorded body of the nth request of the most recent batch fake.
func f0(t *testing.T, n int) string {
	t.Helper()
	return fakeRef.requests()[n-1].Body
}

func itoa(i int) string { return strconv.Itoa(i) }

func errorsIs(err, target error) bool { return errors.Is(err, target) }
