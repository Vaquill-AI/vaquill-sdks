# vaquill

[![PyPI](https://img.shields.io/pypi/v/vaquill)](https://pypi.org/project/vaquill/) [![Python](https://img.shields.io/pypi/pyversions/vaquill)](https://pypi.org/project/vaquill/) [![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](https://github.com/Vaquill-AI/vaquill-sdks/blob/main/LICENSE)

Python SDK for the Vaquill US primary law Data API: statutes, regulations, court rules, constitutions, session laws and law-change alerts.

Server-side use only: an API key (`vq_key_...`) must never ship to a browser.
Python 3.11 or newer. Sync and async clients with the same methods.
The public API follows semantic versioning and may change in minor versions before 1.0.

```python
from vaquill import Vaquill

client = Vaquill()  # reads VAQUILL_API_KEY; VAQUILL_BASE_URL overrides the host

# 2 credits. Even an unresolved citation is charged: the answer is what you pay for.
result = client.statutes.resolve("42 U.S.C. 1983")
if result.resolved and result.section:
    body = client.statutes.get_section_body(result.section.act_id)  # 6 credits
    print(body.plain)

hits = client.statutes.search(
    "statute of limitations for medical malpractice", state="ca"
)  # 4 credits
for hit in hits.results:
    print(hit.citation, hit.section_title)
print(hits.credits_consumed, client.credits_spent)
```

Async is the same with `AsyncVaquill` and `await`:

```python
import asyncio
from vaquill import AsyncVaquill


async def main() -> None:
    async with AsyncVaquill() as client:
        balance = await client.credits.balance()
        print(balance.credits_remaining)


asyncio.run(main())
```

## Documentation

- [Python guide](https://www.vaquill.ai/docs/api-guide/sdks/python) and the [SDK overview](https://www.vaquill.ai/docs/api-guide/sdks/overview)
- [Data API guide](https://www.vaquill.ai/docs/api-guide/overview): authentication, pagination, errors, alerts
- [API reference](https://www.vaquill.ai/docs/api-reference/): every endpoint and field
- Get an API key at [app.vaquill.ai/settings](https://app.vaquill.ai/settings)
- Source, issues and releases: [Vaquill-AI/vaquill-sdks](https://github.com/Vaquill-AI/vaquill-sdks)

## Namespaces

| Namespace | What it does |
| --- | --- |
| `client.statutes` | search, resolve, sections and their text, browse, changes, enactments, rulemaking, cross-references, citation extraction (`extract_citations` costs 0 credits with `resolve=False`) |
| `client.session_laws` | acts as enacted: search, list, record, text, versions, changes |
| `client.watches` | law-change alerts by webhook or email |
| `client.boards` | the sources a watch can follow |
| `client.credits` | `balance()` |
| `client.pricing` | `get()` the credit price of every endpoint |

All 36 operations, their method names and which ones cost credits are in [docs/OPERATIONS.md](docs/OPERATIONS.md).
Required arguments come first and may be positional; optional ones are keyword-only `snake_case` (sent to the API as camelCase).

## Errors

Every failure is a `VaquillError`. Status errors carry `status_code`, `request_id` and the parsed body.

```python
import vaquill

try:
    client.statutes.resolve("42 U.S.C. 1983")
except vaquill.InsufficientCreditsError:
    ...  # never retried; top up credits
except vaquill.RateLimitError as err:
    print(err.retry_after_seconds)  # seconds; the client already retried with backoff
except vaquill.APIStatusError as err:
    print(err.status_code, err.request_id)
```

## Pagination and the credit warning

`iter_*` helpers hide the offset, cursor and `sinceId`/`beforeId` styles behind one iterator.
**On a charged endpoint every page spends credits.** Iterating a whole result set can cost far more than one call, so always set `max_pages` or `max_items`.

```python
pager = client.statutes.iter_search(
    "negligence", state="ny", limit=10, max_pages=3
)  # at most 12 credits
for hit in pager:
    print(hit.citation)
print(pager.truncated)  # True when the guard stopped it with more available

for page in client.statutes.iter_divisions("STATE", state="wa", max_items=100).pages():
    ...  # whole pages, to control cost yourself
```

## Spend guard

```python
client = Vaquill(
    max_credits=500
)  # charged calls raise SpendGuardExceeded once 500 credits are used
client.credits_spent  # running total across this client and any with_options() copy
client.pricing.get()  # free: the live price list
```

Charged calls send an `Idempotency-Key` automatically and are only retried when that is safe.
Pass `idempotency_key="..."` to any call to supply your own.

## Raw responses

```python
raw = client.with_raw_response.request(
    "GET",
    "/api/v1/us/statutes/resolve",
    cast_to=dict,
    params={"cite": "42 U.S.C. 1983"},
    charged=True,
)
raw.request_id, raw.rate_limit.remaining, raw.credits_charged_this_call, raw.parse()
```

`client.raw_request(method, path, ...)` reaches endpoints newer than this SDK and returns an `APIResponse`; call `.parse()` for the decoded JSON (the TypeScript `rawRequest` returns the parsed value directly).

## Webhooks

Verify the raw request body, never re-serialised JSON.

```python
from vaquill import verify_webhook, WebhookVerificationError

try:
    event = verify_webhook(raw_body, request_headers, WEBHOOK_SECRET)
except WebhookVerificationError:
    ...  # respond 400
```

A watch is created with `client.watches.create("state", state="wa", webhook_url=..., webhook_secret=...)`.
See [examples/](examples/) for runnable versions (`resolve_citation.py`, `search_and_paginate.py`, `watch_and_verify_webhook.py`); the test suite runs them against a fake server.

## Command line

Installing the package also installs a `vaquill` command (standard library only, no extra dependencies).

```bash
export VAQUILL_API_KEY=vq_key_...
vaquill resolve "42 U.S.C. 1983"                  # 2 credits
vaquill search "medical malpractice limitations" --state ca --limit 5 --json
vaquill section USC_T42_C21_S1983 --body                # 6 credits
vaquill credits                                   # free
vaquill webhook verify --secret "$SECRET" --id "$ID" --timestamp "$TS" --signature "$SIG" < body.json
```

Charged commands print `credits used: N` on stderr, so stdout stays pipeable.
Exit codes: 0 ok, 1 error, 2 usage, 3 auth, 4 no credits, 5 rate limited, 6 not found, 7 network.
Every command, flag and the JSON shape are in [docs/CLI.md](docs/CLI.md).

## Types

Responses are Pydantic v2 models in `vaquill.types`, generated from `openapi/vaquill-us.json` by `scripts/gen_models.py`.
Unknown fields are kept and unknown enum values never raise: a field typed `Status | str` holds the enum member for values this SDK knows and the plain string for new ones.
Every top-level response has `credits_consumed`, `request_id` and `idempotent_replayed`.

## Development

```bash
.venv/bin/python scripts/gen_models.py   # regenerate src/vaquill/types after changing the spec
.venv/bin/python scripts/gen_async.py    # regenerate src/vaquill/resources/_async after editing a sync resource
.venv/bin/python -m pytest -q
```

The sync resources in `src/vaquill/resources/` are the one hand-written definition; the async ones are derived from them mechanically and a test fails on drift.
