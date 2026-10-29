package vaquill

import (
	"encoding/json"
	"testing"
)

func TestPathItemDecodesStringsAndIntegers(t *testing.T) {
	var e ApiFieldError
	if err := json.Unmarshal([]byte(`{"loc":["body","items",2,"id"],"msg":"bad","type":"missing"}`), &e); err != nil {
		t.Fatal(err)
	}
	want := []PathItem{{Name: "body"}, {Name: "items"}, {Index: 2, IsIndex: true}, {Name: "id"}}
	if len(e.Loc) != len(want) {
		t.Fatalf("loc = %+v", e.Loc)
	}
	for i, w := range want {
		if e.Loc[i] != w {
			t.Errorf("loc[%d] = %+v, want %+v", i, e.Loc[i], w)
		}
	}
	if got := e.Loc[2].String() + e.Loc[1].String(); got != "2items" {
		t.Errorf("String = %q", got)
	}
}

func TestPathItemRoundTrips(t *testing.T) {
	in := []PathItem{{Name: "query"}, {Index: 0, IsIndex: true}}
	b, err := json.Marshal(in)
	if err != nil {
		t.Fatal(err)
	}
	if string(b) != `["query",0]` {
		t.Fatalf("marshal = %s", b)
	}
	var out []PathItem
	if err := json.Unmarshal(b, &out); err != nil || out[0] != in[0] || out[1] != in[1] {
		t.Fatalf("round trip = %+v, %v", out, err)
	}
}

func TestPathItemRejectsOtherShapes(t *testing.T) {
	for _, bad := range []string{`[true]`, `[1.5]`, `[null]`, `[{"a":1}]`, `[["x"]]`} {
		var out []PathItem
		if err := json.Unmarshal([]byte(bad), &out); err == nil {
			t.Errorf("%s decoded to %+v, want an error", bad, out)
		}
	}
}
