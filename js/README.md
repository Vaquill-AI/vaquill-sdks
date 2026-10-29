# @vaquill-ai/sdk

[![npm](https://img.shields.io/npm/v/@vaquill-ai/sdk)](https://www.npmjs.com/package/@vaquill-ai/sdk) [![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](https://github.com/Vaquill-AI/vaquill-sdks/blob/main/LICENSE)

TypeScript client for the Vaquill US primary law Data API.
It is a small handwritten layer over native `fetch` with zero runtime dependencies.
Request and response types are generated from the OpenAPI document by `openapi-typescript` (a dev dependency only).

Built on standard `fetch`; CI-tested on Node 20, 22 and 24.
The public API follows semantic versioning and may change in minor versions before 1.0.
Use it on a server.
An API key in browser code is readable by anyone, and the client warns when it sees a browser.

```ts
import { Vaquill } from "@vaquill-ai/sdk";

const client = new Vaquill(); // reads VAQUILL_API_KEY (must start with vq_key_)

const res = await client.statutes.search({ query: "assault with a deadly weapon", state: "tx" });
console.log(res.results?.length, res.creditsConsumed);

const { data, meta } = await client.statutes.getSection("USC_T42_C21_S1983").withResponse();
console.log(meta.requestId, meta.creditsConsumed, meta.rateLimit.remainingDay);
```

## Documentation

- [TypeScript guide](https://www.vaquill.ai/docs/api-guide/sdks/typescript) and the [SDK overview](https://www.vaquill.ai/docs/api-guide/sdks/overview)
- [Data API guide](https://www.vaquill.ai/docs/api-guide/overview): authentication, pagination, errors, alerts
- [API reference](https://www.vaquill.ai/docs/api-reference/): every endpoint and field
- Get an API key at [app.vaquill.ai/settings](https://app.vaquill.ai/settings)
- Source, issues and releases: [Vaquill-AI/vaquill-sdks](https://github.com/Vaquill-AI/vaquill-sdks)

## Client options

`new Vaquill({ apiKey, baseURL, timeout, maxRetries, defaultHeaders, fetch, maxCredits })`

- `apiKey` defaults to `VAQUILL_API_KEY`. Keys that do not start with `vq_key_` are rejected.
- `baseURL` defaults to `VAQUILL_BASE_URL`, then `https://api.vaquill.ai`.
- `timeout` is per attempt, in milliseconds (default 60000). `maxRetries` defaults to 2.
- `fetch` injects a custom implementation (proxy, test double).
- `maxCredits` is a spend guard: once responses on this client have reported that many credits, charged calls throw `SpendGuardExceededError` before sending anything. It checks what is already spent, not the cost of the next call. `client.creditsSpent` shows the running total.
- `client.withOptions({...})` returns a derived client that shares the key and the spend counter.
- Every method takes `{ timeout, maxRetries, headers, signal, idempotencyKey }` as its last argument.

The key is held in a private field.
It does not appear in `JSON.stringify`, `util.inspect`, `String(client)` or any error.

## Resources

| Namespace | Methods |
| --- | --- |
| `statutes` | `search`, `searchAll`, `getSection`, `getSectionBody`, `getSectionNeighbors`, `getSections`, `count`, `coverage`, `listDivisions`, `listDivisionsAll`, `getSectionChanges`, `getSectionChangesAll`, `getSectionEnactments`, `getSectionRulemaking`, `getPartRulemaking`, `getSectionCitedBy`, `getSectionDefinitions`, `getSectionCrossState`, `resolve`, `resolveBatch`, `extractCitations` |
| `sessionLaws` | `search`, `searchAll`, `list`, `listAll`, `get`, `getBody`, `getVersions`, `getChanges`, `getChangesAll`, `getBatch` |
| `watches` | `list`, `listAll`, `create`, `update`, `delete`, `test`, `listChanges`, `listChangesAll`, `getChangeDiff`, `listDeliveries` |
| `boards` | `list`, `listAll` |
| `credits` | `balance` |
| `pricing` | `get` |

Each method maps to one operationId (`search_statutes` is `statutes.search`, `get_section_body` is `statutes.getSectionBody`, and so on).
Path parameters are positional arguments.
Query and body fields keep the camelCase wire names.
`client.rawRequest(method, path, { query, body, charged })` reaches endpoints newer than this SDK.

## Charged methods

A method is charged when the spec declares an `Idempotency-Key` header on its operation.
A test derives this list from the spec, so it cannot drift.

Charged: `statutes.search`, `getSection`, `getSectionBody`, `getSectionNeighbors`, `getSections`, `count`, `listDivisions`, `getSectionChanges`, `getSectionEnactments`, `getSectionRulemaking`, `getPartRulemaking`, `getSectionCitedBy`, `getSectionDefinitions`, `getSectionCrossState`, `resolve`, `resolveBatch`, `extractCitations`; `sessionLaws.search`, `list`, `get`, `getBody`, `getVersions`, `getChanges`, `getBatch`; `watches.getChangeDiff`.
That is 25 operations. The `*All` iterators call these and spend per page.

`statutes.extractCitations` costs 0 credits when `resolve: false` and 2 credits per distinct citation otherwise.

Free: `statutes.coverage`, `watches.list`, `create`, `update`, `delete`, `test`, `listChanges`, `listDeliveries`, `boards.list`, `credits.balance`, `pricing.get`.

## Retries and idempotency

- Retried: 408, 429 and 5xx, plus 409 only for `idempotency_in_progress`. Connection errors and timeouts are retried when it is safe.
- Backoff is 0.5 s doubling to an 8 s cap, scaled down by 0 to 25 percent jitter. `retry-after-ms` wins over `Retry-After` (seconds or date), which wins over the body's `retryAfterSeconds`. A wait above 120 s is not retried.
- Never retried: `insufficient_credits` (402), `daily_cap_exceeded`, any 4xx other than the above, and anything the server marks `retryable: false`.
- Each charged call gets one generated `Idempotency-Key`, reused on every retry of that call. Pass `idempotencyKey: "..."` to choose your own.
- With `idempotencyKey: false` a charged call is not retried after a timeout, connection error or 5xx, because it could charge twice. A 429 `rate_limited` is still retried, since it is refused before any work.
- Free `POST`s without a key (`watches.create`, `watches.test`) follow the same rule, so a retry cannot create a second watch.

## Errors

`VaquillError` is the base. `APIConnectionError` (with `APITimeoutError`, `APIUserAbortError`) means no response arrived.
`APIStatusError` carries `status`, `requestId`, `code`, `retryable`, `retryAfterSeconds`, `body`, plus the legacy `detail` and `errors`.
Subclasses: `BadRequestError`, `AuthenticationError`, `InsufficientCreditsError`, `PermissionDeniedError`, `NotFoundError`, `ConflictError`, `UnprocessableEntityError`, `RateLimitError` (and `DailyCapExceededError`), `InternalServerError`, and `IdempotencyConflictError` with `IdempotencyKeyReusedError`, `IdempotencyInProgressError`, `IdempotencyReplayUnavailableError`.
The code is checked first, then the status. An unknown code still gives the status class. Missing new fields come back as `null`.

## Pagination

The `*All` methods return an async iterable of items, with `.pages()` for whole pages and `.toArray()`.
They hide offset with `nextOffset`, `cursor` with `nextCursor`, and `sinceId` / `beforeId` paging.

```ts
for await (const s of client.statutes.searchAll({ query: "negligence" }, { maxPages: 3, maxItems: 50 })) {
  console.log(s);
}
```

Charged endpoints spend credits on every page.
Set `maxPages`, `maxItems` or a client `maxCredits`.
Without one, an iterator runs until the data ends.

## Webhooks

```ts
import { webhooks } from "@vaquill-ai/sdk";

const event = await webhooks.unwrap(rawBody, request.headers, process.env.WEBHOOK_SECRET!);
```

Pass the raw body, never re-serialised JSON.
`verify` and `unwrap` check Standard Webhooks headers with a 300 s tolerance, accept several `v1` signatures (rotation) and a list of secrets, and compare through `crypto.subtle.verify`, which is constant time.
A secret starting with `whsec_` is base64 decoded; any other secret is used as its UTF-8 bytes.
They throw `WebhookVerificationError` on any failure.

`{ allowLegacy: true }` also accepts the old `X-Vaquill-Signature: sha256=<hex>` header when the Standard Webhooks headers are absent.
That header signs only the body, so it has no replay protection: a captured delivery verifies forever.

## Development

```
npm install --legacy-peer-deps
npm run gen            # regenerate src/_generated/schema.d.ts from openapi/vaquill-us.json
npm run build && npm run typecheck && npm test && npm run lint:package && npm run lint
```

Never edit `src/_generated`.
