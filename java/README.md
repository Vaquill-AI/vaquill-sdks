# Vaquill Java SDK

Java client for the Vaquill US Data API: US statutes, regulations, court rules, session laws, law-change watches and credits.
It covers all 36 operations of the OpenAPI document and matches the behaviour of the Python SDK.

- Java 11 or newer.
- One runtime dependency: Jackson (`jackson-databind`) for JSON.
- HTTP goes through the JDK `java.net.http.HttpClient`, so you can pass your own configured client.
- Every call has a blocking form, a `...WithResponse` form (status, headers, request id, credits) and a `...Async` form.

## Install

Maven:

```xml
<dependency>
  <groupId>ai.vaquill</groupId>
  <artifactId>vaquill-sdk</artifactId>
  <version>0.1.0</version>
</dependency>
```

Gradle (Kotlin DSL):

```kotlin
dependencies {
    implementation("ai.vaquill:vaquill-sdk:0.1.0")
}
```

Gradle (Groovy):

```groovy
dependencies {
    implementation 'ai.vaquill:vaquill-sdk:0.1.0'
}
```

## Quickstart

```java
import ai.vaquill.sdk.Vaquill;
import ai.vaquill.sdk.models.StatuteCountRequest;

try (Vaquill client = Vaquill.builder().build()) {   // reads VAQUILL_API_KEY
    System.out.println(client.credits().balance().getCreditsRemaining());
    System.out.println(client.statutes().count(StatuteCountRequest.builder().state("ca").build()));
}
```

Resources: `client.statutes()`, `client.sessionLaws()`, `client.watches()`, `client.boards()`, `client.credits()`, `client.pricing()`.
Request bodies are built with `Model.builder()`, optional query parameters with `...Params.builder()`.
Responses are plain immutable-style models. Members this SDK version does not know about are kept in `getAdditionalProperties()` and survive a round trip.

### Client options

| Builder method | Meaning |
| --- | --- |
| `apiKey(String)` | Defaults to the `VAQUILL_API_KEY` environment variable. Must start with `vq_key_`. The key is never echoed in an error message or a log line. |
| `baseUrl(String)` | Defaults to `VAQUILL_BASE_URL`, then `https://api.vaquill.ai`. |
| `timeout(Duration)` | Per-request timeout. `Duration.ZERO` disables it. |
| `maxRetries(int)` | Default 2. |
| `httpClient(HttpClient)` | Bring your own client (proxy, TLS, executor). |
| `defaultHeader(name, value)` / `defaultHeaders(Map)` | Merged case-insensitively into every request. |
| `idempotencyKeys(boolean)` | Auto-generate keys for charged POSTs (default on). |
| `maxCredits(double)` | Spend guard, see below. |
| `logger(VaquillLogger)` | `VaquillLogger.system()` logs through `System.Logger`; the API key is redacted. |

Per call, pass `RequestOptions` as the last argument: `timeout`, `maxRetries`, `idempotencyKey`, extra `header`s.
`client.toBuilder()` derives a client that shares the same spend guard.
The User-Agent is `vaquill-java/<version>`.

### Response metadata

```java
Response<StatuteCountResponse> r = client.statutes().countWithResponse(request);
r.getData();              // the model
r.getStatusCode();
r.getRequestId();
r.getCreditsConsumed();   // from the body, falling back to meta.creditsConsumed
r.isIdempotentReplayed(); // the server replayed a stored answer, nothing was charged
r.getRateLimit();
```

### Async

```java
CompletableFuture<StatuteCountResponse> f = client.statutes().countAsync(request);
```

Async calls run on an SDK-owned daemon pool and use the same retries and spend guard as blocking calls.

## Errors

Every failure is an unchecked `VaquillException`.

