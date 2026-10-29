package vaquill

import (
	"crypto/hmac"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"errors"
	"net/http"
	"strconv"
	"strings"
	"testing"
	"time"
)

var (
	whNow    = time.Date(2026, 10, 29, 12, 0, 0, 0, time.UTC)
	whSecret = "whsec_" + base64.StdEncoding.EncodeToString([]byte("super-secret-key-bytes-0123456789"))
	whBody   = []byte(`{"event":"board.refreshed","fired_at":"2026-10-29T11:59:00Z","boardId":"b1"}`)
)

func whClock() func() time.Time { return func() time.Time { return whNow } }

func signed(t *testing.T, secret string, at time.Time) http.Header {
	t.Helper()
	h, err := SignWebhook(whBody, secret, "msg_1", at)
	if err != nil {
		t.Fatal(err)
	}
	return h
}

func TestWebhookVerifyAndUnwrap(t *testing.T) {
	h := signed(t, whSecret, whNow)
	ev, err := UnwrapWebhook(whBody, h, whSecret, WithWebhookClock(whClock()))
	if err != nil {
		t.Fatal(err)
	}
	if ev.Event != "board.refreshed" || ev.FiredAt != "2026-10-29T11:59:00Z" {
		t.Errorf("event = %+v", ev)
	}
	var extra struct {
		BoardID string `json:"boardId"`
	}
	if err := ev.Unmarshal(&extra); err != nil || extra.BoardID != "b1" {
		t.Errorf("extra = %+v %v", extra, err)
	}
	if err := VerifyWebhook(whBody, h, whSecret, WithWebhookClock(whClock())); err != nil {
		t.Error(err)
	}
	// Header names are case-insensitive.
	lower := http.Header{}
	for k, v := range h {
		lower[strings.ToLower(k)] = v
	}
	if err := VerifyWebhook(whBody, lower, whSecret, WithWebhookClock(whClock())); err != nil {
		t.Errorf("lower-case headers: %v", err)
	}
}

func TestWebhookRejects(t *testing.T) {
	opts := []WebhookOption{WithWebhookClock(whClock())}
	good := signed(t, whSecret, whNow)
	var ve *WebhookVerificationError

	tampered := append([]byte(nil), whBody...)
	tampered[3] = 'X'
	if err := VerifyWebhook(tampered, good, whSecret, opts...); !errors.As(err, &ve) || !errors.Is(err, ErrWebhookVerification) {
		t.Errorf("tampered body: %v", err)
	}
	other := "whsec_" + base64.StdEncoding.EncodeToString([]byte("another-secret-entirely-000000"))
	if err := VerifyWebhook(whBody, good, other, opts...); !errors.As(err, &ve) {
		t.Errorf("wrong secret: %v", err)
	}
	old := signed(t, whSecret, whNow.Add(-6*time.Minute))
	if err := VerifyWebhook(whBody, old, whSecret, opts...); !errors.As(err, &ve) || !strings.Contains(err.Error(), "tolerance") {
		t.Errorf("stale: %v", err)
	}
	future := signed(t, whSecret, whNow.Add(6*time.Minute))
	if err := VerifyWebhook(whBody, future, whSecret, opts...); !errors.As(err, &ve) {
		t.Errorf("future: %v", err)
	}
	edge := signed(t, whSecret, whNow.Add(-5*time.Minute))
	if err := VerifyWebhook(whBody, edge, whSecret, opts...); err != nil {
		t.Errorf("exactly at tolerance must pass: %v", err)
	}
	if err := VerifyWebhook(whBody, old, whSecret, append(opts, WithWebhookTolerance(10*time.Minute))...); err != nil {
		t.Errorf("wider tolerance: %v", err)
	}
	bad := good.Clone()
	bad.Set("webhook-timestamp", "yesterday")
	if err := VerifyWebhook(whBody, bad, whSecret, opts...); !errors.As(err, &ve) || !strings.Contains(err.Error(), "Invalid webhook-timestamp") {
		t.Errorf("bad timestamp: %v", err)
	}
	if err := VerifyWebhook(whBody, http.Header{}, whSecret, opts...); !errors.As(err, &ve) || !strings.Contains(err.Error(), "Missing") {
		t.Errorf("no headers: %v", err)
	}
	partial := good.Clone()
	partial.Del("webhook-signature")
	if err := VerifyWebhook(whBody, partial, whSecret, opts...); !errors.As(err, &ve) {
		t.Errorf("partial headers: %v", err)
	}
	junkSig := good.Clone()
	junkSig.Set("webhook-signature", "v2,abc v1,notmatching")
	if err := VerifyWebhook(whBody, junkSig, whSecret, opts...); !errors.As(err, &ve) {
		t.Errorf("junk sig: %v", err)
	}
}

