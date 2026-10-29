package vaquill

import (
	"errors"
	"fmt"
	"net/http"
	"strings"
)

// Error is implemented by every error this SDK returns. Use errors.As to test for it.
type Error interface {
	error
	vaquillError()
}

// Sentinels for errors.Is. Each typed API error wraps the sentinels of the classes it belongs to.
var (
	ErrBadRequest                  = errors.New("vaquill: bad request")
	ErrAuthentication              = errors.New("vaquill: authentication failed")
	ErrInsufficientCredits         = errors.New("vaquill: insufficient credits")
	ErrPermissionDenied            = errors.New("vaquill: permission denied")
	ErrNotFound                    = errors.New("vaquill: not found")
	ErrConflict                    = errors.New("vaquill: conflict")
	ErrUnprocessableEntity         = errors.New("vaquill: unprocessable entity")
	ErrRateLimit                   = errors.New("vaquill: rate limited")
	ErrDailyCapExceeded            = errors.New("vaquill: daily cap exceeded")
	ErrInternalServer              = errors.New("vaquill: server error")
	ErrIdempotencyConflict         = errors.New("vaquill: idempotency conflict")
	ErrIdempotencyKeyReused        = errors.New("vaquill: idempotency key reused")
	ErrIdempotencyInProgress       = errors.New("vaquill: idempotency request in progress")
	ErrIdempotencyReplayGone       = errors.New("vaquill: idempotent replay unavailable")
	ErrSpendGuard                  = errors.New("vaquill: spend guard reached")
	ErrResponseParse               = errors.New("vaquill: response parse error")
	ErrWebhookVerification         = errors.New("vaquill: webhook verification failed")
	ErrEmptyWebhookSecret          = errors.New("vaquill: the webhook secret is empty or blank")
	ErrInvalidWebhookSecret        = errors.New("vaquill: the webhook secret is not valid base64 after the whsec_ prefix")
	_                        Error = (*APIError)(nil)
)

// ConfigError reports invalid client configuration or call arguments (a bad API key,
// an invalid idempotency key or path segment, a negative retry count).
type ConfigError struct{ Message string }

func (e *ConfigError) Error() string { return e.Message }
func (*ConfigError) vaquillError()   {}

func errNilRequest(name string) error {
	return &ConfigError{Message: fmt.Sprintf("vaquill: the %s request must not be nil", name)}
}

// SpendGuardError is returned, without sending a request, when the WithMaxCredits cap is reached.
type SpendGuardError struct {
	Spent, Limit float64
}

func (e *SpendGuardError) Error() string {
	return fmt.Sprintf("Spend guard reached: %g of %g credits used.", e.Spent, e.Limit)
}
func (*SpendGuardError) vaquillError() {}

// Unwrap lets errors.Is(err, ErrSpendGuard) match.
func (*SpendGuardError) Unwrap() error { return ErrSpendGuard }

// ConnectionError means the request never produced an HTTP response.
type ConnectionError struct {
	Message string
	Cause   error
}

func (e *ConnectionError) Error() string {
	if e.Cause != nil {
		return e.Message + ": " + e.Cause.Error()
	}
	return e.Message
}
func (*ConnectionError) vaquillError() {}

// Unwrap returns the transport error.
func (e *ConnectionError) Unwrap() error { return e.Cause }

// TimeoutError is a ConnectionError raised when the per-attempt timeout elapsed.
type TimeoutError struct{ *ConnectionError }

// Timeout reports true, so the error satisfies net.Error-style checks.
func (*TimeoutError) Timeout() bool { return true }

// Unwrap exposes both the ConnectionError and the underlying cause.
func (e *TimeoutError) Unwrap() []error { return []error{e.ConnectionError} }

// ResponseParseError means a 2xx body was not valid JSON or did not match the expected shape.
type ResponseParseError struct {
	Message    string
	RequestID  string
	StatusCode int
	Cause      error
}

func (e *ResponseParseError) Error() string {
	return fmt.Sprintf("%s (status=%d, request_id=%s)", e.Message, e.StatusCode, orNone(e.RequestID))
}
func (*ResponseParseError) vaquillError() {}

// Unwrap returns the decoding error and ErrResponseParse.
func (e *ResponseParseError) Unwrap() []error {
	if e.Cause != nil {
		return []error{e.Cause, ErrResponseParse}
	}
	return []error{ErrResponseParse}
}

// WebhookVerificationError means a webhook delivery failed signature or timestamp verification.
type WebhookVerificationError struct{ Message string }