```
VaquillException
  ConnectionException, RequestTimeoutException, ResponseParseException
  SpendGuardExceededException
  WebhookVerificationException, WebhookPayloadException
  ApiStatusException            statusCode, code, requestId, retryable, retryAfterSeconds, errors, body, headers
    BadRequestException (400)
    AuthenticationException (401)
    InsufficientCreditsException (402)
    PermissionDeniedException (403)
    NotFoundException (404)
    ConflictException (409)
      IdempotencyInProgressException, IdempotencyReplayUnavailableException
    UnprocessableEntityException (422)
      IdempotencyKeyReusedException
    RateLimitException (429)
      DailyCapExceededException
    InternalServerException (5xx)
```

`IdempotencyConflict` is a marker interface implemented by the three idempotency exceptions, so `catch` blocks can match them with an `instanceof` check.
The 422 message is `Validation failed: ` followed by the first rejected fields, for example `body: Field required`.
A 2xx whose body is not the documented JSON raises `ResponseParseException`.
A `Deprecation` or `Sunset` response header logs one warning per endpoint.

```java
try {
    client.statutes().search(req);
} catch (InsufficientCreditsException e) {
    // top up
} catch (RateLimitException e) {
    Thread.sleep((long) (e.getRetryAfterSeconds() * 1000));
} catch (ApiStatusException e) {
    log.error("failed {} request {}", e.getStatusCode(), e.getRequestId());
}
```

## Retries

- Exponential backoff from 0.5s doubling to an 8s cap, plus 0 to 25% jitter.
- `retry-after-ms`, then `Retry-After` (seconds or an HTTP date) are honoured. A wait over 120s is raised at once instead of slept.
- Retried: the codes `rate_limited`, `idempotency_in_progress`, `upstream_timeout`, `service_unavailable` and `internal_error`, and otherwise statuses 408, 429 and 5xx. A response that says `retryable: false` is not retried, and neither is 501.
- Never retried: `insufficient_credits` and `daily_cap_exceeded`.
- Connect failures are always retried. Any other transport error (a dropped connection mid-response) is retried only for GET and HEAD, or when the request carries an Idempotency-Key, because the server may already have done the work.
- A 5xx on a charged call is not retried without a key, for the same reason.

## Idempotency

The 25 charged operations accept an `Idempotency-Key`.
The SDK generates one for every charged POST unless you pass your own (`RequestOptions.builder().idempotencyKey("...")`), so a retried call is charged once.
A key must be 16 to 255 visible ASCII characters; an empty or malformed key is rejected before anything is sent.
`Response.isIdempotentReplayed()` is true when the server answered from a stored result, and a replay counts as 0 credits against the spend guard.

## Spend guard

```java
Vaquill client = Vaquill.builder().maxCredits(50).build();
```

Charged calls are serialised: the guard checks the running total, sends the request and adds the credits actually consumed while holding one lock.
When the total has reached the cap, the next charged call raises `SpendGuardExceededException` and is never sent, so the cap is exact even with many threads.
`client.getCreditsSpent()` returns the total. Free endpoints are never blocked.

## Pagination

Every paginated endpoint has an `iter...` method returning a `Paginator<T>`.

```java
for (StatuteResult hit : client.statutes().iterSearch(request).maxItems(200)) {
    System.out.println(hit.getActId());
}

List<StatuteResult> all = client.statutes().iterSearch(request).maxPages(5).toList();
client.statutes().iterSearch(request).stream().limit(20).forEach(System.out::println);
client.statutes().iterSearch(request).toListAsync();
```

- `maxPages(n)` and `maxItems(n)` set limits before iteration starts (afterwards they throw `IllegalStateException`). `isTruncated()` reports that a limit stopped the walk.
- `isStuck()` is true when the server repeated a cursor or offset, or returned an empty page claiming more; iteration stops instead of looping forever.
- `pages()` iterates page by page.
- A paginator is single use and not thread safe.

Available: `statutes().iterSearch / iterDivisions / iterSectionChanges`, `sessionLaws().iterSearch / iterList / iterChanges / iterBody`, `watches().iterList / iterChanges`, `boards().iterList`.
Charged pages are charged and counted by the spend guard like any other call.

