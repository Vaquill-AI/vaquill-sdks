package vaquill

import (
	"bytes"
	"encoding/json"
	"fmt"
	"net/url"
	"reflect"
	"sort"
	"strconv"
	"strings"
	"time"
)

// escapeSegment percent-encodes everything except the RFC 3986 unreserved characters,
// so a citation or id containing "/" stays one path segment.
func escapeSegment(s string) string {
	const hex = "0123456789ABCDEF"
	var b strings.Builder
	for i := 0; i < len(s); i++ {
		c := s[i]
		if c >= 'a' && c <= 'z' || c >= 'A' && c <= 'Z' || c >= '0' && c <= '9' || c == '-' || c == '.' || c == '_' || c == '~' {
			b.WriteByte(c)
			continue
		}
		b.WriteByte('%')
		b.WriteByte(hex[c>>4])
		b.WriteByte(hex[c&15])
	}
	return b.String()
}

// pathSegment validates and encodes one path segment. An empty segment would produce "//",
// and "." or ".." would be resolved away by a URL parser and silently call another endpoint.
func pathSegment(value string) (string, error) {
	if value == "" || value == "." || value == ".." {
		return "", &ConfigError{Message: fmt.Sprintf("invalid path segment %q: it must not be empty, '.' or '..'", value)}
	}
	return escapeSegment(value), nil
}

// pathf fills {name} placeholders of a path template from name/value pairs.
func pathf(tpl string, kv ...any) (string, error) {
	for i := 0; i+1 < len(kv); i += 2 {
		name, _ := kv[i].(string)
		var seg string
		switch v := kv[i+1].(type) {
		case string:
			s, err := pathSegment(v)
			if err != nil {
				return "", err
			}
			seg = s
		case int:
			seg = strconv.Itoa(v)
		case int64:
			seg = strconv.FormatInt(v, 10)
		default:
			seg = escapeSegment(fmt.Sprint(v))
		}
		tpl = strings.ReplaceAll(tpl, "{"+name+"}", seg)
	}
	return tpl, nil
}

// toMap converts a request struct (or map) to its wire map: JSON names, unset members dropped,
// integers kept as int64 and decimals as float64.
func toMap(v any) (map[string]any, error) {
	if v == nil {
		return map[string]any{}, nil
	}
	if rv := reflect.ValueOf(v); rv.Kind() == reflect.Ptr && rv.IsNil() {
		return map[string]any{}, nil
	}
	if m, ok := v.(map[string]any); ok {
		out := make(map[string]any, len(m))
		for k, x := range m {
			if x != nil {
				out[k] = x
			}
		}
		return out, nil
	}
	raw, err := json.Marshal(v)
	if err != nil {
		return nil, &ConfigError{Message: "cannot encode parameters: " + err.Error()}
	}
	var out map[string]any
	if err := decodeNormalized(raw, &out); err != nil {
		return nil, &ConfigError{Message: "parameters must encode to a JSON object: " + err.Error()}
	}
	if out == nil {
		out = map[string]any{}
	}
	for k, x := range out {
		if x == nil {
			delete(out, k)
		}
	}
	return out, nil
}

// decodeNormalized decodes JSON, turning integral numbers into int64 and the rest into float64.
func decodeNormalized(raw []byte, out any) error {
	dec := json.NewDecoder(bytes.NewReader(raw))
	dec.UseNumber()
	if err := dec.Decode(out); err != nil {
		return err
	}
	switch p := out.(type) {
	case *map[string]any:
		if *p != nil {
			normalizeMap(*p)
		}
	case *any:
		*p = normalizeValue(*p)
	}
	return nil
}

func normalizeMap(m map[string]any) {
	for k, v := range m {
		m[k] = normalizeValue(v)
	}
}

func normalizeValue(v any) any {
	switch x := v.(type) {
	case json.Number:
		if i, err := x.Int64(); err == nil {
			return i
		}
		f, _ := x.Float64()
		return f
	case map[string]any:
		normalizeMap(x)
		return x
	case []any:
		for i := range x {
			x[i] = normalizeValue(x[i])
		}
		return x
	}
	return v
}

// buildQuery encodes a params struct (may be nil) plus required name/value pairs. Booleans are
// "true"/"false", time values RFC 3339, and arrays repeat the key.
func buildQuery(params any, kv ...any) (url.Values, error) {
	m, err := toMap(params)
	if err != nil {
		return nil, err
	}
	for i := 0; i+1 < len(kv); i += 2 {
		m[kv[i].(string)] = kv[i+1]
	}
	return encodeQuery(m), nil
}

func encodeQuery(m map[string]any) url.Values {
	q := url.Values{}
	keys := make([]string, 0, len(m))
	for k := range m {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	for _, k := range keys {
		switch v := m[k].(type) {
		case nil:
		case []any:
			for _, e := range v {
				q.Add(k, queryScalar(e))
			}
		case []string:
			for _, e := range v {
				q.Add(k, e)
			}
		case StringOrList:
			for _, e := range v {
				q.Add(k, e)
			}
		default:
			q.Add(k, queryScalar(v))
		}
	}
	return q
}

func queryScalar(v any) string {
	switch x := v.(type) {
	case string:
		return x
	case bool:
		return strconv.FormatBool(x)
	case time.Time:
		return x.Format(time.RFC3339)
	case *time.Time:
		return x.Format(time.RFC3339)
	case int:
		return strconv.Itoa(x)
	case int64:
		return strconv.FormatInt(x, 10)
	case float64:
		return strconv.FormatFloat(x, 'f', -1, 64)
	case json.Number:
		return x.String()
	case fmt.Stringer:
		return x.String()
	}
	return fmt.Sprint(v)
}
