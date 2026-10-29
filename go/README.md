# Vaquill Go SDK

Go client for the Vaquill US Data API: statutes, regulations, court rules, constitutions and session laws, plus law-change alerts.
It covers all 36 operations of `openapi/vaquill-us.json` and mirrors the behaviour of the Python SDK.

## Install

```bash
go get github.com/Vaquill-AI/vaquill-sdks/go
```

Requires Go 1.23 or newer (the paging iterators use `iter.Seq2`).
CI runs the tests on Go 1.23 and on the stable release.

The module lives in the `go/` subdirectory of the repository, so its path ends in `/go` and its release tags are `go/vX.Y.Z` (for example `go/v0.1.0`).
`go get github.com/Vaquill-AI/vaquill-sdks/go@latest` resolves those tags; pin one with `go get github.com/Vaquill-AI/vaquill-sdks/go@v0.1.0`.

```go
import vaquill "github.com/Vaquill-AI/vaquill-sdks/go"
```

## Quickstart

```go
client, err := vaquill.NewClient() // reads VAQUILL_API_KEY
if err != nil {
	log.Fatal(err)
}
defer client.Close()

res, err := client.Statutes.Resolve(ctx, "42 U.S.C. 1983", nil)
if err != nil {
	log.Fatal(err)
}
fmt.Printf("%+v\n", res)
```

Every method takes a `context.Context` first, returns a typed value and an error, and never panics.
Optional request fields are pointers, so use `vaquill.Ptr("wa")`.
Fields that accept one value or a list use `vaquill.StringOrList{"wa", "ca"}`.

Client options: `WithAPIKey`, `WithBaseURL`, `WithTimeout` (0 disables), `WithMaxRetries`, `WithHTTPClient`, `WithDefaultHeaders`, `WithUserAgentSuffix`, `WithMaxCredits`, `WithAutoIdempotencyKeys`, `WithLogger`.
Per-call options: `WithRequestTimeout`, `WithRequestMaxRetries`, `WithIdempotencyKey`, `WithRequestHeader`, `WithResponse`.

## Response metadata

```go
var info vaquill.ResponseInfo
res, err := client.Statutes.Count(ctx, req, vaquill.WithResponse(&info))
fmt.Println(info.StatusCode, info.RequestID, info.CreditsChargedThisCall(), info.IdempotentReplayed)
```

`Header`, `Body`, `RateLimit` and `CreditsConsumed` are on the same value.

`CreditsConsumed` is the top-level `creditsConsumed` of the body, exactly as the Python SDK reads it.
Go adds one intentional fallback: when the top level has no number, it reads `meta.creditsConsumed`, because the watch change-diff route reports its charge there.
The top level always wins when both are present, and a non-numeric value is ignored (nil).
`CreditsChargedThisCall` is zero on an idempotent replay and feeds `WithMaxCredits`.
`client.Raw` sends any request and returns the undecoded body.

## Errors

All SDK errors implement `vaquill.Error`.
HTTP failures are typed per status and per machine `code`, and every one unwraps to `*vaquill.APIError`, which carries `StatusCode`, `Code`, `RequestID`, `Retryable`, `RetryAfterSeconds`, `Errors`, `Body` and `Headers`.

```go
var rl *vaquill.RateLimitError
switch {
case errors.As(err, &rl):
	time.Sleep(time.Duration(*rl.RetryAfterSeconds) * time.Second)
case errors.Is(err, vaquill.ErrInsufficientCredits):
	// top up
case errors.Is(err, vaquill.ErrNotFound):
}
```

Other types: `ConnectionError`, `TimeoutError`, `ResponseParseError` (a malformed 2xx body), `SpendGuardError`, `ConfigError`, `WebhookVerificationError`.
A 422 message ends with the first validation reasons from `errors[]`.
The idempotency codes behave as in Python: `IdempotencyKeyReused` is also an unprocessable-entity error, `IdempotencyInProgress` is also a conflict.

## Retries

The default is 2 retries with exponential backoff (0.5s doubling to 8s) and jitter.
`Retry-After-Ms` and `Retry-After` are honoured, up to 120 seconds.

