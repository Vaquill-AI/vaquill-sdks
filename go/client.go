package vaquill

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"math/rand/v2"
	"net"
	"net/http"
	"net/url"
	"os"
	"runtime"
	"strings"
	"sync"
	"time"
)

// spendTracker is the running total of credits a client (and clients derived from it) consumed.
type spendTracker struct {
	mu    sync.Mutex
	total float64
	// serial is held from the spend check until a charged call is counted while a cap is set.
	serial chan struct{}
}

func newSpendTracker() *spendTracker { return &spendTracker{serial: make(chan struct{}, 1)} }

func (s *spendTracker) add(v float64) {
	s.mu.Lock()
	s.total += v
	s.mu.Unlock()
}

func (s *spendTracker) get() float64 {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.total
}

type request struct {
	op      string
	method  string
	path    string
	query   url.Values
	body    any
	charged bool
}

// Client is the Vaquill API client. It is safe for concurrent use.
type Client struct {
	cfg      clientConfig
	http     *http.Client
	ownsHTTP bool
	spend    *spendTracker
	logger   Logger

	depMu sync.Mutex
	dep   map[string]bool

	// Test seams.
	sleep func(ctx context.Context, d time.Duration) error
	rnd   func() float64
	now   func() time.Time

	// Statutes serves the US statutes corpus.
	Statutes *StatutesService
	// SessionLaws serves acts as enacted.
	SessionLaws *SessionLawsService
	// Watches manages law-change alerts.
	Watches *WatchesService
	// Boards lists the sources a watch can follow.
	Boards *BoardsService
	// Credits reports the credit balance.
	Credits *CreditsService
	// Pricing reports the credit price of every endpoint.
	Pricing *PricingService
}

// NewClient builds a client. It returns a *ConfigError for a missing or malformed API key.
func NewClient(opts ...Option) (*Client, error) { return build(clientConfig{}, nil, nil, opts) }

// WithOptions returns a copy with overrides. It shares the HTTP client (unless WithHTTPClient is
// given) and the spend total with the original.
func (c *Client) WithOptions(opts ...Option) (*Client, error) {
	return build(c.cfg, c.http, c.spend, opts)
}

func build(base clientConfig, shared *http.Client, spend *spendTracker, opts []Option) (*Client, error) {
	cfg := base
	cfg.headers = make(map[string]string, len(base.headers))
	for k, v := range base.headers {
		cfg.headers[k] = v
	}
	for _, o := range opts {
		if o != nil {
			o(&cfg)
		}
	}
	key := cfg.apiKey
	if !cfg.apiKeySet && key == "" {
		key = os.Getenv(APIKeyEnv)
	}
	key = strings.TrimSpace(key)
	if key == "" {
		return nil, &ConfigError{Message: "No API key. Pass WithAPIKey(...) or set the " + APIKeyEnv + " variable."}
	}
	for i := 0; i < len(key); i++ {
		if key[i] < 33 || key[i] > 126 {
			return nil, &ConfigError{Message: "Invalid API key: it contains control, whitespace or non-ASCII characters. Check for a stray newline or quote in the value."}
		}
	}
	if !strings.HasPrefix(key, apiKeyPrefix) {
		return nil, &ConfigError{Message: "Invalid API key: Vaquill keys start with '" + apiKeyPrefix + "'."}
	}
	cfg.apiKey, cfg.apiKeySet = key, true
	if cfg.maxRetries < 0 {
		return nil, &ConfigError{Message: "max retries must be >= 0."}
	}
	if cfg.timeout < 0 {
		return nil, &ConfigError{Message: "timeout must be >= 0 (0 disables it)."}
	}
	if !cfg.maxRetriesSet {
		cfg.maxRetries = DefaultMaxRetries
	}
	if !cfg.timeoutSet {
		cfg.timeout = DefaultTimeout
	}
	base2 := cfg.baseURL
	if base2 == "" {
		base2 = os.Getenv(BaseURLEnv)
	}
	if base2 == "" {
		base2 = DefaultBaseURL
	}
	base2 = strings.TrimRight(base2, "/")
	u, err := url.Parse(base2)
	if err != nil || u.Scheme == "" || u.Host == "" {
		return nil, &ConfigError{Message: fmt.Sprintf("invalid base URL %q", base2)}
	}
	cfg.baseURL = base2
	if cfg.maxCredits != nil && *cfg.maxCredits < 0 {
		return nil, &ConfigError{Message: "max credits must be >= 0."}
	}

	c := &Client{cfg: cfg, dep: map[string]bool{}}
	switch {
	case cfg.httpClient != nil:
		c.http = cfg.httpClient
	case shared != nil:
		c.http = shared
	default:
		c.http, c.ownsHTTP = defaultHTTPClient(), true
	}
	c.spend = spend
	if c.spend == nil {
		c.spend = newSpendTracker()
	}
	inner := cfg.logger
	if inner == nil {
		inner = stdWarnLogger{}
	}
	c.logger = redactor{inner: inner, key: key}
	c.sleep = sleepCtx
	c.rnd = rand.Float64
	c.now = time.Now
	c.Statutes = &StatutesService{c}
	c.SessionLaws = &SessionLawsService{c}
	c.Watches = &WatchesService{c}
	c.Boards = &BoardsService{c}
	c.Credits = &CreditsService{c}
	c.Pricing = &PricingService{c}
	return c, nil
}