Batch helpers split large inputs, de-duplicate in order and suffix the idempotency key per chunk (`key-1`, `key-2`):

| Helper | Chunk size |
| --- | --- |
| `statutes().resolveBatchAll(citations)` | 500 |
| `statutes().getSectionsAll(actIds)` | 50 |
| `sessionLaws().getBatchAll(ids)` | 200 |

An empty input sends nothing. Each has an `...Async` form.

## Webhooks

Deliveries use Standard Webhooks (`webhook-id`, `webhook-timestamp`, `webhook-signature`).

```java
WebhookEvent event = Webhooks.unwrap(rawBody, headers, System.getenv("VAQUILL_WEBHOOK_SECRET"));
System.out.println(event.getEvent());
```

- Pass the raw request body, not re-serialised JSON.
- `headers` is any `Map<String, ?>`; names are matched case-insensitively and values may be a string or a list.
- The secret is the `whsec_` base64 form or a plain string. An empty, blank or `whsec_`-only secret, and invalid base64 after `whsec_`, throw `IllegalArgumentException` (the message is "The webhook secret has an invalid base64 key after 'whsec_'." and never echoes the secret), so an unset environment variable can never verify a forged event.
- Tolerance is 300 seconds either side of now. Use the longer overloads for another tolerance, several secrets (rotation: a delivery signed with any of them verifies) or the legacy `X-Vaquill-Signature` scheme (off by default, no replay protection).
- `WebhookVerificationException` means do not trust the delivery; `WebhookPayloadException` means the signature was valid but the body is not an event.

## Models and the generator

Models, `...Params` classes, the resource base classes, `OperationIndex` and the test fixture `GeneratedCases` are generated from `../openapi/vaquill-us.json`.

```bash
python3 tools/generate.py           # regenerate
python3 tools/generate.py --check   # fail if the checked-in files differ from the spec
```

CI runs the check, and `SpecDriftTest` fails if an operation in the spec has no SDK method.
Hand-written code lives in `src/main/java/ai/vaquill/sdk` (client, internal transport, pagination, `resources/Statutes` and friends); do not edit generated files.

## Develop

```bash
mvn verify                  # tests plus JaCoCo (line coverage must stay above 85%)
mvn javadoc:javadoc
```

The library targets Java 11 (`--release 11`). `mvn verify` is proven on JDK 11, 17, 21 and 22 (and 27) with the pinned JaCoCo 0.8.16 (`jacoco.version` in `pom.xml`); CI runs 11, 17 and 21.
If a future JDK breaks the coverage step, bump `jacoco.version`; JaCoCo 0.8.12 and older cannot read class files from JDK 24 and newer.
The tests use a local fake server (`com.sun.net.httpserver`) and never reach the network.

### Live smoke test

`LiveSmokeTest` calls the real API with `maxCredits(10)` and prints no secrets.
It is skipped unless you ask for it:

```bash
export VAQUILL_API_KEY=vq_key_...
mvn -Plive test
```

## Release

Releases are cut by pushing a `java-vX.Y.Z` tag, which runs `.github/workflows/java-release.yml`: full Java CI, GPG signing, publish to Maven Central through the Sonatype Central Portal, then a GitHub Release.
The owner-only one-time setup and the exact steps are in [RELEASING.md](RELEASING.md).

What is verified without credentials (JDK 11, `mvn -Prelease -Dgpg.skip=true verify`): the main, sources and javadoc jars build with the Central-required metadata (name, description, url, licence, developer, scm), and signing works against a throwaway local GPG key.
What cannot be tested without the owner's credentials: the real GPG key and the upload to Central.
The first real release is the first time those two steps run.

Manual publishing from a laptop is possible (`mvn -Prelease deploy` with server id `central` in `~/.m2/settings.xml` and `MAVEN_GPG_PASSPHRASE` set), but prefer the workflow.

## Licence

MIT.