func (e *WebhookVerificationError) Error() string { return e.Message }
func (*WebhookVerificationError) vaquillError()   {}
func (*WebhookVerificationError) Unwrap() error   { return ErrWebhookVerification }
func newWebhookError(msg string) *WebhookVerificationError {
	return &WebhookVerificationError{Message: msg}
}

// WebhookPayloadError means the signature matched but the body is not a Vaquill event.
type WebhookPayloadError struct{ *WebhookVerificationError }

// APIError is the server answering with a 4xx or 5xx status. The concrete error returned is one
// of the typed wrappers below (RateLimitError, NotFoundError, ...), all of which unwrap to *APIError.
type APIError struct {
	Message    string
	StatusCode int
	// Code is the machine code from the envelope (for example "rate_limited"), or empty.
	Code string
	// RequestID comes from the envelope, falling back to the X-Request-ID header.
	RequestID string
	// Retryable is the server's verdict when it gave one.
	Retryable *bool
	// RetryAfterSeconds is the wait the envelope asked for, when present.
	RetryAfterSeconds *float64
	// Detail is the legacy envelope member, unchanged.
	Detail any
	// Errors is the validation error list of a 422, when present.
	Errors []any
	// Body is the decoded JSON body, or the raw text when it was not JSON.
	Body    any
	Headers http.Header
}

func (e *APIError) Error() string {
	return fmt.Sprintf("%s (status=%d, request_id=%s)", e.Message, e.StatusCode, orNone(e.RequestID))
}
func (*APIError) vaquillError() {}

func orNone(s string) string {
	if s == "" {
		return "none"
	}
	return s
}

// Typed status errors. Each embeds the shared *APIError, so err.Code, err.RequestID and the
// rest are available on the typed value, and errors.As(err, &apiErr) works for any of them.
type (
	// BadRequestError is a 400.
	BadRequestError struct{ *APIError }
	// AuthenticationError is a 401.
	AuthenticationError struct{ *APIError }
	// InsufficientCreditsError is a 402. Never retried.
	InsufficientCreditsError struct{ *APIError }
	// PermissionDeniedError is a 403.
	PermissionDeniedError struct{ *APIError }
	// NotFoundError is a 404.
	NotFoundError struct{ *APIError }
	// ConflictError is a 409.
	ConflictError struct{ *APIError }
	// UnprocessableEntityError is a 422.
	UnprocessableEntityError struct{ *APIError }
	// RateLimitError is a 429. RetryAfterSeconds is set when the server said how long to wait.
	RateLimitError struct{ *APIError }
	// DailyCapExceededError is a per-key daily cap (a RateLimitError). Retrying cannot succeed until the cap resets.
	DailyCapExceededError struct{ *APIError }
	// InternalServerError is any 5xx.
	InternalServerError struct{ *APIError }
	// IdempotencyConflictError is the base of the three idempotency codes.
	IdempotencyConflictError struct{ *APIError }
	// IdempotencyKeyReusedError means the same key was sent with a different request. It is also an UnprocessableEntityError.
	IdempotencyKeyReusedError struct{ *APIError }
	// IdempotencyInProgressError means the original request is still running. Retryable. It is also a ConflictError.
	IdempotencyInProgressError struct{ *APIError }
	// IdempotencyReplayUnavailableError means the original completed but its response is too large to replay.
	// The call was not charged again; check Credits.Balance before retrying. It is also a ConflictError.
	IdempotencyReplayUnavailableError struct{ *APIError }
)

func (e *BadRequestError) Unwrap() []error     { return []error{e.APIError, ErrBadRequest} }
func (e *AuthenticationError) Unwrap() []error { return []error{e.APIError, ErrAuthentication} }
func (e *InsufficientCreditsError) Unwrap() []error {
	return []error{e.APIError, ErrInsufficientCredits}
}
func (e *PermissionDeniedError) Unwrap() []error { return []error{e.APIError, ErrPermissionDenied} }
func (e *NotFoundError) Unwrap() []error         { return []error{e.APIError, ErrNotFound} }
func (e *ConflictError) Unwrap() []error         { return []error{e.APIError, ErrConflict} }
func (e *UnprocessableEntityError) Unwrap() []error {
	return []error{e.APIError, ErrUnprocessableEntity}
}
func (e *RateLimitError) Unwrap() []error { return []error{e.APIError, ErrRateLimit} }
func (e *DailyCapExceededError) Unwrap() []error {
	return []error{&RateLimitError{e.APIError}, ErrDailyCapExceeded}
}
func (e *InternalServerError) Unwrap() []error { return []error{e.APIError, ErrInternalServer} }
func (e *IdempotencyConflictError) Unwrap() []error {
	return []error{e.APIError, ErrIdempotencyConflict}
}
func (e *IdempotencyKeyReusedError) Unwrap() []error {
	return []error{&IdempotencyConflictError{e.APIError}, &UnprocessableEntityError{e.APIError}, ErrIdempotencyKeyReused}
}
func (e *IdempotencyInProgressError) Unwrap() []error {
	return []error{&IdempotencyConflictError{e.APIError}, &ConflictError{e.APIError}, ErrIdempotencyInProgress}
}
func (e *IdempotencyReplayUnavailableError) Unwrap() []error {
	return []error{&IdempotencyConflictError{e.APIError}, &ConflictError{e.APIError}, ErrIdempotencyReplayGone}
}