func defaultHTTPClient() *http.Client {
	t := http.DefaultTransport.(*http.Transport).Clone()
	t.DialContext = (&net.Dialer{Timeout: defaultConnectTimeout, KeepAlive: 30 * time.Second}).DialContext
	return &http.Client{Transport: t}
}

func sleepCtx(ctx context.Context, d time.Duration) error {
	if d <= 0 {
		return ctx.Err()
	}
	t := time.NewTimer(d)
	defer t.Stop()
	select {
	case <-ctx.Done():
		return ctx.Err()
	case <-t.C:
		return nil
	}
}

// Close releases idle connections of the HTTP client the SDK created. A client passed with
// WithHTTPClient is left alone.
func (c *Client) Close() {
	if c.ownsHTTP {
		c.http.CloseIdleConnections()
	}
}

// BaseURL is the origin requests are sent to.
func (c *Client) BaseURL() string { return c.cfg.baseURL }

// CreditsSpent is the credits consumed by charged calls since construction, shared with derived clients.
func (c *Client) CreditsSpent() float64 { return c.spend.get() }

func userAgent(suffix string) string {
	ua := fmt.Sprintf("vaquill-go/%s go/%s %s", Version, strings.TrimPrefix(runtime.Version(), "go"), runtime.GOOS)
	if suffix = strings.TrimSpace(suffix); suffix != "" {
		ua += " " + suffix
	}
	return ua
}

func (c *Client) headers(key string, extra map[string]string) map[string]string {
	h := map[string]string{"user-agent": userAgent(c.cfg.userAgentSuffix), "accept": "application/json"}
	for _, src := range []map[string]string{c.cfg.headers, extra} {
		for k, v := range src {
			if k != "authorization" && k != "idempotency-key" {
				h[k] = v
			}
		}
	}
	h["authorization"] = "Bearer " + c.cfg.apiKey
	if key != "" {
		h["idempotency-key"] = key
	}
	return h
}

func (c *Client) checkSpend(charged bool) error {
	if charged && c.cfg.maxCredits != nil {
		if spent := c.spend.get(); spent >= *c.cfg.maxCredits {
			return &SpendGuardError{Spent: spent, Limit: *c.cfg.maxCredits}
		}
	}
	return nil
}

// do sends one logical request: spend guard, idempotency key, retries, error mapping.
func (c *Client) do(ctx context.Context, r request, out any, opts []CallOption) error {
	call := newCallConfig(opts)
	if ctx == nil {
		ctx = context.Background()
	}
	if r.charged && c.cfg.maxCredits != nil {
		// Check-then-act must be exact: hold the lock from the check until the call is counted.
		select {
		case c.spend.serial <- struct{}{}:
		case <-ctx.Done():
			return ctx.Err()
		}
		defer func() { <-c.spend.serial }()
	}
	if err := c.checkSpend(r.charged); err != nil {
		return err
	}
	key := ""
	switch {
	case call.idempotencyKey != nil:
		if err := validateIdempotencyKey(*call.idempotencyKey); err != nil {
			return err
		}
		key = *call.idempotencyKey
	case r.charged && !c.cfg.noIdempotency:
		key = newIdempotencyKey()
	}
	return c.execute(ctx, r, out, call, key)
}

