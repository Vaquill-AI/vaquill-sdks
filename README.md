# Vaquill SDKs

Official client libraries for the Vaquill US Data API: primary law (statutes, regulations, court rules, session laws) with citation resolution, search and law-change alerts.

| Language | Package | Install | Docs |
| --- | --- | --- | --- |
| Python 3.11+ | [`vaquill`](python/) | `pip install vaquill` | [python/README.md](python/README.md) |
| TypeScript, Node 20+ | [`@vaquill/sdk`](js/) | `npm install @vaquill/sdk` | [js/README.md](js/README.md) |

Both read your key from `VAQUILL_API_KEY` and share the same behavior: retries with backoff, idempotency keys on charged calls, a spend guard, typed errors and webhook signature verification.
The Python package also installs a `vaquill` command line tool.

## Repository layout

- `python/` and `js/`: the two packages, released independently.
- `openapi/vaquill-us.json`: the API contract both are built from. `CONTRACT_VERSION` records its version.
- `.github/`: CI, CodeQL, scorecard and the two release workflows.

See [CONTRIBUTING.md](CONTRIBUTING.md) to work on the SDKs, [SECURITY.md](SECURITY.md) to report a vulnerability, and the [license](LICENSE) (MIT).
