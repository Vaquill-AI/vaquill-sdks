# Operations

All 36 operations of the frozen contract (`openapi/vaquill-us.json`, `info.version` 1.0.0), the SDK method for each, and which ones spend credits.
Each method exists on `Vaquill` and, with `await`, on `AsyncVaquill`.
`tests/test_operations.py` fails if this table and the spec disagree.

## Charged rule

An operation is **charged** when the spec declares the `Idempotency-Key` header parameter on it.
That is 25 operations.
The SDK passes `charged=True` for exactly those: it sends an auto-generated `Idempotency-Key`, retries ambiguous failures safely, checks the `max_credits` spend guard before the call and adds the response's `creditsConsumed` to `client.credits_spent` after it.
The TypeScript SDK applies the same rule.

Free operations: `list_statutes_coverage`, `list_boards`, the watches operations except `get_watch_change_diff`, `get_credit_balance` and `get_pricing`.
Prices are not hard-coded here. Call `client.pricing.get()` (free) for the live matrix.
Some charged calls return `creditsConsumed: 0` (for example a body that is not held); read the figure from the response.

## Naming

The method name is the `operationId` with the namespace noun removed (`search_statutes` is `statutes.search`, `get_session_law_body` is `session_laws.get_body`).
Where the verb carries meaning it is kept (`get_section`, `get_sections_batch`).
`get_section_neighbors` is `statutes.neighbors` (the path is `/related`).

## Call shape

* Required parameters (path parameters first, then required query or body members) come first and may be passed by position.
* Optional parameters are keyword-only, in `snake_case`. The wire name is the API's camelCase (`title_number` is sent as `titleNumber`).
* Unset optional parameters are not sent, so the server default applies.
* Every method also accepts `timeout`, `max_retries`, `idempotency_key` and `headers` as keyword arguments.
* Array parameters take a list. Query arrays are sent as repeated keys.

## Methods

| operationId | SDK method | Route | Cost |
| --- | --- | --- | --- |
| `get_section_cited_by` | `client.statutes.cited_by` | GET `/us/statutes/section/{act_id}/cited-by` | charged |
| `count_statute_sections` | `client.statutes.count` | POST `/us/statutes/count` | charged |
| `list_statutes_coverage` | `client.statutes.coverage` | GET `/us/statutes/coverage` | free |
| `get_section_cross_state` | `client.statutes.cross_state` | GET `/us/statutes/section/{act_id}/cross-state` | charged |
| `get_section_definitions` | `client.statutes.definitions` | GET `/us/statutes/section/{act_id}/definitions` | charged |
| `list_statute_divisions` | `client.statutes.divisions` | GET `/us/statutes/divisions` | charged |
| `get_section_enactments` | `client.statutes.enactments` | GET `/us/statutes/section/{act_id}/enactments` | charged |
| `get_section_rulemaking` | `client.statutes.section_rulemaking` | GET `/us/statutes/section/{act_id}/rulemaking` | charged |
| `get_part_rulemaking` | `client.statutes.part_rulemaking` | GET `/us/statutes/part/{title}/{part}/rulemaking` | charged |
| `extract_statute_citations` | `client.statutes.extract_citations` | POST `/us/statutes/extract-citations` | charged |
| `get_section` | `client.statutes.get_section` | GET `/us/statutes/section/{act_id}` | charged |
| `get_section_body` | `client.statutes.get_section_body` | GET `/us/statutes/section/{act_id}/body` | charged |
| `get_sections_batch` | `client.statutes.get_sections_batch` | POST `/us/statutes/sections` | charged |
| `get_section_neighbors` | `client.statutes.neighbors` | GET `/us/statutes/section/{act_id}/related` | charged |
| `resolve_statute_citation` | `client.statutes.resolve` | GET `/us/statutes/resolve` | charged |
| `resolve_statute_citations_batch` | `client.statutes.resolve_batch` | POST `/us/statutes/resolve` | charged |
| `search_statutes` | `client.statutes.search` | POST `/us/statutes/search` | charged |
| `get_section_changes` | `client.statutes.section_changes` | GET `/us/statutes/section/{act_id}/changes` | charged |
| `get_session_law_changes` | `client.session_laws.changes` | GET `/us/session-laws/changes` | charged |
| `get_session_law` | `client.session_laws.get` | GET `/us/session-laws/{session_law_id}` | charged |
| `get_session_laws_batch` | `client.session_laws.get_batch` | POST `/us/session-laws/batch` | charged |
| `get_session_law_body` | `client.session_laws.get_body` | GET `/us/session-laws/{session_law_id}/body` | charged |
| `list_session_laws` | `client.session_laws.list` | GET `/us/session-laws/list` | charged |
| `search_session_laws` | `client.session_laws.search` | POST `/us/session-laws/search` | charged |
| `get_session_law_versions` | `client.session_laws.versions` | GET `/us/session-laws/{session_law_id}/versions` | charged |
| `get_watch_change_diff` | `client.watches.change_diff` | GET `/watches/{watch_id}/changes/{change_id}/diff` | charged |
| `list_watch_changes` | `client.watches.changes` | GET `/watches/{watch_id}/changes` | free |
| `create_watch` | `client.watches.create` | POST `/watches` | free |
| `delete_watch` | `client.watches.delete` | DELETE `/watches/{watch_id}` | free |
| `list_watch_deliveries` | `client.watches.deliveries` | GET `/watches/{watch_id}/deliveries` | free |
| `list_watches` | `client.watches.list` | GET `/watches` | free |
| `test_watch` | `client.watches.test` | POST `/watches/{watch_id}/test` | free |
| `update_watch` | `client.watches.update` | PATCH `/watches/{watch_id}` | free |
| `list_boards` | `client.boards.list` | GET `/boards` | free |
| `get_credit_balance` | `client.credits.balance` | GET `/credits/balance` | free |
| `get_pricing` | `client.pricing.get` | GET `/api-credits/pricing` | free |