func (c *Client) execute(ctx context.Context, r request, out any, call *callConfig, key string) error {
	retries := c.cfg.maxRetries
	if call.maxRetries != nil {
		retries = *call.maxRetries
	}
	if retries < 0 {
		return &ConfigError{Message: "max retries must be >= 0."}
	}
	timeout := c.cfg.timeout
	if call.timeout != nil {
		timeout = *call.timeout
	}
	var payload []byte
	if r.body != nil {
		var buf bytes.Buffer
		enc := json.NewEncoder(&buf)
		enc.SetEscapeHTML(false)
		if err := enc.Encode(r.body); err != nil {
			return &ConfigError{Message: "cannot encode the request body: " + err.Error()}
		}
		payload = bytes.TrimRight(buf.Bytes(), "\n")
	}
	target := c.cfg.baseURL + r.path
	if len(r.query) > 0 {
		target += "?" + r.query.Encode()
	}
	hdr := c.headers(key, call.headers)
	if payload != nil {
		hdr["content-type"] = "application/json"
	}
	for attempt := 0; ; attempt++ {
		c.logger.Debug("request", "method", r.method, "url", target, "idempotency_key", redactOrEmpty(key))
		status, header, data, err := c.send(ctx, r.method, target, hdr, payload, timeout)
		if err != nil {
			if ctx.Err() != nil {
				return ctx.Err()
			}
			if attempt < retries && connectionRetryable(err, r.method, key != "") {
				if serr := c.retryWait(ctx, "transport error", backoffDelay(attempt, c.rnd), attempt, retries); serr != nil {
					return serr
				}
				continue
			}
			ce := &ConnectionError{Message: "Connection error", Cause: err}
			if isTimeout(err) {
				ce.Message = "Request timed out"
				return &TimeoutError{ce}
			}
			return ce
		}
		c.noteDeprecation(r.method, r.path, header)
		if status >= 200 && status < 300 {
			return c.finish(status, header, data, r.charged, out, call, key)
		}
		apiErr := newAPIError(status, header, decodeErrorBody(data))
		if attempt < retries {
			base := baseAPIError(apiErr)
			replaySafe := key != "" || !r.charged
			if d, ok := delayForStatus(base, attempt, replaySafe, c.now(), c.rnd); ok {
				if serr := c.retryWait(ctx, fmt.Sprintf("status %d", status), d, attempt, retries); serr != nil {
					return serr
				}
				continue
			}
		}
		return apiErr
	}
}

func redactOrEmpty(key string) string {
	if key == "" {
		return ""
	}
	return redactKey(key)
}

func (c *Client) retryWait(ctx context.Context, why string, d time.Duration, attempt, retries int) error {
	c.logger.Debug("retrying", "why", why, "delay", d.String(), "retry", fmt.Sprintf("%d of %d", attempt+1, retries))
	return c.sleep(ctx, d)
}

func isTimeout(err error) bool {
	type timeouter interface{ Timeout() bool }
	for e := err; e != nil; {
		if e == context.DeadlineExceeded {
			return true
		}
		if t, ok := e.(timeouter); ok && t.Timeout() {
			return true
		}
		u, ok := e.(interface{ Unwrap() error })
		if !ok {
			break
		}
		e = u.Unwrap()
	}
	return false
}

func baseAPIError(err error) *APIError {
	type embedded interface{ Unwrap() []error }
	if a, ok := err.(*APIError); ok {
		return a
	}
	if u, ok := err.(embedded); ok {
		for _, e := range u.Unwrap() {
			if a, ok := e.(*APIError); ok {
				return a
			}
		}
	}
	return &APIError{}
}

func (c *Client) send(ctx context.Context, method, target string, hdr map[string]string, payload []byte, timeout time.Duration) (int, http.Header, []byte, error) {
	if timeout > 0 {
		var cancel context.CancelFunc
		ctx, cancel = context.WithTimeout(ctx, timeout)
		defer cancel()
	}
	var body io.Reader
	if payload != nil {
		body = bytes.NewReader(payload)
	}
	req, err := http.NewRequestWithContext(ctx, method, target, body)
	if err != nil {
		return 0, nil, nil, &ConfigError{Message: "invalid request: " + err.Error()}
	}
	for k, v := range hdr {
		req.Header.Set(k, v)
	}
	resp, err := c.http.Do(req)
	if err != nil {
		return 0, nil, nil, err
	}
	defer resp.Body.Close()
	data, err := io.ReadAll(resp.Body)
	if err != nil {
		return 0, nil, nil, err
	}
	return resp.StatusCode, resp.Header, data, nil
}

func decodeErrorBody(data []byte) any {
	var v any
	if err := json.Unmarshal(data, &v); err != nil || v == nil {
		return string(data)
	}
	return v
}

