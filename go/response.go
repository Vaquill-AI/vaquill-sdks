package vaquill

import (
	"net/http"
	"strconv"
	"strings"
)

// RateLimit is the parsed X-RateLimit-* headers. A nil member means the server omitted it.
type RateLimit struct {
	Limit        *int
	Remaining    *int
	Reset        *float64
	LimitDay     *int
	RemainingDay *int
	ResetDay     *float64
}

func headerInt(h http.Header, k string) *int {
	v, err := strconv.Atoi(strings.TrimSpace(h.Get(k)))
	if err != nil {
		return nil
	}
	return &v
}

func headerFloat(h http.Header, k string) *float64 {
	v, err := strconv.ParseFloat(strings.TrimSpace(h.Get(k)), 64)
	if err != nil {
		return nil
	}
	return &v
}

func rateLimitFrom(h http.Header) RateLimit {
	return RateLimit{
		Limit: headerInt(h, "X-RateLimit-Limit"), Remaining: headerInt(h, "X-RateLimit-Remaining"),
		Reset: headerFloat(h, "X-RateLimit-Reset"), LimitDay: headerInt(h, "X-RateLimit-Limit-Day"),
		RemainingDay: headerInt(h, "X-RateLimit-Remaining-Day"), ResetDay: headerFloat(h, "X-RateLimit-Reset-Day"),
	}
}

// ResponseInfo is the metadata of a successful call. Pass a pointer to WithResponse to receive it.
type ResponseInfo struct {
	StatusCode int
	Header     http.Header
	// Body is the raw response body.
	Body      []byte
	RequestID string
	// CreditsConsumed is creditsConsumed from the body (top level, else meta.creditsConsumed), or nil.
	CreditsConsumed *float64
	// IdempotentReplayed is true when the server replayed a stored response (Idempotent-Replayed: true).
	IdempotentReplayed bool
	RateLimit          RateLimit
}

// CreditsChargedThisCall is zero on an idempotent replay, otherwise CreditsConsumed (0 when absent).
func (r *ResponseInfo) CreditsChargedThisCall() float64 {
	if r.IdempotentReplayed || r.CreditsConsumed == nil {
		return 0
	}
	return *r.CreditsConsumed
}
