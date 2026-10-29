# CI contract gates

Two jobs in `.github/workflows/ci.yml` guard `openapi/vaquill-us.json`.

## spectral

Lints the spec with `.spectral.yaml` (extends `spectral:oas`).
Errors fail the job: missing or duplicate `operationId`, missing operation tags, empty descriptions, and operations with no documented 4xx or `default` response.
Warnings are printed and do not fail.
Run it locally:

```bash
npx --yes @stoplight/spectral-cli@6.17.0 lint openapi/vaquill-us.json --ruleset .spectral.yaml
```

## contract-diff

Pull requests only. Compares the spec on the PR with `origin/<base>:openapi/vaquill-us.json` using a pinned, checksum-verified `oasdiff` release.
Breaking changes fail the job unless the PR title contains `!:` (for example `feat(api)!: drop a field`) or the PR has the `breaking-contract` label.
Adding or removing the label, or editing the title, re-runs the checks.
The job is skipped on pushes and release runs, and `ci-ok` treats a skipped job as passing.

To bump oasdiff, change `OASDIFF_VERSION` and `OASDIFF_SHA256` (the `oasdiff_<version>_linux_amd64.tar.gz` line of the release `checksums.txt`) together.
