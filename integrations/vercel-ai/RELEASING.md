# Releasing @vaquill-ai/ai-sdk

Releases are cut by pushing a tag.
The workflow is `.github/workflows/integration-vercel-ai-release.yml`.
It publishes with npm trusted publishing (OIDC).
There is no npm token in the repository, in any environment or in the workflow.

## One-time setup (owner only)

Do these once, in this order.

1. **Publish `@vaquill-ai/sdk` first.**
   This package depends on `@vaquill-ai/sdk` (`^0.2.0`).
   `npm install @vaquill-ai/ai-sdk` fails for everyone until that version is on npm.

2. **Create the GitHub Environment `npm-ai-sdk`.**
   Repository `Vaquill-AI/vaquill-sdks`, Settings, Environments, New environment, name exactly `npm-ai-sdk`.
   - Required reviewers: add yourself (and a second person if you have one).
     Tick "Prevent self-review" only if there is a second reviewer.
   - Deployment branches and tags: "Selected branches and tags", add the tag rule `ai-sdk-v*`.
   - Do not add any secret. Trusted publishing needs none.

3. **Register the trusted publisher on npmjs.com.**
   Sign in as an owner of the `@vaquill-ai` organisation, open the package `@vaquill-ai/ai-sdk`, Settings, "Trusted Publisher", choose GitHub Actions and enter:
   - Organization or user: `Vaquill-AI`
   - Repository: `vaquill-sdks`
   - Workflow filename: `integration-vercel-ai-release.yml`
   - Environment name: `npm-ai-sdk`

   The values must match exactly, including case.
   npm may only offer this page once the package exists on the registry.
   If the page is not available for a package that has never been published, check the npm docs for "pending trusted publishers"; if that is also unavailable, the very first version has to be published by you once from your own machine (`npm publish --access public`, with 2FA), and every release after that goes through this workflow.
   Nothing in this repository can do that first publish for you.

4. **Tighten the package after the first release.**
   On the package's npm settings, under "Publishing access", choose "Require two-factor authentication and disallow tokens".
   That makes the trusted publisher the only way to publish.

5. **Check the repository field.**
   `package.json` `repository.url` must stay `git+https://github.com/Vaquill-AI/vaquill-sdks.git`.
   Provenance signing fails if it does not match the repository the workflow runs in.

## Cutting a release

1. Land the change on `main` with the new `version` in `package.json` (the tag must equal it).
2. Tag the commit that is on `main` and push the tag:

   ```bash
   git tag ai-sdk-v0.1.0
   git push origin ai-sdk-v0.1.0
   ```

   A tag with a suffix such as `ai-sdk-v0.2.0-rc.1` publishes to the `next` dist-tag and creates a pre-release.
   A plain `ai-sdk-vX.Y.Z` publishes to `latest`.
3. The workflow runs the full package CI (the `ai` 5, 6, 7 and Node matrix), builds the tarball, runs publint and attw, then waits for a reviewer to approve the `npm-ai-sdk` environment.
4. After approval it runs `npm publish --provenance --access public`, then creates the GitHub Release with the tarball attached.

The workflow refuses to run when the tag is malformed, does not equal `package.json` `version`, or is not on `main`.
A failed publish can be re-run from the Actions tab; npm refuses to republish a version that already exists.

## Supported matrix (measured 2026-10-29)

The same 79 tests, plus typecheck and publint/attw, were run against each combination.

| `ai` | `zod` | Node 20 | Node 22 | Node 24 |
| --- | --- | --- | --- | --- |
| 5.0.15 and newer 5.x | 4 and 3.25.76 | pass | pass | pass |
| 6.x | 4 and 3.25.76 | pass | pass | pass |
| 7.x | 4 and 3.25.76 | not supported by `ai` | pass | pass |

- `ai` 5.0.0 fails the suite (an invalid tool input throws instead of becoming a tool error) and 5.0.10 hangs the agent test, hence the peer range `^5.0.15 || ^6.0.0 || ^7.0.0`.
- `ai` 5 and 6 declare Node 18 or newer, `ai` 7 declares Node 22 or newer, and `@vaquill-ai/sdk` declares Node 20 or newer.
  So the package floor is Node 20 (`engines`), and `ai` 7 users need 22.
  The suite also passes on Node 20 with `ai` 7, but that combination is outside what `ai` supports, so CI does not run it.
- The package source needs no per-major shim: `tool({ description, inputSchema, execute })` is the same in 5, 6 and 7.
  Only the tests differ between majors (`stepCountIs` vs `isStepCount`, `Experimental_Agent` vs `ToolLoopAgent`, `MockLanguageModelV2/V3/V4`), and `test/ai-compat.ts` is the single place that handles that.
- `ai` 5.0.60 is a known bad release for anyone using `ai/test`: it imports `msw` without declaring it.
  This affects the test helpers only, not this package.

## README snippets cannot rot

Every TypeScript block in `README.md` is a file in `examples/`, including the Next.js route handler.
`test/readme.test.ts` fails when the two differ, and `npm run typecheck:examples` compiles them against the installed `ai` (CI runs it on `ai` 7, the major the snippets are written for).
To change a snippet, edit the README block and the matching file in `examples/` together.
