package vaquill

import (
	"context"
	"errors"
	"net/http"
	"regexp"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
)

func TestValidateIdempotencyKey(t *testing.T) {
	ok := []string{strings.Repeat("a", 16), strings.Repeat("~", 255), "abcdefgh-ijkl-mnop", "!\"#$%&'()*+,-./:"}
	bad := []string{"", "short", strings.Repeat("a", 15), strings.Repeat("a", 256), "has space in the key!", "tab\tin-the-key-xxxx", "café-café-café-xx", "new\nline-in-key-xxx", "del\x7f-in-key-xxxxxx"}
	for _, k := range ok {
		if err := validateIdempotencyKey(k); err != nil {
			t.Errorf("%q rejected: %v", k, err)
		}
	}
	for _, k := range bad {
		var ce *ConfigError
		if err := validateIdempotencyKey(k); !errors.As(err, &ce) {
			t.Errorf("%q accepted", k)
		}
	}
	if redactKey("0123456789abcdef") != "01234567..." || redactKey("abc") != "abc..." {
		t.Error("redactKey")
	}
}

var uuidV4 = regexp.MustCompile(`^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$`)

func TestAutoKeyOnChargedOnly(t *testing.T) {
	f := newFake(t, nil)
	c, _ := newTestClient(t, f)
	ctx := context.Background()
	_, _ = c.Statutes.Count(ctx, &StatuteCountRequest{})
	_, _ = c.Statutes.Count(ctx, &StatuteCountRequest{})
	_, _ = c.Statutes.Coverage(ctx, nil)
	_, _ = c.Boards.List(ctx, nil)
	_, _ = c.Watches.Test(ctx, "w1")
	reqs := f.requests()
	k1, k2 := reqs[0].Header.Get("Idempotency-Key"), reqs[1].Header.Get("Idempotency-Key")
	if !uuidV4.MatchString(k1) || k1 == k2 {
		t.Errorf("keys %q %q must be distinct UUIDv4", k1, k2)
	}
	for _, r := range reqs[2:] {
		if r.Header.Get("Idempotency-Key") != "" {
			t.Errorf("%s %s is free and must not carry a key", r.Method, r.Path)
		}
	}
}

func TestExplicitKeyIsUsedAndValidated(t *testing.T) {
	f := newFake(t, nil)
	c, _ := newTestClient(t, f)
	ctx := context.Background()
	if _, err := c.Statutes.Count(ctx, &StatuteCountRequest{}, WithIdempotencyKey("my-key-1234567890")); err != nil {
		t.Fatal(err)
	}
	if got := f.last(t).Header.Get("Idempotency-Key"); got != "my-key-1234567890" {
		t.Errorf("key = %q", got)
	}
	n := len(f.requests())
	for _, bad := range []string{"", "short", "has a space in it!!"} {
		var ce *ConfigError
		if _, err := c.Statutes.Count(ctx, &StatuteCountRequest{}, WithIdempotencyKey(bad)); !errors.As(err, &ce) {
			t.Errorf("key %q: err = %v", bad, err)
		}
	}
	if len(f.requests()) != n {
		t.Error("an invalid key must be rejected before sending")
	}
}

func TestReplayedResponseIsNotCounted(t *testing.T) {
	f := newFake(t, func(w http.ResponseWriter, r *http.Request, n int) {
		if n == 2 {
			w.Header().Set("Idempotent-Replayed", "true")
		}
		writeJSON(w, 200, `{"creditsConsumed":3}`)
	})
	c, _ := newTestClient(t, f)
	for i := 0; i < 2; i++ {
		if _, err := c.Statutes.Count(context.Background(), &StatuteCountRequest{}); err != nil {
			t.Fatal(err)
		}
	}
	if c.CreditsSpent() != 3 {
		t.Errorf("spent = %v, want 3 (the replay is free)", c.CreditsSpent())
	}
}

func TestSpendGuardConcurrentExactness(t *testing.T) {
	var hits atomic.Int32
	f := newFake(t, func(w http.ResponseWriter, r *http.Request, n int) {
		hits.Add(1)
		writeJSON(w, 200, `{"creditsConsumed":1}`)
	})
	c, _ := newTestClient(t, f, WithMaxCredits(5))
	var wg sync.WaitGroup
	var okN, guarded atomic.Int32
	for i := 0; i < 40; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			_, err := c.Statutes.Count(context.Background(), &StatuteCountRequest{})
			switch {
			case err == nil:
				okN.Add(1)
			case errors.Is(err, ErrSpendGuard):
				var sg *SpendGuardError
				if !errors.As(err, &sg) || sg.Limit != 5 {
					t.Errorf("err = %v", err)
				}
				guarded.Add(1)
			default:
				t.Errorf("unexpected error %v", err)
			}
		}()
	}
	wg.Wait()
	if okN.Load() != 5 || guarded.Load() != 35 || hits.Load() != 5 {
		t.Errorf("ok=%d guarded=%d server hits=%d; want exactly 5 / 35 / 5", okN.Load(), guarded.Load(), hits.Load())
	}
	if c.CreditsSpent() != 5 {
		t.Errorf("spent = %v", c.CreditsSpent())
	}
	// Free calls are never blocked by the guard.
	if _, err := c.Credits.Balance(context.Background()); err != nil {
		t.Errorf("free call blocked: %v", err)
	}
}

func TestSpendGuardWaitHonoursContext(t *testing.T) {
	release := make(chan struct{})
	f := newFake(t, func(w http.ResponseWriter, r *http.Request, n int) {
		<-release
		writeJSON(w, 200, `{"creditsConsumed":1}`)
	})
	c, _ := newTestClient(t, f, WithMaxCredits(100))
	done := make(chan error, 1)
	go func() {
		_, err := c.Statutes.Count(context.Background(), &StatuteCountRequest{})
		done <- err
	}()
	for len(f.requests()) == 0 {
	}
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	if _, err := c.Statutes.Count(ctx, &StatuteCountRequest{}); !errors.Is(err, context.Canceled) {
		t.Errorf("a call queued behind the cap lock must honour its context, got %v", err)
	}
	close(release)
	if err := <-done; err != nil {
		t.Fatal(err)
	}
}

func TestChunkOptions(t *testing.T) {
	key := strings.Repeat("k", 255)
	opts := []CallOption{WithIdempotencyKey(key)}
	if got := *newCallConfig(chunkOptions(opts, 0)).idempotencyKey; got != key {
		t.Error("first chunk keeps the key")
	}
	got := *newCallConfig(chunkOptions(opts, 12)).idempotencyKey
	if len(got) != 255 || !strings.HasSuffix(got, "-12") {
		t.Errorf("chunk 12 key = %q (len %d)", got, len(got))
	}
	if chunkOptions(nil, 3) != nil {
		t.Error("no key, no change")
	}
	if validateIdempotencyKey(got) != nil {
		t.Error("derived key must stay valid")
	}
}

func TestSpendGuardZeroCap(t *testing.T) {
	f := newFake(t, nil)
	c, _ := newTestClient(t, f, WithMaxCredits(0))
	if _, err := c.Statutes.Count(context.Background(), &StatuteCountRequest{}); !errors.Is(err, ErrSpendGuard) {
		t.Errorf("err = %v", err)
	}
	if len(f.requests()) != 0 {
		t.Error("nothing may be sent")
	}
}
