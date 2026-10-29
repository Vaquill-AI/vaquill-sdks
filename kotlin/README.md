# Vaquill Kotlin SDK

Kotlin client for the [Vaquill US Data API](https://www.vaquill.ai): US primary law (statutes, regulations, court rules, constitutions, session laws) with citation resolution, change history and law-change alerts.

It is built for coroutines.
Every call is a `suspend` function, every paginated endpoint is a `Flow`, and every model is a `kotlinx.serialization` data class.

* Coordinates: `ai.vaquill:vaquill-kotlin`, package `ai.vaquill.sdk`, version 0.1.0.
* Targets JVM 11 and newer.
* Dependencies: `kotlinx-serialization-json` and `kotlinx-coroutines-core`. Transport is the JDK `java.net.http.HttpClient`, so there is no HTTP engine to choose.
* Covers all 36 operations of the frozen contract (`../openapi/vaquill-us.json`, `info.version` 1.0.0).

## Install

The artifact is not published yet.
Once it is on Maven Central:

```kotlin
dependencies {
    implementation("ai.vaquill:vaquill-kotlin:0.1.0")
}
```

Until then, build it locally with `./gradlew build` and use `publishToMavenLocal` (see Publishing).
The release process is in [RELEASING.md](RELEASING.md).

## Quickstart

```kotlin
import ai.vaquill.sdk.VaquillClient
import ai.vaquill.sdk.resources.SearchFilters
import kotlinx.coroutines.runBlocking

fun main() = runBlocking {
    // apiKey defaults to the VAQUILL_API_KEY environment variable.
    VaquillClient { maxCredits = 25.0 }.use { client ->
        println("balance: ${client.credits.balance()}")

        val hits = client.statutes.search("adverse possession", SearchFilters(state = "tx", limit = 5))
        hits.results?.forEach { println(it.actId) }

        val section = client.statutes.resolve("42 U.S.C. 1983")
        println(section)
    }
}
```

Create one client and share it.
It is thread safe, and safe to call from many coroutines at once.
Call `close()` (or use `use {}`) to release its threads.

## Configuration

```kotlin
val client = VaquillClient {
    apiKey = "vq_key_..."                 // default: $VAQUILL_API_KEY
    baseUrl = "https://api.vaquill.ai"    // default: $VAQUILL_BASE_URL, then the production URL
    timeout = Duration.ofSeconds(30)      // per attempt, default 60 s, Duration.ZERO disables it
    maxRetries = 2                        // default 2
    defaultHeader("X-Team", "legal-ops")  // names are matched case-insensitively
    idempotencyKeys = true                // automatic Idempotency-Key on charged calls
    maxCredits = 100.0                    // client-side spend cap
    logger = VaquillLogger.system()       // default; VaquillLogger.NONE silences it
}
```

Per-call overrides go in `RequestOptions(timeout, maxRetries, idempotencyKey, headers)`, the last parameter of every method.
`client.withOptions { ... }` makes a copy that shares the transport and the spend total.
`Authorization` and `Idempotency-Key` cannot be overridden by default or per-call headers.
Headers that the JDK transport owns (`Host`, `Content-Length`, `Connection`, ...) are rejected with `IllegalArgumentException`.

### Timeouts

`timeout` is the total time for one HTTP attempt, from sending the request until the whole response body has been read.
It is enforced with a coroutine `withTimeout` around the JDK call, so a slow body that keeps trickling in is still cut off when the budget is spent.
Each retry gets a fresh budget, so a call can take up to `(maxRetries + 1) * timeout` plus the backoff waits.
Connecting has its own fixed 5 s limit.

This differs from the Python SDK, which uses `httpx.Timeout(60.0, connect=5.0)`: there the 60 s is a limit on each phase (connect, write, and the wait for each chunk of the response), not on the whole response, so a response that keeps sending bytes can run longer than 60 s.
The JDK `HttpClient` has no per-read timeout, so the Kotlin SDK cannot reproduce that behaviour without replacing the transport.
The practical consequence is that the Kotlin timeout is stricter for very large bodies: raise `timeout` (or pass `RequestOptions(timeout = ...)`) for them, or use `Duration.ZERO` to disable it.

The `User-Agent` is `vaquill-kotlin/0.1.0 kotlin/<version> java/<version> <os>`.

The logger receives every line after API-key redaction (`vq_key_...` becomes `vq_key_***`), and idempotency keys are logged by their first 8 characters only.

## Which calls cost credits

An operation is charged when the contract declares the `Idempotency-Key` header on it.
That is 25 operations: everything on `statutes` except `coverage`, everything on `sessionLaws`, and `watches.changeDiff`.
Boards, watches (except the diff), `credits.balance` and `pricing.get` are free.
Read the live prices with `client.pricing.get()`.

## Response metadata

Methods return the model.
Wrap any call (or several) in `withResponse` to also get the status, headers, request id, rate-limit headers and credits:

```kotlin
val r = client.withResponse { statutes.count(state = "wa") }
println(r.data.count)
println("${r.statusCode} ${r.requestId} consumed=${r.creditsConsumed} replayed=${r.idempotentReplayed}")
println(r.rateLimit.remaining)
```

If the block makes several requests, the last response is reported.

## Errors

Everything the SDK throws extends `VaquillException`.

```text
VaquillException
  SpendGuardExceededException         client-side maxCredits reached, nothing was sent
  ResponseParseException              a 2xx body was not valid JSON or had the wrong shape
  WebhookVerificationException
    WebhookPayloadException           signature fine, body not an event
  ApiConnectionException              no HTTP response
    ApiTimeoutException
  ApiStatusException (sealed)         status, code, requestId, retryable, retryAfterSeconds, errors, body, headers
    BadRequestException               400
    AuthenticationException           401
    InsufficientCreditsException      402 or code insufficient_credits (never retried)
    PermissionDeniedException         403
    NotFoundException                 404
    ConflictException                 409
      IdempotencyInProgressException         (also IdempotencyConflict)
      IdempotencyReplayUnavailableException  (also IdempotencyConflict)
    UnprocessableEntityException      422, message appends the first errors[] reasons
      IdempotencyKeyReusedException          (also IdempotencyConflict)
    RateLimitException                429
      DailyCapExceededException              code daily_cap_exceeded (never retried)
    InternalServerException           5xx
    UnexpectedStatusException         any other 4xx or 5xx
```

The class is chosen by the error `code` first, then by status, so an unknown future code still gives the status class.

```kotlin
try {
    client.statutes.getSection("TX-PEN-22.01")
} catch (e: NotFoundException) {
    println("missing (request ${e.requestId})")
} catch (e: RateLimitException) {
    println("retry in ${e.retryAfterSeconds}")
} catch (e: ApiStatusException) {
    println("${e.status} ${e.code}: ${e.message}")
}
```

## Retries

* Up to `maxRetries` (default 2) retries with exponential backoff from 0.5 s to 8 s, scaled down by 0 to 25 percent jitter.
* `retry-after-ms`, `Retry-After` seconds and `Retry-After` HTTP dates are honoured. A wait longer than 120 s raises the error immediately.
* Retried: 408, 429, 5xx (except 501) and the codes the server marks retryable. Never retried: `insufficient_credits`, `daily_cap_exceeded`, any response with `retryable: false`.
* Connect failures (refused, unresolved host) never reached the server, so they are always retried.
* Other transport failures are ambiguous. They are retried only for GET and HEAD, or when the call carries an idempotency key.
* A 5xx on a charged call is not retried unless the call has an idempotency key, because it may already have been billed.

## Idempotency

Charged calls get a fresh UUID `Idempotency-Key` automatically, reused on every retry of that call.
Pass your own for a retry that spans processes:

```kotlin
client.statutes.search("trespass", options = RequestOptions(idempotencyKey = "order-7731-search-1"))
```

A key must be 16 to 255 visible ASCII characters; an empty or invalid key throws `VaquillException` before any request.
`ApiResponse.idempotentReplayed` is true when the server replayed a stored answer (read from `Idempotent-Replayed`); a replay is not charged again and not counted by the spend guard.
The batch helpers suffix a caller key with `-1`, `-2`, ... for chunks after the first, because each chunk has a different body.

## Spend guard

`maxCredits` caps what this client (and clients derived from it) will spend.
Charged calls are serialised by a coroutine `Mutex` while the cap is set, so the check, the call and the accounting are one step and the cap is exact even under heavy concurrency.
When the cap is reached the call throws `SpendGuardExceededException` and nothing is sent.
Free calls are never blocked.
`client.creditsSpent` shows the running total.

## Pagination

Every paginated endpoint has an `iter...` method returning a `Paginator<T>`, a cold set of `Flow`s:

```kotlin
val p = client.statutes.iterSearch("easement", SearchFilters(state = "ca"), maxPages = 3)
p.items().collect { println(it.actId) }        // every item
p.pages().collect { page -> println(page.size) } // or page by page
println("${p.truncated} ${p.stuck}")
```

Charged endpoints spend credits on every page.
Set `maxPages` or `maxItems` unless you mean to read everything.
`truncated` is true when a guard cut the result short.
`stuck` is true when the server repeated the position it was just sent, or answered an empty page with `hasMore: true`; the loop stops instead of paying for the same page forever.

| Method | Pages by |
| --- | --- |
| `statutes.iterSearch` | `nextOffset`, else `hasMore` and the row count |
| `statutes.iterDivisions` | `nextCursor` |
| `statutes.iterSectionChanges` | `beforeId` (or `sinceId` with `order = "asc"`) |
| `sessionLaws.iterSearch` | `offset` and `hasMore` |
| `sessionLaws.iterList` | `nextCursor` |
| `sessionLaws.iterChanges` | `sinceId` |
| `sessionLaws.iterBody` | `nextCursor` until `pageEnd` reaches `totalChars` |
| `watches.iterList`, `watches.iterChanges`, `boards.iterList` | offset or id windows (free) |

Batch helpers de-duplicate, chunk and join the results:

* `statutes.resolveBatchAll(citations)` sends 500 per call.
* `statutes.getSectionsAll(actIds)` sends 50 per call.
* `sessionLaws.getBatchAll(ids)` sends 200 per call.

## Webhooks

Verify the raw request body, never re-serialised JSON.

```kotlin
val event = Webhooks.unwrap(
    payload = rawBody,                       // String or ByteArray
    headers = requestHeaders,                // webhook-id, webhook-timestamp, webhook-signature
    secret = System.getenv("VAQUILL_WEBHOOK_SECRET"),
)
println("${event.event} ${event.firedAt} ${event.extra}")
```

* Standard Webhooks signatures with a `whsec_` base64 secret (or a plain UTF-8 secret), and a timestamp tolerance of 300 s by default.
* Pass several secrets (`secrets = listOf(new, old)`) to accept both during a rotation.
* An empty or blank secret, or a `whsec_` secret that is not valid base64, throws `IllegalArgumentException`. A misconfigured environment can never accept a forged event.
* `Webhooks.verify` checks the signature only; `unwrap` also parses the event.
* The legacy `X-Vaquill-Signature` header is rejected unless you pass `allowLegacy = true`. It has no replay protection.

## Operations

| Operation | Method | Credits |
| --- | --- | --- |
| `get_pricing` | `pricing.get` | free |
| `get_credit_balance` | `credits.balance` | free |
| `list_boards` | `boards.list`, `boards.iterList` | free |
| `list_watches` | `watches.list`, `watches.iterList` | free |
| `create_watch` | `watches.create` | free |
| `update_watch` | `watches.update` | free |
| `delete_watch` | `watches.delete` | free |
| `test_watch` | `watches.test` | free |
| `list_watch_changes` | `watches.changes`, `watches.iterChanges` | free |
| `list_watch_deliveries` | `watches.deliveries` | free |
| `get_watch_change_diff` | `watches.changeDiff` | charged |
| `list_statutes_coverage` | `statutes.coverage` | free |
| `search_statutes` | `statutes.search`, `statutes.iterSearch` | charged |
| `count_statute_sections` | `statutes.count` | charged |
| `resolve_statute_citation` | `statutes.resolve` | charged |
| `resolve_statute_citations_batch` | `statutes.resolveBatch`, `statutes.resolveBatchAll` | charged |
| `extract_statute_citations` | `statutes.extractCitations` | charged |
| `list_statute_divisions` | `statutes.divisions`, `statutes.iterDivisions` | charged |
| `get_section` | `statutes.getSection` | charged |
| `get_section_body` | `statutes.getSectionBody` | charged |
| `get_sections_batch` | `statutes.getSectionsBatch`, `statutes.getSectionsAll` | charged |
| `get_section_changes` | `statutes.sectionChanges`, `statutes.iterSectionChanges` | charged |
| `get_section_cited_by` | `statutes.citedBy` | charged |
| `get_section_cross_state` | `statutes.crossState` | charged |
| `get_section_definitions` | `statutes.definitions` | charged |
| `get_section_enactments` | `statutes.enactments` | charged |
| `get_section_neighbors` | `statutes.neighbors` | charged |
| `get_section_rulemaking` | `statutes.sectionRulemaking` | charged |
| `get_part_rulemaking` | `statutes.partRulemaking` | charged |
| `search_session_laws` | `sessionLaws.search`, `sessionLaws.iterSearch` | charged |
| `list_session_laws` | `sessionLaws.list`, `sessionLaws.iterList` | charged |
| `get_session_law` | `sessionLaws.get` | charged |
| `get_session_law_body` | `sessionLaws.getBody`, `sessionLaws.iterBody` | charged |
| `get_session_law_versions` | `sessionLaws.versions` | charged |
| `get_session_laws_batch` | `sessionLaws.getBatch`, `sessionLaws.getBatchAll` | charged |
| `get_session_law_changes` | `sessionLaws.changes`, `sessionLaws.iterChanges` | charged |

`OperationsTest` fails if this list and the spec disagree: it sends one request per operation to a local server and checks the method, path, body and whether an `Idempotency-Key` was sent.
For an endpoint newer than the SDK, use `client.rawRequest(method, path, query, body, charged)`.

Path segments are validated (empty, `.` and `..` are rejected) and percent-encoded, including `/`.
Query values follow the contract: booleans are `true` or `false`, `Instant`, `OffsetDateTime` and `LocalDate` values are RFC 3339 and unquoted, and lists repeat the key.
A list that the API also accepts as a single string (for example `corpusType`) is sent as a plain string when it has one element.

## Models

`ai.vaquill.sdk.models` holds one `@Serializable` data class per schema in the contract (132 classes).
It is generated by `tools/generate_models.py` from `../openapi/vaquill-us.json`:

```bash
python3 tools/generate_models.py          # rewrite Models.kt
python3 tools/generate_models.py --check  # fail if it is stale (CI runs this)
```

Models are lenient on the wire: unknown fields are ignored, enum values are plain `String`s (the generated `CorpusTypes` object lists the known ones), integers are `Long` and numbers are `Double`.
A test compares every schema's properties with the compiled classes and decodes a sample document for each, so contract drift fails the build.

## Building

```bash
./gradlew build          # compile, test, coverage verification (minimum 85 percent), jars
./gradlew koverLog       # print line coverage
./gradlew test           # unit tests against a local fake server, no network
```

The wrapper pins Gradle 8.14.x so the build also runs on JDK 11.
Coverage excludes the generated `ai.vaquill.sdk.models` package.

### Live smoke test

Normal builds never call production.
The opt-in smoke test makes a few free calls and one charged call (about 1 credit), capped at 5 credits client-side:

```bash
VAQUILL_API_KEY=vq_key_... ./gradlew liveSmoke -PliveSmoke
```

## Publishing

`maven-publish` is configured for `ai.vaquill:vaquill-kotlin` with a sources jar, a javadoc jar and full POM metadata (name, description, url, MIT license, developer, scm, issue tracker).
The javadoc jar is generated by Dokka (`org.jetbrains.dokka-javadoc` 2.2.0, Javadoc-format HTML of the public Kotlin API) because the Java `javadoc` task has no sources in a Kotlin project.
No credentials are stored in the repository.

```bash
./gradlew publishToMavenLocal    # local check, no signing, no network upload
```

Releases are made by the `kotlin-release.yml` workflow when a `kotlin-vX.Y.Z` tag is pushed.
It signs with an in-memory GPG key (`signingInMemoryKey`, `signingInMemoryKeyPassword`) and uploads to the Sonatype Central Portal with a user token (`centralUsername`, `centralPassword`).
Gradle reads those from `ORG_GRADLE_PROJECT_*` environment variables or `-P` properties; signing is on only when a key is supplied, and the Central repository is registered only when both token parts are supplied.
The one-time owner setup and the release steps are in [RELEASING.md](RELEASING.md).

### What has and has not been tested

Tested without credentials:

* `./gradlew build` and the unit tests on JDK 11, 17, 21 and 22.
* `publishToMavenLocal`: the generated POM, the module metadata and the three jars, including the contents of the javadoc jar.
* The signing path, with a throwaway GPG key generated for the test and discarded: all five artifacts get a `.asc` signature.

Not tested, and cannot be without the owner's accounts:

* Signing with the real Vaquill key, and the real key being accepted by the key servers Central checks.
* Uploading to the Central Portal, its namespace verification and validation rules, and the final release.
* The `kotlin-release.yml` workflow itself, which has never run.

Expect the first release to need a fix or two.
Use a `-rc.1` tag first.

## Java interop

The client is usable from Java through `VaquillClient.builder()`, `Webhooks.verify`/`unwrap` (static methods) and `CoroutineScope`-based wrappers of your choice.
A dedicated Java SDK exists separately.
