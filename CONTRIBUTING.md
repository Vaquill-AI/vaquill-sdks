# Contributing to the Vaquill SDKs

Thanks for helping. Please read the [Code of Conduct](CODE_OF_CONDUCT.md) first.
Report security issues privately, as described in [SECURITY.md](SECURITY.md).

This repository holds both SDKs and the API contract they are built from:

| Path | What it is |
| --- | --- |
| `python/` | The `vaquill` package for PyPI, including the `vaquill` command line tool |
| `js/` | The `@vaquill/sdk` package for npm |
| `openapi/vaquill-us.json` | The one pinned copy of the US Data API contract, shared by both |
| `CONTRACT_VERSION` | The contract version both SDKs were built from |

## Python (`python/`)

Python 3.11 or newer is required. CI runs 3.11, 3.12 and 3.13.

```bash
cd python
python -m venv .venv
.venv/bin/python -m pip install -e . pytest pytest-asyncio ruff pyright
```

The virtualenv must be at `python/.venv`, because the pyright config in `pyproject.toml` points there.
Run all of these before opening a pull request. CI runs the same.

```bash
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/pyright
.venv/bin/python -m pytest
```

## TypeScript (`js/`)

Node 20 or newer is required. CI runs Node 20, 22 and 24.

```bash
cd js
npm ci
npm run lint          # biome
npm run typecheck     # tsc, strict
npm test              # vitest
npm run build         # tsup, ESM and CJS with types
npm run lint:package  # publint and arethetypeswrong, needs a build first
```

Commit `js/package-lock.json` changes together with the `package.json` change that caused them.

## Both

Tests never call the live API and never need a real key.
Use fake keys such as `vq_key_test_0123456789abcdef`. The secret scan rejects anything that looks like a real `vq_key_` key.

## The contract and generated files

`openapi/vaquill-us.json` is copied from the backend export, never edited here.
When it changes, update `CONTRACT_VERSION` in the same commit and regenerate both SDKs:

- Python: `cd python && .venv/bin/python scripts/gen_models.py && .venv/bin/python scripts/gen_async.py`. Models under `python/src/vaquill/types/` and the async resources are generated, so do not edit them by hand.
- TypeScript: `cd js && npm run gen`. `js/src/_generated/schema.d.ts` is generated, so do not edit it by hand.

Each package's tests check that every operation in the spec has exactly one method.
`CHANGELOG` content is generated from commits and release notes, never written by hand.

## Commits and pull requests

Use [Conventional Commits](https://www.conventionalcommits.org) for commit messages and for the pull request title, because CI checks the title and release notes are generated from them.
Use the package as the scope when a change touches only one: `feat(python): add divisions iterator`, `fix(js): honour Retry-After dates`.
Mark breaking changes with `!` and explain them in the body.
Keep pull requests small and focused, and fill in the template.

## How releases work

Maintainers release one package at a time by pushing a tag with its prefix. Contributors do not need to do anything.
The two packages are versioned independently.

**Python (`vaquill`)**

1. Set `__version__` in `python/src/vaquill/_version.py` and merge it to the default branch.
2. Tag the merged commit: `python-v0.1.0a1` (pre-release, goes to TestPyPI) or `python-v0.1.0` (goes to PyPI).
3. The `Release (Python)` workflow runs the full CI matrix, builds once from the tagged commit, and waits for a reviewer to approve the protected `pypi` environment.
4. After approval it publishes with PyPI Trusted Publishing (no stored token) and creates a GitHub Release with generated notes and the API contract version.

**TypeScript (`@vaquill/sdk`)**

1. Bump `version` in `js/package.json` (`cd js && npm version --no-git-tag-version 0.1.0`) and merge it to the default branch.
2. Tag the merged commit: `js-v0.1.0-rc.1` (any `-suffix` is a pre-release, goes to the `next` dist-tag) or `js-v0.1.0` (goes to `latest`).
3. The `Release (JS)` workflow runs the full CI matrix, builds one tarball from the tagged commit, and waits for a reviewer to approve the protected `npm` environment.
4. After approval it runs `npm publish --provenance --access public` and creates a GitHub Release with generated notes and the API contract version.

A version number is never reused. A bad PyPI release is yanked, a bad npm release is deprecated with `npm deprecate`, and either is fixed forward with a new patch version.
