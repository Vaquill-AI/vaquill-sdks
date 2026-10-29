package vaquill

import (
	"bytes"
	"encoding/json"
	"fmt"
	"strconv"
)

// PathItem is one step of a validation error location (ApiFieldError.Loc). The API sends a
// string for a section or parameter name ("body", "corpusType") and an integer for a list
// index (0). Exactly one of those is set: IsIndex says which.
type PathItem struct {
	// Name is the section or parameter name when IsIndex is false.
	Name string
	// Index is the list position when IsIndex is true.
	Index int
	// IsIndex is true when this step is a list index.
	IsIndex bool
}

// String renders the step: the name, or the index in decimal.
func (p PathItem) String() string {
	if p.IsIndex {
		return strconv.Itoa(p.Index)
	}
	return p.Name
}

// MarshalJSON implements json.Marshaler. An index is a JSON number, a name a JSON string.
func (p PathItem) MarshalJSON() ([]byte, error) {
	if p.IsIndex {
		return json.Marshal(p.Index)
	}
	return json.Marshal(p.Name)
}

// UnmarshalJSON implements json.Unmarshaler. It accepts a JSON string or a whole JSON number
// and rejects every other shape, so a malformed location is reported rather than swallowed.
func (p *PathItem) UnmarshalJSON(data []byte) error {
	data = bytes.TrimSpace(data)
	if len(data) == 0 {
		return fmt.Errorf("vaquill: empty path item")
	}
	if data[0] == '"' {
		var name string
		if err := json.Unmarshal(data, &name); err != nil {
			return err
		}
		*p = PathItem{Name: name}
		return nil
	}
	var n json.Number
	if err := json.Unmarshal(data, &n); err != nil {
		return fmt.Errorf("vaquill: path item must be a string or an integer: %s", data)
	}
	i, err := strconv.Atoi(n.String())
	if err != nil {
		return fmt.Errorf("vaquill: path item must be a string or an integer: %s", data)
	}
	*p = PathItem{Index: i, IsIndex: true}
	return nil
}