func (c *Client) noteDeprecation(method, path string, h http.Header) {
	dep, sun := h.Get("Deprecation"), h.Get("Sunset")
	if dep == "" && sun == "" {
		return
	}
	seen := method + " " + path
	c.depMu.Lock()
	if c.dep[seen] {
		c.depMu.Unlock()
		return
	}
	c.dep[seen] = true
	c.depMu.Unlock()
	var parts []string
	if dep != "" {
		parts = append(parts, "Deprecation: "+dep)
	}
	if sun != "" {
		parts = append(parts, "Sunset: "+sun)
	}
	c.logger.Warn(fmt.Sprintf("%s %s is deprecated (%s).", method, path, strings.Join(parts, ", ")))
}

// rawBody receives the undecoded response body instead of a decoded value.
type rawBody []byte

func creditsFromBody(data []byte) *float64 {
	var probe struct {
		CreditsConsumed *float64 `json:"creditsConsumed"`
		Meta            *struct {
			CreditsConsumed *float64 `json:"creditsConsumed"`
		} `json:"meta"`
	}
	if json.Unmarshal(data, &probe) != nil {
		// A body whose members have unexpected types: read what can be read member by member.
		var loose map[string]json.RawMessage
		if json.Unmarshal(data, &loose) != nil {
			return nil
		}
		var v float64
		if json.Unmarshal(loose["creditsConsumed"], &v) == nil {
			return &v
		}
		return nil
	}
	if probe.CreditsConsumed != nil {
		return probe.CreditsConsumed
	}
	if probe.Meta != nil {
		return probe.Meta.CreditsConsumed
	}
	return nil
}

func (c *Client) finish(status int, h http.Header, data []byte, charged bool, out any, call *callConfig, key string) error {
	if strings.EqualFold(h.Get(idempotencyStatusHeader), "unavailable") {
		c.logger.Warn("Server could not deduplicate this request (idempotency store unavailable).")
	}
	info := &ResponseInfo{
		StatusCode: status, Header: h, Body: data, RequestID: h.Get(requestIDHeader),
		IdempotentReplayed: strings.EqualFold(h.Get(replayedHeader), "true"), RateLimit: rateLimitFrom(h),
	}
	trimmed := bytes.TrimSpace(data)
	if len(trimmed) > 0 {
		if !json.Valid(trimmed) {
			if call.info != nil {
				*call.info = *info
			}
			return &ResponseParseError{Message: fmt.Sprintf("Response was not valid JSON (status %d).", status), RequestID: info.RequestID, StatusCode: status}
		}
		info.CreditsConsumed = creditsFromBody(trimmed)
	}
	if charged {
		c.spend.add(info.CreditsChargedThisCall())
	}
	c.logger.Debug("response", "status", status, "idempotency_key", redactOrEmpty(key))
	if call.info != nil {
		*call.info = *info
	}
	if out == nil {
		return nil
	}
	if rb, ok := out.(*rawBody); ok {
		*rb = append((*rb)[:0], trimmed...)
		return nil
	}
	if len(trimmed) == 0 || string(trimmed) == "null" {
		return &ResponseParseError{Message: "Response had no body where one was expected.", RequestID: info.RequestID, StatusCode: status}
	}
	if err := json.Unmarshal(trimmed, out); err != nil {
		return &ResponseParseError{Message: "Response did not match the expected shape: " + err.Error(), RequestID: info.RequestID, StatusCode: status, Cause: err}
	}
	return nil
}

// RawRequest describes a call to an endpoint newer than this SDK.
type RawRequest struct {
	Method string
	// Path is the path after the origin, for example "/api/v1/us/statutes/coverage". It is used as given.
	Path    string
	Query   url.Values
	Body    any
	Charged bool
}

// Raw is the escape hatch for endpoints newer than this SDK. The body comes back undecoded in
// ResponseInfo.Body. Charged calls get an idempotency key and count toward the spend guard.
func (c *Client) Raw(ctx context.Context, r RawRequest, opts ...CallOption) (*ResponseInfo, error) {
	var info ResponseInfo
	opts = append(append([]CallOption(nil), opts...), WithResponse(&info))
	var rb rawBody
	req := request{op: "raw", method: strings.ToUpper(r.Method), path: r.Path, query: r.Query, body: r.Body, charged: r.Charged}
	if err := c.do(ctx, req, &rb, opts); err != nil {
		return nil, err
	}
	return &info, nil
}
