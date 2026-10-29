package vaquill

import (
	"crypto/rand"
	"fmt"
)

// newIdempotencyKey returns a random UUIDv4.
func newIdempotencyKey() string {
	var b [16]byte
	if _, err := rand.Read(b[:]); err != nil {
		panic("vaquill: crypto/rand unavailable: " + err.Error())
	}
	b[6] = (b[6] & 0x0f) | 0x40
	b[8] = (b[8] & 0x3f) | 0x80
	return fmt.Sprintf("%x-%x-%x-%x-%x", b[0:4], b[4:6], b[6:8], b[8:10], b[10:])
}

// validateIdempotencyKey enforces the server rule: 16 to 255 visible ASCII characters.
func validateIdempotencyKey(key string) error {
	if len(key) < 16 || len(key) > 255 {
		return &ConfigError{Message: "idempotency key must be 16 to 255 visible ASCII characters"}
	}
	for i := 0; i < len(key); i++ {
		if key[i] < 33 || key[i] > 126 {
			return &ConfigError{Message: "idempotency key must be 16 to 255 visible ASCII characters"}
		}
	}
	return nil
}

// redactKey shows a key by its first 8 characters only.
func redactKey(key string) string {
	if len(key) <= 8 {
		return key + "..."
	}
	return key[:8] + "..."
}
