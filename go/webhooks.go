package vaquill

import (
	"crypto/hmac"
	"crypto/sha256"
	"crypto/subtle"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"math"
	"net/http"
	"strconv"
	"strings"
	"time"
)

const (
	webhookSecretPrefix = "whsec_" // pragma: allowlist secret
	// DefaultWebhookTolerance is the accepted clock skew either side of now.
	DefaultWebhookTolerance = 5 * time.Minute
)

// WebhookEvent is the event envelope. Every other member of the payload is in Raw.
type WebhookEvent struct {
	Event   string
	FiredAt string
	// Raw is the whole payload.
	Raw map[string]json.RawMessage
}

// Unmarshal decodes the whole payload into v.
func (e *WebhookEvent) Unmarshal(v any) error {
	b, err := json.Marshal(e.Raw)
	if err != nil {
		return err
	}
	return json.Unmarshal(b, v)
}

// Unwrap lets errors.As find the embedded verification error.
func (e *WebhookPayloadError) Unwrap() error { return e.WebhookVerificationError }

type webhookConfig struct {
	tolerance   time.Duration
	allowLegacy bool
	now         func() time.Time
}

// WebhookOption adjusts verification.
type WebhookOption func(*webhookConfig)

// WithWebhookTolerance sets the accepted clock skew either side of now (default 5 minutes).
func WithWebhookTolerance(d time.Duration) WebhookOption {
	return func(c *webhookConfig) { c.tolerance = d }
}

// WithLegacySignature accepts a legacy X-Vaquill-Signature: sha256=<hmac> delivery when the
// Standard Webhooks headers are absent. WARNING: that scheme signs only the body, so it has NO
// replay protection; a captured delivery verifies forever. Opt in only while your endpoint still
// receives deliveries without the Standard Webhooks headers.
func WithLegacySignature() WebhookOption { return func(c *webhookConfig) { c.allowLegacy = true } }

// WithWebhookClock replaces the clock, for tests.
func WithWebhookClock(now func() time.Time) WebhookOption {
	return func(c *webhookConfig) { c.now = now }
}

// webhookKey decodes a whsec_ secret. A bad base64 tail is an error rather than a silent
// fallback to the literal text, which would make a mangled secret verify against the wrong key.
func webhookKey(secret string) ([]byte, error) {
	if strings.HasPrefix(secret, webhookSecretPrefix) {
		key, err := base64.StdEncoding.DecodeString(secret[len(webhookSecretPrefix):])
		if err != nil {
			return nil, ErrInvalidWebhookSecret
		}
		return key, nil
	}
	return []byte(secret), nil
}

func requireSecrets(secrets []string) error {
	if len(secrets) == 0 {
		return ErrEmptyWebhookSecret
	}
	for _, s := range secrets {
		if t := strings.TrimSpace(s); t == "" || t == webhookSecretPrefix {
			return ErrEmptyWebhookSecret
		}
	}
	return nil
}

func headerLookup(h http.Header, name string) string {
	for k, v := range h {
		if strings.EqualFold(k, name) && len(v) > 0 {
			return v[0]
		}
	}
	return ""
}

// anyMatch compares every pair without an early exit, so timing does not reveal which matched.
func anyMatch(candidates, expected []string) bool {
	matched := 0
	for _, g := range candidates {
		for _, w := range expected {
			matched |= subtle.ConstantTimeCompare([]byte(g), []byte(w))
		}
	}
	return matched == 1
}

// VerifyWebhook checks a delivery against one secret and returns nil when it is authentic.
// payload must be the raw request body, never re-serialised JSON. See VerifyWebhookSecrets.
func VerifyWebhook(payload []byte, headers http.Header, secret string, opts ...WebhookOption) error {
	_, err := UnwrapWebhookSecrets(payload, headers, []string{secret}, opts...)
	return err
}

// VerifyWebhookSecrets is VerifyWebhook with several secrets, accepted together during a rotation.
func VerifyWebhookSecrets(payload []byte, headers http.Header, secrets []string, opts ...WebhookOption) error {
	_, err := UnwrapWebhookSecrets(payload, headers, secrets, opts...)
	return err
}

// UnwrapWebhook verifies a delivery and returns its parsed event.
func UnwrapWebhook(payload []byte, headers http.Header, secret string, opts ...WebhookOption) (*WebhookEvent, error) {
	return UnwrapWebhookSecrets(payload, headers, []string{secret}, opts...)
}

