package vaquill

import (
	"bytes"
	"encoding/json"
	"time"
)

// Ptr returns a pointer to v. Optional scalar request fields are pointers so that an unset
// field is omitted and the server default applies: vaquill.Ptr("wa"), vaquill.Ptr(10).
func Ptr[T any](v T) *T { return &v }

// StringOrList is a request field the API accepts as one string or a list of strings
// (for example corpusType, chapter, code). It is always sent as a JSON array and decodes from either form.
type StringOrList []string

// MarshalJSON implements json.Marshaler.
func (s StringOrList) MarshalJSON() ([]byte, error) {
	if s == nil {
		return []byte("null"), nil
	}
	if len(s) == 1 {
		return json.Marshal(s[0])
	}
	return json.Marshal([]string(s))
}

// UnmarshalJSON implements json.Unmarshaler.
func (s *StringOrList) UnmarshalJSON(data []byte) error {
	data = bytes.TrimSpace(data)
	if len(data) > 0 && data[0] == '"' {
		var one string
		if err := json.Unmarshal(data, &one); err != nil {
			return err
		}
		*s = StringOrList{one}
		return nil
	}
	var many []string
	if err := json.Unmarshal(data, &many); err != nil {
		return err
	}
	*s = many
	return nil
}

// Time formats t as the RFC 3339 string the API expects in a timestamp parameter, for use as an
// optional field: Since: vaquill.Time(t).
func Time(t time.Time) *string { s := t.UTC().Format(time.RFC3339); return &s }

// Date formats t as a YYYY-MM-DD date parameter, for use as an optional field.
func Date(t time.Time) *string { s := t.Format("2006-01-02"); return &s }
