package vaquill

import (
	"context"
	"errors"
	"net/http"
	"strings"
	"testing"
)

func TestErrorTypeMapping(t *testing.T) {
	cases := []struct {
		name   string
		status int
		body   string
		target func(error) bool
		is     []error
	}{
		{"400", 400, `{"detail":"bad"}`, func(e error) bool { var x *BadRequestError; return errors.As(e, &x) }, []error{ErrBadRequest}},
		{"401", 401, `{"detail":"no"}`, func(e error) bool { var x *AuthenticationError; return errors.As(e, &x) }, []error{ErrAuthentication}},
		{"402", 402, `{"detail":"pay"}`, func(e error) bool { var x *InsufficientCreditsError; return errors.As(e, &x) }, []error{ErrInsufficientCredits}},
		{"403", 403, `{"detail":"no"}`, func(e error) bool { var x *PermissionDeniedError; return errors.As(e, &x) }, []error{ErrPermissionDenied}},
		{"404", 404, `{"detail":"gone"}`, func(e error) bool { var x *NotFoundError; return errors.As(e, &x) }, []error{ErrNotFound}},
		{"409", 409, `{"detail":"clash"}`, func(e error) bool { var x *ConflictError; return errors.As(e, &x) }, []error{ErrConflict}},
		{"422", 422, `{"detail":"invalid"}`, func(e error) bool { var x *UnprocessableEntityError; return errors.As(e, &x) }, []error{ErrUnprocessableEntity}},
		{"429", 429, `{"detail":"slow"}`, func(e error) bool { var x *RateLimitError; return errors.As(e, &x) }, []error{ErrRateLimit}},
		{"500", 500, `{"detail":"boom"}`, func(e error) bool { var x *InternalServerError; return errors.As(e, &x) }, []error{ErrInternalServer}},
		{"502 html", 502, `<html>bad gateway</html>`, func(e error) bool { var x *InternalServerError; return errors.As(e, &x) }, []error{ErrInternalServer}},
		{"code daily cap", 429, `{"detail":"cap","code":"daily_cap_exceeded"}`, func(e error) bool { var x *DailyCapExceededError; return errors.As(e, &x) }, []error{ErrDailyCapExceeded, ErrRateLimit}},
		{"code credits on 400", 400, `{"detail":"x","code":"insufficient_credits"}`, func(e error) bool { var x *InsufficientCreditsError; return errors.As(e, &x) }, []error{ErrInsufficientCredits}},
		{"key reused", 422, `{"detail":"x","code":"idempotency_key_reused"}`, func(e error) bool {
			var a *IdempotencyKeyReusedError
			var b *IdempotencyConflictError
			var c *UnprocessableEntityError
			return errors.As(e, &a) && errors.As(e, &b) && errors.As(e, &c)
		}, []error{ErrIdempotencyKeyReused, ErrIdempotencyConflict, ErrUnprocessableEntity}},
		{"in progress", 409, `{"detail":"x","code":"idempotency_in_progress"}`, func(e error) bool {
			var a *IdempotencyInProgressError
			var b *IdempotencyConflictError
			var c *ConflictError
			return errors.As(e, &a) && errors.As(e, &b) && errors.As(e, &c)
		}, []error{ErrIdempotencyInProgress, ErrIdempotencyConflict, ErrConflict}},
		{"replay unavailable", 409, `{"detail":"x","code":"idempotency_replay_unavailable"}`, func(e error) bool {
			var a *IdempotencyReplayUnavailableError
			var c *ConflictError
			return errors.As(e, &a) && errors.As(e, &c)
		}, []error{ErrIdempotencyReplayGone, ErrConflict, ErrIdempotencyConflict}},
		{"unknown code falls back to status", 404, `{"detail":"x","code":"brand_new"}`, func(e error) bool { var x *NotFoundError; return errors.As(e, &x) }, []error{ErrNotFound}},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			err := newAPIError(tc.status, http.Header{}, decodeErrorBody([]byte(tc.body)))
			if !tc.target(err) {
				t.Fatalf("%T does not match", err)
			}
			for _, s := range tc.is {
				if !errors.Is(err, s) {
					t.Errorf("errors.Is(%T, %v) = false", err, s)
				}
			}
			var base *APIError
			var v Error
			if !errors.As(err, &base) || !errors.As(err, &v) || base.StatusCode != tc.status {
				t.Error("every API error unwraps to *APIError and implements Error")
			}
		})
	}
	// Status codes with no dedicated type stay *APIError.
	if _, ok := newAPIError(418, http.Header{}, nil).(*APIError); !ok {
		t.Error("418 should be a bare *APIError")
	}
	if _, ok := newAPIError(405, http.Header{}, nil).(*APIError); !ok {
		t.Error("405 should be a bare *APIError")
	}
	if errors.Is(newAPIError(404, http.Header{}, nil), ErrRateLimit) {
		t.Error("404 is not a rate limit")
	}
}