- 408, 429 and 5xx are retried, except 501.
- `insufficient_credits` and `daily_cap_exceeded` are never retried.
- A transport error that may have reached the server is retried only for GET and HEAD, or when an idempotency key is set.
- A 5xx on a charged call is not retried without an idempotency key.

## Idempotency

Charged POSTs get a generated UUID `Idempotency-Key` unless you pass one:

```go
client.Statutes.Search(ctx, req, vaquill.WithIdempotencyKey("report-2026-10-29-search"))
```

Keys must be 16 to 255 visible ASCII characters; an empty or invalid key is rejected before any request.
`ResponseInfo.IdempotentReplayed` tells you the server replayed a stored response (no new charge).

## Spend guard

```go
client, _ := vaquill.NewClient(vaquill.WithMaxCredits(25))
```

The guard is exact: while a cap is set, charged calls run one at a time and the credits each response reports are added before the next call is allowed.
Once the cap is reached the next charged call fails with `*vaquill.SpendGuardError` without sending a request.
`client.CreditsSpent()` reads the running total.

## Pagination

Paginated endpoints return a `*Paginator[T]` built on `iter.Seq2`:

```go
pager, _ := client.Statutes.IterSearch(ctx, &vaquill.StatuteSearchRequest{Query: "negligence"},
	vaquill.WithMaxPages(3), vaquill.WithMaxItems(100))
for item, err := range pager.All() {
	if err != nil {
		return err
	}
	fmt.Println(item.ActID)
}
fmt.Println(pager.Truncated(), pager.Stuck())
```

`Pages()` yields whole pages and `Collect()` returns a slice.
Charged endpoints spend credits on every page, so always set `WithMaxPages` or `WithMaxItems`.
`Truncated` reports that a guard stopped the walk early; `Stuck` reports that the server repeated its offset or cursor, or answered an empty page with `hasMore: true`, and the SDK stopped instead of spending on the same page again.

Iterators: `Statutes.IterSearch`, `IterDivisions`, `IterSectionChanges`; `SessionLaws.IterSearch`, `IterList`, `IterBody`, `IterChanges`; `Boards.IterList`; `Watches.IterList`, `IterChanges`.
Batch helpers split large inputs, remove duplicates and derive a per-chunk idempotency key: `Statutes.ResolveBatchAll` (500 per request), `Statutes.GetSectionsAll` (50), `SessionLaws.GetBatchAll` (200).

## Webhooks

Deliveries follow the Standard Webhooks scheme.
Verify the raw request body, never a re-encoded one:

```go
ev, err := vaquill.UnwrapWebhook(body, r.Header, "whsec_...")
if err != nil {
	http.Error(w, "bad signature", http.StatusBadRequest)
	return
}
```

Secrets are `whsec_` plus base64.
Pass several secrets to `VerifyWebhookSecrets` / `UnwrapWebhookSecrets` while rotating.
An empty or blank secret (including a bare `whsec_`), or an empty secret list, returns `ErrEmptyWebhookSecret`; it is a configuration error, not a signature failure.
A `whsec_` secret whose remainder is not valid base64 returns `ErrInvalidWebhookSecret` instead of silently using the text as the key (the Python SDK raises `ValueError` for the same input).
Test both with `errors.Is`.
The default timestamp tolerance is 5 minutes (`WithWebhookTolerance`).
`WithLegacySignature` accepts the older `X-Vaquill-Signature` header.
`SignWebhook` produces headers for your own tests.

## Models and operations

`models_gen.go`, `operations_gen.go` and `operations_meta_gen.go` are generated from the OpenAPI document:

```bash
go generate ./...
```

A test fails if the committed files differ from a fresh generation, and another fails if `Operations` disagrees with the spec.
`vaquill.Operations` lists every operation with its method, path and whether it is charged.

## Versioning

The SDK follows semantic versioning; `vaquill.Version` is `0.1.0` and requests carry `User-Agent: vaquill-go/0.1.0`.
While the major version is 0, minor releases may change the API.
A server `Deprecation` or `Sunset` header makes the client log one warning per route.

## Tests

```bash
go test -race ./...
VAQUILL_API_KEY=... go test -tags live -run TestLiveSmoke -v .   # at most 10 credits
```