func TestWebhookSecretValidation(t *testing.T) {
	h := signed(t, whSecret, whNow)
	opts := WithWebhookClock(whClock())
	for _, s := range []string{"", "   ", "whsec_", "\t"} {
		err := VerifyWebhook(whBody, h, s, opts)
		if !errors.Is(err, ErrEmptyWebhookSecret) {
			t.Errorf("secret %q: err = %v", s, err)
		}
		var ve *WebhookVerificationError
		if errors.As(err, &ve) {
			t.Errorf("an empty secret is a configuration error, not a verification failure")
		}
	}
	if err := VerifyWebhookSecrets(whBody, h, nil, opts); !errors.Is(err, ErrEmptyWebhookSecret) {
		t.Errorf("no secrets: %v", err)
	}
	if err := VerifyWebhookSecrets(whBody, h, []string{whSecret, ""}, opts); !errors.Is(err, ErrEmptyWebhookSecret) {
		t.Errorf("one blank among several: %v", err)
	}
	if err := VerifyWebhook(whBody, h, "whsec_!!!not-base64!!!", opts); !errors.Is(err, ErrInvalidWebhookSecret) {
		t.Errorf("invalid base64: %v", err)
	}
	if _, err := SignWebhook(whBody, "whsec_%%%", "id", whNow); !errors.Is(err, ErrInvalidWebhookSecret) {
		t.Errorf("sign with invalid base64: %v", err)
	}
	// A plain (non whsec_) secret is used as literal bytes.
	h2, _ := SignWebhook(whBody, "plain-secret", "m", whNow)
	if err := VerifyWebhook(whBody, h2, "plain-secret", opts); err != nil {
		t.Errorf("plain secret: %v", err)
	}
}

func TestWebhookRotation(t *testing.T) {
	oldS := "whsec_" + base64.StdEncoding.EncodeToString([]byte("old-secret-old-secret-old-secret"))
	newS := "whsec_" + base64.StdEncoding.EncodeToString([]byte("new-secret-new-secret-new-secret"))
	opts := WithWebhookClock(whClock())
	for _, signer := range []string{oldS, newS} {
		h := signed(t, signer, whNow)
		if _, err := UnwrapWebhookSecrets(whBody, h, []string{newS, oldS}, opts); err != nil {
			t.Errorf("rotation with signer %.12s: %v", signer, err)
		}
	}
	// Two signatures in one header (the sender signs with both keys).
	a, b := signed(t, oldS, whNow), signed(t, newS, whNow)
	both := a.Clone()
	both.Set("webhook-signature", a.Get("webhook-signature")+" "+b.Get("webhook-signature"))
	if err := VerifyWebhook(whBody, both, newS, opts); err != nil {
		t.Errorf("space separated signatures: %v", err)
	}
}

func TestWebhookLegacy(t *testing.T) {
	mac := hmac.New(sha256.New, []byte("legacy-secret"))
	mac.Write(whBody)
	h := http.Header{}
	h.Set("X-Vaquill-Signature", "sha256="+hex.EncodeToString(mac.Sum(nil)))
	var ve *WebhookVerificationError
	if err := VerifyWebhook(whBody, h, "legacy-secret"); !errors.As(err, &ve) {
		t.Errorf("legacy must be rejected by default: %v", err)
	}
	if err := VerifyWebhook(whBody, h, "legacy-secret", WithLegacySignature()); err != nil {
		t.Errorf("legacy opt-in: %v", err)
	}
	if err := VerifyWebhook(whBody, h, "other-secret", WithLegacySignature()); !errors.As(err, &ve) {
		t.Errorf("legacy wrong secret: %v", err)
	}
	bad := http.Header{}
	bad.Set("X-Vaquill-Signature", "sha256=00")
	if err := VerifyWebhook(whBody, bad, "legacy-secret", WithLegacySignature()); !errors.As(err, &ve) {
		t.Errorf("legacy bad sig: %v", err)
	}
	if err := VerifyWebhook(whBody, http.Header{}, "legacy-secret", WithLegacySignature()); !errors.As(err, &ve) {
		t.Errorf("legacy absent: %v", err)
	}
}

func TestWebhookPayloadErrors(t *testing.T) {
	for _, body := range []string{`not json`, `[1]`, `{"x":1}`, `{"event":5}`, `{"event":""}`, `null`} {
		b := []byte(body)
		h, _ := SignWebhook(b, whSecret, "m", whNow)
		_, err := UnwrapWebhook(b, h, whSecret, WithWebhookClock(whClock()))
		var pe *WebhookPayloadError
		var ve *WebhookVerificationError
		if !errors.As(err, &pe) || !errors.As(err, &ve) {
			t.Errorf("body %q: err = %v", body, err)
		}
	}
	// camelCase firedAt is read too.
	b := []byte(`{"event":"e","firedAt":"2026-01-01T00:00:00Z"}`)
	h, _ := SignWebhook(b, whSecret, "m", whNow)
	ev, err := UnwrapWebhook(b, h, whSecret, WithWebhookClock(whClock()))
	if err != nil || ev.FiredAt != "2026-01-01T00:00:00Z" {
		t.Errorf("firedAt: %+v %v", ev, err)
	}
}

func TestWebhookDefaultClock(t *testing.T) {
	h, _ := SignWebhook(whBody, whSecret, "m", time.Now())
	if err := VerifyWebhook(whBody, h, whSecret); err != nil {
		t.Errorf("default clock: %v", err)
	}
	if h.Get("webhook-timestamp") == strconv.FormatInt(whNow.Unix(), 10) {
		t.Error("timestamp should be current")
	}
}
