package vaquill_test

import (
	"context"
	"errors"
	"fmt"
	"net/http"
	"net/http/httptest"
	"time"

	vaquill "github.com/Vaquill-AI/vaquill-sdks/go"
)

// exampleClient returns a client pointed at a local server that answers every call with body.
func exampleClient(status int, body string, extra ...vaquill.Option) (*vaquill.Client, func()) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(status)
		_, _ = w.Write([]byte(body))
	}))
	opts := append([]vaquill.Option{vaquill.WithAPIKey("vq_key_example"), vaquill.WithBaseURL(srv.URL), vaquill.WithMaxRetries(0)}, extra...)
	c, err := vaquill.NewClient(opts...)
	if err != nil {
		panic(err)
	}
	return c, srv.Close
}

func ExampleNewClient() {
	client, err := vaquill.NewClient(
		vaquill.WithAPIKey("vq_key_..."), // default: the VAQUILL_API_KEY environment variable
		vaquill.WithTimeout(30*time.Second),
		vaquill.WithMaxRetries(3),
		vaquill.WithMaxCredits(25), // refuse to spend more than 25 credits through this client
	)
	if err != nil {
		fmt.Println(err)
		return
	}
	defer client.Close()
	fmt.Println(client.BaseURL())
	// Output: https://api.vaquill.ai
}

func ExampleStatutesService_Count() {
	client, stop := exampleClient(200, `{"count":412,"isExact":true,"creditsConsumed":1}`)
	defer stop()

	var info vaquill.ResponseInfo
	res, err := client.Statutes.Count(context.Background(),
		&vaquill.StatuteCountRequest{State: vaquill.StringOrList{"wa"}},
		vaquill.WithResponse(&info))
	if err != nil {
		fmt.Println(err)
		return
	}
	fmt.Println(res.Count, info.CreditsChargedThisCall())
	// Output: 412 1
}

func ExampleStatutesService_Resolve() {
	client, stop := exampleClient(200, `{"found":true}`)
	defer stop()
	_, err := client.Statutes.Resolve(context.Background(), "42 U.S.C. 1983", &vaquill.ResolveStatuteCitationParams{State: vaquill.Ptr("federal")})
	fmt.Println(err)
	// Output: <nil>
}

func ExampleStatutesService_IterSearch() {
	client, stop := exampleClient(200, `{"results":[{"actId":"a1"},{"actId":"a2"}],"hasMore":false,"count":2}`)
	defer stop()

	// Every page of a charged search spends credits: always bound the walk.
	pager, err := client.Statutes.IterSearch(context.Background(),
		&vaquill.StatuteSearchRequest{Query: "negligence"},
		vaquill.WithMaxPages(2), vaquill.WithMaxItems(50))
	if err != nil {
		fmt.Println(err)
		return
	}
	for item, err := range pager.All() {
		if err != nil {
			fmt.Println(err)
			return
		}
		fmt.Println(item.ActID)
	}
	fmt.Println("truncated:", pager.Truncated())
	// Output:
	// a1
	// a2
	// truncated: false
}

func ExampleAPIError() {
	client, stop := exampleClient(404, `{"detail":"No such section","code":"not_found","requestId":"req_1"}`)
	defer stop()

	_, err := client.Statutes.GetSection(context.Background(), "missing")
	var nf *vaquill.NotFoundError
	if errors.As(err, &nf) {
		fmt.Println(nf.StatusCode, nf.Code, nf.RequestID)
	}
	var api *vaquill.APIError
	fmt.Println(errors.As(err, &api), errors.Is(err, vaquill.ErrNotFound))
	// Output:
	// 404 not_found req_1
	// true true
}

func ExampleWithIdempotencyKey() {
	client, stop := exampleClient(200, `{"count":1}`)
	defer stop()
	// A retry of this call, by this process or another, never charges twice.
	_, err := client.Statutes.Count(context.Background(), &vaquill.StatuteCountRequest{},
		vaquill.WithIdempotencyKey("nightly-report-2026-10-29-count"))
	fmt.Println(err)
	// Output: <nil>
}

func ExampleVerifyWebhook() {
	secret := "whsec_c2VjcmV0LWtleS1mb3ItZXhhbXBsZQ=="
	payload := []byte(`{"event":"watch.change","firedAt":"2026-10-29T00:00:00Z"}`)
	headers, err := vaquill.SignWebhook(payload, secret, "msg_1", time.Now())
	if err != nil {
		fmt.Println(err)
		return
	}
	ev, err := vaquill.UnwrapWebhook(payload, headers, secret)
	if err != nil {
		fmt.Println(err)
		return
	}
	fmt.Println(ev.Event)
	// Output: watch.change
}