## Auto-pagination

Each helper returns a `SyncPaginator` (or `AsyncPaginator`).
Iterate it for items, call `.pages()` for whole pages, read `.truncated` after iterating.
All accept `max_pages` and `max_items`. On a charged helper every page spends credits, so always set one of them.

| Helper | Wraps | Paging | Cost |
| --- | --- | --- | --- |
| `client.statutes.iter_search` | `search_statutes` | offset (`nextOffset`) | charged |
| `client.statutes.iter_divisions` | `list_statute_divisions` | cursor (`nextCursor`) | charged |
| `client.statutes.iter_section_changes` | `get_section_changes` | `beforeId` (newest first) or `sinceId` (`order="asc"`) | charged |
| `client.session_laws.iter_search` | `search_session_laws` | offset (`hasMore`) | charged |
| `client.session_laws.iter_list` | `list_session_laws` | cursor (`nextCursor`) | charged |
| `client.session_laws.iter_changes` | `get_session_law_changes` | `sinceId` | charged |
| `client.watches.iter_list` | `list_watches` | offset | free |
| `client.watches.iter_changes` | `list_watch_changes` | `beforeId` or `sinceId` (`order="asc"`) | free |
| `client.boards.iter_list` | `list_boards` | offset (`hasMore`) | free |
| `client.session_laws.iter_body` | `get_session_law_body` | cursor (`nextCursor`, `hasMore`), one `SessionLawBodyResponse` per page | charged |

Two guards stop an iteration without a `max_pages` or `max_items`.
`truncated` is True whenever a guard left rows unread, including a `max_items` that cut items off the last page.
`stuck` is True when the server returned the offset or cursor it was just sent, or an empty page with `hasMore: true`.
The iterator then stops, logs a warning on the `vaquill` logger and does not fetch again, so a misbehaving server cannot burn credits.

## Batch helpers

Each wraps one batch operation, splits the input at the spec's per-call cap and returns the members of every response as one flat list in input order.
The `max_credits` spend guard is checked before every chunk, so a guard reached part way raises `SpendGuardExceeded` and the remaining chunks are not sent.
Exact repeats in the input are sent once.
A caller's `idempotency_key` is kept for the first chunk and suffixed with `-<chunk number>` for later ones.
An empty input sends nothing and returns `[]`.

| Helper | Wraps | Cap per call | Returns | Cost |
| --- | --- | --- | --- | --- |
| `client.statutes.resolve_batch_all` | `resolve_statute_citations_batch` | 500 | `results` (`StatuteResolveBatchItem`) | charged |
| `client.statutes.get_sections_all` | `get_sections_batch` | 50 | `sections` (`StatuteResult`) | charged |
| `client.session_laws.get_batch_all` | `get_session_laws_batch` | 200 | `laws` (`SessionLawBatchLaw`) | charged |

`get_sections_all` and `get_batch_all` drop ids with no match; call the single-call method to read `notFound`.

## Argument checks

A path argument that is empty, `.` or `..` raises `ValueError` before any request, because a URL parser would resolve it to another endpoint.
`verify_webhook` raises `ValueError` for an empty or whitespace-only secret (or `whsec_` with no key), so an unset environment variable cannot verify a forged event.
`extract_citations` costs 0 credits when `resolve=False`.