// UnwrapWebhookSecrets verifies a delivery against any of secrets and returns its parsed event.
//
// Standard Webhooks (webhook-id, webhook-timestamp, webhook-signature; HMAC-SHA256 over
// "id.timestamp.body" with a whsec_ base64 secret) is checked first, within the tolerance window.
// An empty or blank secret, or a whsec_ secret that is not valid base64, returns an error that is
// not a *WebhookVerificationError, so a missing configuration value is a loud failure and can never
// accept a forged event. Verification failures are *WebhookVerificationError.
func UnwrapWebhookSecrets(payload []byte, headers http.Header, secrets []string, opts ...WebhookOption) (*WebhookEvent, error) {
	cfg := webhookConfig{tolerance: DefaultWebhookTolerance, now: time.Now}
	for _, o := range opts {
		o(&cfg)
	}
	if err := requireSecrets(secrets); err != nil {
		return nil, err
	}
	msgID := headerLookup(headers, "webhook-id")
	stamp := headerLookup(headers, "webhook-timestamp")
	sig := headerLookup(headers, "webhook-signature")
	if msgID != "" && stamp != "" && sig != "" {
		ts, err := strconv.ParseInt(stamp, 10, 64)
		if err != nil {
			return nil, newWebhookError("Invalid webhook-timestamp.")
		}
		skew := math.Abs(float64(cfg.now().Unix() - ts))
		if skew > cfg.tolerance.Seconds() {
			return nil, newWebhookError("Webhook timestamp is outside the tolerance window.")
		}
		signed := append([]byte(msgID+"."+strconv.FormatInt(ts, 10)+"."), payload...)
		var expected []string
		for _, s := range secrets {
			key, err := webhookKey(s)
			if err != nil {
				return nil, err
			}
			mac := hmac.New(sha256.New, key)
			mac.Write(signed)
			expected = append(expected, base64.StdEncoding.EncodeToString(mac.Sum(nil)))
		}
		var given []string
		for _, p := range strings.Fields(sig) {
			if strings.HasPrefix(p, "v1,") {
				given = append(given, p[3:])
			}
		}
		if !anyMatch(given, expected) {
			return nil, newWebhookError("No matching signature.")
		}
	} else {
		legacy := headerLookup(headers, "x-vaquill-signature")
		if !cfg.allowLegacy || legacy == "" {
			return nil, newWebhookError("Missing webhook signature headers.")
		}
		var expected []string
		for _, s := range secrets {
			mac := hmac.New(sha256.New, []byte(s))
			mac.Write(payload)
			expected = append(expected, "sha256="+hex.EncodeToString(mac.Sum(nil)))
		}
		if !anyMatch([]string{legacy}, expected) {
			return nil, newWebhookError("No matching signature.")
		}
	}
	var raw map[string]json.RawMessage
	if err := json.Unmarshal(payload, &raw); err != nil || raw == nil {
		return nil, &WebhookPayloadError{newWebhookError("Payload is not a valid event.")}
	}
	ev := &WebhookEvent{Raw: raw}
	if err := json.Unmarshal(raw["event"], &ev.Event); err != nil || ev.Event == "" {
		return nil, &WebhookPayloadError{newWebhookError("Payload is not a valid event.")}
	}
	_ = json.Unmarshal(raw["fired_at"], &ev.FiredAt)
	if ev.FiredAt == "" {
		_ = json.Unmarshal(raw["firedAt"], &ev.FiredAt)
	}
	return ev, nil
}

// SignWebhook produces the Standard Webhooks headers for a payload. It exists for tests and for
// replaying deliveries against your own endpoint.
func SignWebhook(payload []byte, secret, msgID string, at time.Time) (http.Header, error) {
	key, err := webhookKey(secret)
	if err != nil {
		return nil, err
	}
	ts := strconv.FormatInt(at.Unix(), 10)
	mac := hmac.New(sha256.New, key)
	mac.Write([]byte(msgID + "." + ts + "."))
	mac.Write(payload)
	h := http.Header{}
	h.Set("webhook-id", msgID)
	h.Set("webhook-timestamp", ts)
	h.Set("webhook-signature", "v1,"+base64.StdEncoding.EncodeToString(mac.Sum(nil)))
	return h, nil
}