// Codes the server marks retryable. Anything else is not retried on a code basis.
var retryableCodes = map[string]bool{
	"rate_limited": true, "idempotency_in_progress": true, "upstream_timeout": true,
	"service_unavailable": true, "internal_error": true,
}

var neverRetryCodes = map[string]bool{"insufficient_credits": true, "daily_cap_exceeded": true}

func envelope(body any) map[string]any {
	m, _ := body.(map[string]any)
	return m
}

func strField(m map[string]any, k string) string {
	s, _ := m[k].(string)
	return s
}

// newAPIError maps a response to the most specific error type. Code wins over status.
func newAPIError(status int, header http.Header, body any) error {
	env := envelope(body)
	e := &APIError{
		Message:    errorMessage(status, env),
		StatusCode: status,
		Body:       body,
		Headers:    header,
		Code:       strField(env, "code"),
		RequestID:  strField(env, "requestId"),
		Detail:     env["detail"],
	}
	if e.RequestID == "" {
		e.RequestID = header.Get(requestIDHeader)
	}
	if r, ok := env["retryable"].(bool); ok {
		e.Retryable = &r
	}
	if f, ok := env["retryAfterSeconds"].(float64); ok {
		e.RetryAfterSeconds = &f
	}
	if l, ok := env["errors"].([]any); ok {
		e.Errors = l
	}
	switch e.Code {
	case "insufficient_credits":
		return &InsufficientCreditsError{e}
	case "daily_cap_exceeded":
		return &DailyCapExceededError{e}
	case "idempotency_key_reused":
		return &IdempotencyKeyReusedError{e}
	case "idempotency_in_progress":
		return &IdempotencyInProgressError{e}
	case "idempotency_replay_unavailable":
		return &IdempotencyReplayUnavailableError{e}
	}
	switch {
	case status >= 500:
		return &InternalServerError{e}
	case status == 400:
		return &BadRequestError{e}
	case status == 401:
		return &AuthenticationError{e}
	case status == 402:
		return &InsufficientCreditsError{e}
	case status == 403:
		return &PermissionDeniedError{e}
	case status == 404:
		return &NotFoundError{e}
	case status == 409:
		return &ConflictError{e}
	case status == 422:
		return &UnprocessableEntityError{e}
	case status == 429:
		return &RateLimitError{e}
	}
	return e
}

func errorMessage(status int, env map[string]any) string {
	if detail, ok := env["detail"].(string); ok && detail != "" {
		if status == 422 {
			if why := validationSummary(env["errors"]); why != "" {
				return detail + ": " + why
			}
		}
		return detail
	}
	if title, ok := env["title"].(string); ok && title != "" {
		return title
	}
	return fmt.Sprintf("HTTP %d", status)
}

// validationSummary renders the first three "loc: msg" pairs of a 422 errors list.
func validationSummary(errs any) string {
	items, ok := errs.([]any)
	if !ok {
		return ""
	}
	var parts []string
	for _, raw := range items {
		item, ok := raw.(map[string]any)
		if !ok {
			continue
		}
		msg, _ := item["msg"].(string)
		if msg == "" {
			continue
		}
		loc, _ := item["loc"].([]any)
		if len(loc) > 1 {
			switch fmt.Sprint(loc[0]) {
			case "body", "query", "path", "header":
				loc = loc[1:]
			}
		}
		segs := make([]string, len(loc))
		for i, l := range loc {
			segs[i] = fmt.Sprint(l)
		}
		if where := strings.Join(segs, "."); where != "" {
			parts = append(parts, where+": "+msg)
		} else {
			parts = append(parts, msg)
		}
	}
	if len(parts) == 0 {
		return ""
	}
	shown := len(parts)
	if shown > 3 {
		shown = 3
	}
	out := strings.Join(parts[:shown], "; ")
	if more := len(items) - shown; more > 0 {
		out += fmt.Sprintf(" (+%d more)", more)
	}
	return out
}