func TestAPIErrorFields(t *testing.T) {
	h := http.Header{}
	h.Set("X-Request-ID", "hdr_req")
	body := `{"detail":"Too many","code":"rate_limited","requestId":"env_req","retryable":true,"retryAfterSeconds":12.5,"errors":[{"msg":"m"}]}`
	err := newAPIError(429, h, decodeErrorBody([]byte(body)))
	var e *APIError
	if !errors.As(err, &e) {
		t.Fatal("not an APIError")
	}
	if e.Code != "rate_limited" || e.RequestID != "env_req" || e.Retryable == nil || !*e.Retryable ||
		e.RetryAfterSeconds == nil || *e.RetryAfterSeconds != 12.5 || len(e.Errors) != 1 || e.Detail != "Too many" || e.Headers.Get("X-Request-ID") != "hdr_req" {
		t.Errorf("fields = %+v", e)
	}
	if m, ok := e.Body.(map[string]any); !ok || m["code"] != "rate_limited" {
		t.Errorf("Body = %#v", e.Body)
	}
	if got := err.Error(); got != "Too many (status=429, request_id=env_req)" {
		t.Errorf("Error() = %q", got)
	}
	// Header request id is the fallback.
	err = newAPIError(500, h, decodeErrorBody([]byte(`{"title":"Oops"}`)))
	if !strings.Contains(err.Error(), "Oops (status=500, request_id=hdr_req)") {
		t.Errorf("Error() = %q", err.Error())
	}
	err = newAPIError(503, http.Header{}, decodeErrorBody([]byte(``)))
	if !strings.Contains(err.Error(), "HTTP 503") || !strings.Contains(err.Error(), "request_id=none") {
		t.Errorf("Error() = %q", err.Error())
	}
	var base *APIError
	_ = errors.As(err, &base)
	if base.Body != "" {
		t.Errorf("non JSON body should be kept as text, got %#v", base.Body)
	}
}

func TestValidationMessage(t *testing.T) {
	body := `{"detail":"Request validation failed","errors":[
	  {"loc":["body","query"],"msg":"Field required"},
	  {"loc":["query","limit"],"msg":"must be <= 500"},
	  {"loc":["body","filters","state"],"msg":"bad state"},
	  {"loc":["body","extra"],"msg":"fourth"},
	  {"loc":["body","skipped"]},
	  "junk"]}`
	err := newAPIError(422, http.Header{}, decodeErrorBody([]byte(body)))
	want := "Request validation failed: query: Field required; limit: must be <= 500; filters.state: bad state (+3 more)"
	if !strings.HasPrefix(err.Error(), want) {
		t.Errorf("message = %q\nwant prefix %q", err.Error(), want)
	}
	// Only a 422 appends reasons.
	e400 := newAPIError(400, http.Header{}, decodeErrorBody([]byte(body)))
	if strings.Contains(e400.Error(), "Field required") {
		t.Error("a 400 must not append validation reasons")
	}
	if got := validationSummary("nope"); got != "" {
		t.Errorf("non-list: %q", got)
	}
	if got := validationSummary([]any{map[string]any{"msg": "alone"}}); got != "alone" {
		t.Errorf("no loc: %q", got)
	}
	if got := validationSummary([]any{map[string]any{"loc": []any{"body"}, "msg": "top"}}); got != "body: top" {
		t.Errorf("single loc keeps body: %q", got)
	}
	if got := validationSummary([]any{}); got != "" {
		t.Errorf("empty: %q", got)
	}
}

func TestEndToEndErrorFromServer(t *testing.T) {
	f := newFake(t, func(w http.ResponseWriter, r *http.Request, n int) {
		w.Header().Set("X-Request-ID", "rid")
		writeJSON(w, 404, `{"detail":"Section not found","code":"not_found"}`)
	})
	c, _ := newTestClient(t, f)
	_, err := c.Statutes.GetSection(context.Background(), "nope")
	var nf *NotFoundError
	if !errors.As(err, &nf) || nf.RequestID != "rid" || nf.StatusCode != 404 {
		t.Fatalf("err = %v", err)
	}
	if len(f.requests()) != 1 {
		t.Error("a 404 must not be retried")
	}
}

func TestSpendGuardErrorShape(t *testing.T) {
	e := &SpendGuardError{Spent: 5, Limit: 5}
	if e.Error() != "Spend guard reached: 5 of 5 credits used." || !errors.Is(e, ErrSpendGuard) {
		t.Errorf("%v", e)
	}
	var v Error = e
	_ = v
}
