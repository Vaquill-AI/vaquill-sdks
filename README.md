# Vaquill SDKs

[![PyPI](https://img.shields.io/pypi/v/vaquill?label=PyPI)](https://pypi.org/project/vaquill/)
[![npm](https://img.shields.io/npm/v/@vaquill-ai/sdk?label=npm)](https://www.npmjs.com/package/@vaquill-ai/sdk)
[![CI](https://github.com/Vaquill-AI/vaquill-sdks/actions/workflows/ci.yml/badge.svg)](https://github.com/Vaquill-AI/vaquill-sdks/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

Official client libraries for the Vaquill US Data API: primary law (statutes, regulations, court rules, constitutions, session laws) with citation resolution, search and law-change alerts.

| Language | Package | Install | Package README |
| --- | --- | --- | --- |
| Python 3.11+ | [`vaquill`](https://pypi.org/project/vaquill/) | `pip install vaquill` | [python/README.md](python/README.md) |
| TypeScript, built on standard `fetch`, CI-tested on Node 20, 22 and 24 | [`@vaquill-ai/sdk`](https://www.npmjs.com/package/@vaquill-ai/sdk) | `npm install @vaquill-ai/sdk` | [js/README.md](js/README.md) |

More languages are built and tested in this repository but are **not yet published** to a package registry. Until a release is tagged, install them from source (each README says how).

| Language | Package | Status | Package README |
| --- | --- | --- | --- |
| Go 1.23+ | `github.com/Vaquill-AI/vaquill-sdks/go` | not yet published | [go/README.md](go/README.md) |
| Java 11+ | `ai.vaquill:vaquill-sdk` | not yet published | [java/README.md](java/README.md) |
| Kotlin (JVM 11+), coroutines and Flow | `ai.vaquill:vaquill-kotlin` | not yet published | [kotlin/README.md](kotlin/README.md) |

Agent framework integrations, built on the Python and TypeScript SDKs (also not yet published):

| Framework | Package | README |
| --- | --- | --- |
| LangChain | `langchain-vaquill` | [integrations/langchain/README.md](integrations/langchain/README.md) |
| LlamaIndex | `llama-index-tools-vaquill` | [integrations/llamaindex/README.md](integrations/llamaindex/README.md) |
| Vercel AI SDK | `@vaquill-ai/ai-sdk` | [integrations/vercel-ai/README.md](integrations/vercel-ai/README.md) |

Every SDK shares the same behavior: retries with backoff, idempotency keys on charged calls, a spend guard, typed errors, pagination helpers and webhook signature verification.
The Python package also installs a `vaquill` command line tool.

## Documentation

| What | Where |
| --- | --- |
| SDK overview (concepts shared by both languages) | [vaquill.ai/docs/api-guide/sdks/overview](https://www.vaquill.ai/docs/api-guide/sdks/overview) |
| Python guide | [vaquill.ai/docs/api-guide/sdks/python](https://www.vaquill.ai/docs/api-guide/sdks/python) |
| TypeScript guide | [vaquill.ai/docs/api-guide/sdks/typescript](https://www.vaquill.ai/docs/api-guide/sdks/typescript) |
| Command line tool | [vaquill.ai/docs/api-guide/sdks/cli](https://www.vaquill.ai/docs/api-guide/sdks/cli) |
| Data API guide (authentication, pagination, errors, alerts) | [vaquill.ai/docs/api-guide/overview](https://www.vaquill.ai/docs/api-guide/overview) |
| API reference (every endpoint) | [vaquill.ai/docs/api-reference](https://www.vaquill.ai/docs/api-reference/) |
| Get an API key | [app.vaquill.ai/settings](https://app.vaquill.ai/settings) |
| Every operation, its method name and whether it is charged | [Python](python/docs/OPERATIONS.md), [TypeScript](js/README.md#charged-methods) |
| Live credit price of every endpoint (prices are not hard-coded in the SDKs) | `client.pricing.get()` in both SDKs (free); also the [Data API guide](https://www.vaquill.ai/docs/api-guide/overview) |

## Quickstart

1. Create an API key at [app.vaquill.ai/settings](https://app.vaquill.ai/settings). Keys start with `vq_key_`.
2. Export it. Both SDKs read `VAQUILL_API_KEY`:

   ```bash
   export VAQUILL_API_KEY=vq_key_your_api_key_here
   ```

3. Install and make a call.

**Python**

```bash
pip install vaquill
```

```python
from vaquill import Vaquill

client = Vaquill()

# 2 credits. Even an unresolved citation is charged: the answer is what you pay for.
result = client.statutes.resolve("42 U.S.C. 1983")
if result.resolved and result.section:
    body = client.statutes.get_section_body(result.section.act_id)  # 6 credits
    print(body.plain)

print(client.credits_spent, "credits spent in this session")
```

**TypeScript**

```bash
npm install @vaquill-ai/sdk
```

```ts
import { Vaquill } from "@vaquill-ai/sdk";

const client = new Vaquill();

const res = await client.statutes.search({ query: "assault with a deadly weapon", state: "tx" });
console.log(res.results?.length, res.creditsConsumed);
```

**Command line**

```bash
pip install vaquill
vaquill resolve "42 U.S.C. 1983"
vaquill search "medical malpractice limitations" --state ca --limit 5 --json
vaquill credits   # free
```

## Things worth knowing before you build

- **Server side only.** An API key in browser code is readable by anyone. The TypeScript client warns when it detects a browser.
- **Most calls cost credits.** Each response reports `credits_consumed` (Python) or `creditsConsumed` (TypeScript), and the client keeps a running total. Auto-pagination spends credits per page, so read the pagination section of your language's README first.
- **Retries are designed to be safe.** Charged calls carry an `Idempotency-Key`, so when the server honours that header a retried request after a timeout is not billed twice.
  The SDKs never retry a 402 (no credits).
- **Versioning.** The public API of both SDKs follows semantic versioning and may change in minor versions before 1.0.
- **Typed errors.** Every failure is a `VaquillError` subclass carrying the HTTP status, request id and the parsed error body, with `code`, `retryable` and a retry hint when the server sends them.
- **Webhooks.** `verify_webhook` (Python) and `verifyWebhook` (TypeScript) check Standard Webhooks signatures for law-change alerts. See the [alerts guide](https://www.vaquill.ai/docs/api-guide/alerts).

## What you can call

| Area | Examples |
| --- | --- |
| Statutes | search, resolve a citation to a section, section text, browse the hierarchy, amendment history, cross-references, rulemaking, extract citations from a document (free with `resolve=false`, otherwise 2 credits per distinct citation) |
| Session laws | acts as enacted: search, list, record, text, versions, changes |
| Law-change alerts | create a watch on a source, receive webhooks or email, inspect deliveries |
| Account | credit balance (free), pricing for every endpoint |

## Repository layout

- `python/` and `js/`: the published packages, released independently (tags `python-vX.Y.Z` and `js-vX.Y.Z`).
- `go/`, `java/` and `kotlin/`: the other SDKs (tags `go/vX.Y.Z`, `java-vX.Y.Z` and `kotlin-vX.Y.Z`). Each has a `RELEASING.md` with the one-time setup.
- `integrations/`: LangChain, LlamaIndex and Vercel AI packages (tags `langchain-vaquill-vX.Y.Z`, `llama-index-tools-vaquill-vX.Y.Z` and `ai-sdk-vX.Y.Z`).
- `openapi/vaquill-us.json`: the API contract both are built from. `CONTRACT_VERSION` records its version.
- `.github/`: CI per package, CodeQL, OpenSSF Scorecard and a release workflow per package.

## Support

- Bugs and feature requests: [GitHub issues](https://github.com/Vaquill-AI/vaquill-sdks/issues).
- Account and billing questions: contact@vaquill.ai.
- Security reports: see [SECURITY.md](SECURITY.md).
- Contributing: see [CONTRIBUTING.md](CONTRIBUTING.md).

Released under the [MIT license](LICENSE).
