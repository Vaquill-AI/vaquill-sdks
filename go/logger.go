package vaquill

import (
	"fmt"
	"log"
	"strings"
)

// Logger receives debug and warning messages. *slog.Logger satisfies it. Values that contain
// the API key are redacted before they reach the logger.
type Logger interface {
	Debug(msg string, args ...any)
	Warn(msg string, args ...any)
}

// stdWarnLogger is the default: warnings (such as a deprecated endpoint) go to the standard
// logger, debug output is dropped.
type stdWarnLogger struct{}

func (stdWarnLogger) Debug(string, ...any) {}
func (stdWarnLogger) Warn(msg string, args ...any) {
	log.Print("vaquill: " + msg + formatArgs(args))
}

func formatArgs(args []any) string {
	var b strings.Builder
	for i := 0; i+1 < len(args); i += 2 {
		fmt.Fprintf(&b, " %v=%v", args[i], args[i+1])
	}
	return b.String()
}

// redactor scrubs the API key from anything logged.
type redactor struct {
	inner Logger
	key   string
}

func (r redactor) scrub(msg string, args []any) (string, []any) {
	clean := func(s string) string {
		if r.key != "" {
			s = strings.ReplaceAll(s, r.key, apiKeyPrefix+"***")
		}
		return s
	}
	out := make([]any, len(args))
	for i, a := range args {
		switch v := a.(type) {
		case string:
			out[i] = clean(v)
		case error:
			out[i] = clean(v.Error())
		case fmt.Stringer:
			out[i] = clean(v.String())
		default:
			out[i] = a
		}
	}
	return clean(msg), out
}

func (r redactor) Debug(msg string, args ...any) {
	m, a := r.scrub(msg, args)
	r.inner.Debug(m, a...)
}

func (r redactor) Warn(msg string, args ...any) {
	m, a := r.scrub(msg, args)
	r.inner.Warn(m, a...)
}
