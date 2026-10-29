package vaquill

import "testing"

func TestCreditsFromBody(t *testing.T) {
	cases := []struct {
		name string
		body string
		want *float64
	}{
		{"top level", `{"creditsConsumed":2}`, Ptr(2.0)},
		{"meta fallback", `{"data":{},"meta":{"creditsConsumed":3}}`, Ptr(3.0)},
		{"top level wins over meta", `{"creditsConsumed":1.5,"meta":{"creditsConsumed":9}}`, Ptr(1.5)},
		{"zero is a value", `{"creditsConsumed":0}`, Ptr(0.0)},
		{"absent", `{"data":{}}`, nil},
		{"non numeric top level", `{"creditsConsumed":"2"}`, nil},
		{"not an object", `[1,2]`, nil},
	}
	for _, c := range cases {
		got := creditsFromBody([]byte(c.body))
		switch {
		case c.want == nil && got != nil:
			t.Errorf("%s: got %v, want nil", c.name, *got)
		case c.want != nil && (got == nil || *got != *c.want):
			t.Errorf("%s: got %v, want %v", c.name, got, *c.want)
		}
	}
}
