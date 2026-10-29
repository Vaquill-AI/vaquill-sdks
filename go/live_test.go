//go:build live

package vaquill_test

import (
	"context"
	"os"
	"testing"
	"time"

	vaquill "github.com/Vaquill-AI/vaquill-sdks/go"
)

// TestLiveSmoke talks to the real API. Run it with:
//
//	VAQUILL_API_KEY=... go test -tags live -run TestLiveSmoke -v .
//
// It is capped at 10 credits through the SDK's own spend guard, makes one charged call, and never
// prints or stores the key.
func TestLiveSmoke(t *testing.T) {
	if os.Getenv("VAQUILL_API_KEY") == "" {
		t.Skip("VAQUILL_API_KEY is not set")
	}
	ctx, cancel := context.WithTimeout(context.Background(), 90*time.Second)
	defer cancel()
	c, err := vaquill.NewClient(vaquill.WithMaxCredits(10), vaquill.WithMaxRetries(1))
	if err != nil {
		t.Fatal(err)
	}
	defer c.Close()

	// Free.
	var binfo vaquill.ResponseInfo
	bal, err := c.Credits.Balance(ctx, vaquill.WithResponse(&binfo))
	if err != nil {
		t.Fatalf("balance: %v", err)
	}
	if binfo.RequestID == "" {
		t.Error("no request id on the balance response")
	}
	t.Logf("balance ok, request id %s, credits remaining %.2f", binfo.RequestID, bal.CreditsRemaining)

	// Free.
	if _, err := c.Pricing.Get(ctx, nil); err != nil {
		t.Fatalf("pricing: %v", err)
	}

	// One charged call (about 1 credit), a typed error path is covered by the unit tests.
	var cinfo vaquill.ResponseInfo
	res, err := c.Statutes.Count(ctx, &vaquill.StatuteCountRequest{State: vaquill.StringOrList{"wa"}}, vaquill.WithResponse(&cinfo))
	if err != nil {
		t.Fatalf("count: %v", err)
	}
	if res.Count <= 0 {
		t.Errorf("count = %d, want > 0", res.Count)
	}
	t.Logf("count ok: %d sections, charged %.2f credits, spent through this client %.2f", res.Count, cinfo.CreditsChargedThisCall(), c.CreditsSpent())
	if c.CreditsSpent() > 10 {
		t.Errorf("spent %.2f credits, over the 10 credit budget", c.CreditsSpent())
	}
}
