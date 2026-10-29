package vaquill

import (
	"context"
	"errors"
	"math"
	"net"
	"net/http"
	"strconv"
	"strings"
	"time"
)

// backoffDelay is 0.5 s doubling to an 8 s cap, scaled down by 0 to 25 percent jitter.
func backoffDelay(retriesDone int, rnd func() float64) time.Duration {
	base := float64(initialRetryDelay) * math.Pow(2, float64(retriesDone))
	if base > float64(maxRetryDelay) {
		base = float64(maxRetryDelay)
	}
	return time.Duration(base * (1 - 0.25*rnd()))
}

// parseRetryAfter reads retry-after-ms, then retry-after (seconds or an HTTP date).
func parseRetryAfter(h http.Header, now time.Time) (time.Duration, bool) {
	finite := func(f float64) (time.Duration, bool) {
		if math.IsNaN(f) || math.IsInf(f, 0) {
			return 0, false
		}
		if f < 0 {
			f = 0
		}
		if f > float64(math.MaxInt64)/float64(time.Second) {
			return time.Duration(math.MaxInt64), true
		}
		return time.Duration(f * float64(time.Second)), true
	}
	if ms := strings.TrimSpace(h.Get("Retry-After-Ms")); ms != "" {
		f, err := strconv.ParseFloat(ms, 64)
		if err != nil {
			return 0, false
		}
		return finite(f / 1000)
	}
	v := strings.TrimSpace(h.Get("Retry-After"))
	if v == "" {
		return 0, false
	}
	if f, err := strconv.ParseFloat(v, 64); err == nil {
		return finite(f)
	}
	t, err := http.ParseTime(v)
	if err != nil {
		return 0, false
	}
	return finite(t.Sub(now).Seconds())
}

// statusRetryable reports whether the server's answer is worth retrying. It keys on code and
// falls back to the status.
func statusRetryable(e *APIError) bool {
	if e.StatusCode == 501 {
		return false // Not Implemented never becomes implemented by waiting.
	}
	if neverRetryCodes[e.Code] || (e.Retryable != nil && !*e.Retryable) {
		return false
	}
	if retryableCodes[e.Code] {
		return true
	}
	return e.StatusCode == 408 || e.StatusCode == 429 || e.StatusCode >= 500
}

// delayForStatus returns how long to wait before retrying, or false to return the error.
// replaySafe is false for a charged call without an idempotency key: a 5xx there may have been
// processed and billed already, so it is returned instead of replayed.
func delayForStatus(e *APIError, retriesDone int, replaySafe bool, now time.Time, rnd func() float64) (time.Duration, bool) {
	if !statusRetryable(e) {
		return 0, false
	}
	if !replaySafe && e.StatusCode >= 500 {
		return 0, false
	}
	wait, ok := parseRetryAfter(e.Headers, now)
	if !ok && e.RetryAfterSeconds != nil && !math.IsNaN(*e.RetryAfterSeconds) && !math.IsInf(*e.RetryAfterSeconds, 0) {
		w := *e.RetryAfterSeconds
		if w < 0 {
			w = 0
		}
		wait, ok = time.Duration(w*float64(time.Second)), true
	}
	if !ok {
		return backoffDelay(retriesDone, rnd), true
	}
	if wait > maxRetryAfterDelay {
		return 0, false // a wait this long means "go away"
	}
	return wait, true
}

func isConnectError(err error) bool {
	var op *net.OpError
	if errors.As(err, &op) && op.Op == "dial" {
		return true
	}
	var dns *net.DNSError
	return errors.As(err, &dns)
}

// connectionRetryable: connect failures never reached the server, so they are always safe to
// retry. Any other transport failure is ambiguous (the request may have been processed) and is
// retried only for GET and HEAD, or when the call carries an idempotency key.
func connectionRetryable(err error, method string, hasKey bool) bool {
	if errors.Is(err, context.Canceled) {
		return false
	}
	if isConnectError(err) {
		return true
	}
	m := strings.ToUpper(method)
	return m == http.MethodGet || m == http.MethodHead || hasKey
}
