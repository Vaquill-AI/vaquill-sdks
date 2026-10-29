package vaquill

import "time"

// Version is the SDK version. It is sent in the User-Agent as vaquill-go/<Version>.
const Version = "0.1.0"

const (
	// DefaultBaseURL is the production API.
	DefaultBaseURL = "https://api.vaquill.ai"
	// APIKeyEnv is the environment variable read when no API key option is given.
	APIKeyEnv = "VAQUILL_API_KEY"
	// BaseURLEnv overrides the default base URL when no option is given.
	BaseURLEnv = "VAQUILL_BASE_URL"
	// DefaultTimeout bounds one attempt, including reading the body.
	DefaultTimeout = 60 * time.Second
	// DefaultMaxRetries is the number of retries after the first attempt.
	DefaultMaxRetries = 2

	apiKeyPrefix          = "vq_key_" // pragma: allowlist secret
	defaultConnectTimeout = 5 * time.Second
	initialRetryDelay     = 500 * time.Millisecond
	maxRetryDelay         = 8 * time.Second
	// A server-requested wait longer than this is not worth holding the caller for.
	maxRetryAfterDelay = 120 * time.Second

	idempotencyHeader       = "Idempotency-Key"
	replayedHeader          = "Idempotent-Replayed"
	idempotencyStatusHeader = "Idempotency-Status"
	requestIDHeader         = "X-Request-ID"
)
