package vaquill

import (
	"net/http"
	"strings"
	"time"
)

type clientConfig struct {
	apiKey          string
	apiKeySet       bool
	baseURL         string
	timeout         time.Duration
	timeoutSet      bool
	maxRetries      int
	maxRetriesSet   bool
	httpClient      *http.Client
	headers         map[string]string // lower-case names
	userAgentSuffix string
	maxCredits      *float64
	noIdempotency   bool
	logger          Logger
}

// Option configures a Client (NewClient) or a derived copy (Client.WithOptions).
type Option func(*clientConfig)

// WithAPIKey sets the API key. Without it the client reads VAQUILL_API_KEY.
func WithAPIKey(key string) Option {
	return func(c *clientConfig) { c.apiKey, c.apiKeySet = key, true }
}

// WithBaseURL overrides the API origin (default https://api.vaquill.ai, or VAQUILL_BASE_URL).
func WithBaseURL(u string) Option { return func(c *clientConfig) { c.baseURL = u } }

// WithTimeout bounds each attempt, including reading the body. Zero disables the timeout
// (the caller's context still applies). The default is 60 seconds.
func WithTimeout(d time.Duration) Option {
	return func(c *clientConfig) { c.timeout, c.timeoutSet = d, true }
}

// WithMaxRetries sets the retries after the first attempt (default 2). Zero disables retrying.
func WithMaxRetries(n int) Option {
	return func(c *clientConfig) { c.maxRetries, c.maxRetriesSet = n, true }
}

// WithHTTPClient supplies the http.Client used for every request. The client is never closed by the SDK.
func WithHTTPClient(h *http.Client) Option { return func(c *clientConfig) { c.httpClient = h } }

// WithDefaultHeaders adds headers to every request. Names are case-insensitive and later
// values win. Authorization and Idempotency-Key cannot be overridden.
func WithDefaultHeaders(h map[string]string) Option {
	return func(c *clientConfig) {
		if c.headers == nil {
			c.headers = map[string]string{}
		}
		for k, v := range h {
			c.headers[strings.ToLower(k)] = v
		}
	}
}

// WithUserAgentSuffix appends a token (for example your app and version) to the User-Agent.
func WithUserAgentSuffix(s string) Option { return func(c *clientConfig) { c.userAgentSuffix = s } }

// WithMaxCredits sets a client-side spend guard. Once the credits consumed by charged calls
// reach max, further charged calls fail with *SpendGuardError before anything is sent. While a
// cap is set, charged calls are serialised so the check is exact. The total is shared with
// clients derived through WithOptions.
func WithMaxCredits(max float64) Option { return func(c *clientConfig) { c.maxCredits = &max } }

// WithoutMaxCredits removes a spend guard inherited from the client being derived from.
func WithoutMaxCredits() Option { return func(c *clientConfig) { c.maxCredits = nil } }

// WithAutoIdempotencyKeys controls whether charged calls get a generated Idempotency-Key
// (default true). Disabling it also disables automatic retry of 5xx answers on charged calls.
func WithAutoIdempotencyKeys(enabled bool) Option {
	return func(c *clientConfig) { c.noIdempotency = !enabled }
}

// WithLogger sets the logger for debug output and warnings. *slog.Logger satisfies Logger.
// The API key is redacted from everything logged.
func WithLogger(l Logger) Option { return func(c *clientConfig) { c.logger = l } }

type callConfig struct {
	timeout        *time.Duration
	maxRetries     *int
	idempotencyKey *string
	headers        map[string]string
	info           *ResponseInfo
}

// CallOption adjusts a single call.
type CallOption func(*callConfig)

// WithRequestTimeout overrides the per-attempt timeout for this call. Zero disables it.
func WithRequestTimeout(d time.Duration) CallOption { return func(c *callConfig) { c.timeout = &d } }

// WithRequestMaxRetries overrides the retry count for this call.
func WithRequestMaxRetries(n int) CallOption { return func(c *callConfig) { c.maxRetries = &n } }

// WithIdempotencyKey sets the Idempotency-Key for this call: 16 to 255 visible ASCII characters.
// It is reused across every retry of the call. Charged calls get a generated key when this is not set.
func WithIdempotencyKey(key string) CallOption {
	return func(c *callConfig) { c.idempotencyKey = &key }
}

// WithRequestHeader adds a header to this call (case-insensitive name).
func WithRequestHeader(name, value string) CallOption {
	return func(c *callConfig) {
		if c.headers == nil {
			c.headers = map[string]string{}
		}
		c.headers[strings.ToLower(name)] = value
	}
}

// WithResponse fills info with the status, headers, request id, credits consumed and replay
// flag of the successful response.
func WithResponse(info *ResponseInfo) CallOption { return func(c *callConfig) { c.info = info } }

func newCallConfig(opts []CallOption) *callConfig {
	c := &callConfig{}
	for _, o := range opts {
		if o != nil {
			o(c)
		}
	}
	return c
}
