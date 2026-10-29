# Releasing the Go SDK

A Go module is published by a git tag.
There is no registry upload and no secret.
The module path is `github.com/Vaquill-AI/vaquill-sdks/go`, and it lives in the `go/` subdirectory, so the tag must carry that prefix.
A plain `v0.1.0` tag is ignored by the Go tooling for this module.
The tag is `go/v0.1.0`.

## Steps

1. Pick the version.
   While the major version is 0, minor releases may change the API.
   Do not use a `v2` or higher tag without also changing the module path to end in `/v2`.
2. Set `Version` in `go/config.go` to the same number without the `v`, for example `const Version = "0.1.0"`.
3. Regenerate and test on the minimum and the newest Go:

   ```bash
   cd go
   go generate ./...
   git diff --exit-code -- .
   go vet ./... && go vet -tags live ./...
   gofmt -l .
   staticcheck ./... && staticcheck -tags live ./...   # CI pins 2026.2.2
   GOTOOLCHAIN=go1.23.0 go test -race ./...
   go test -race ./...
   ```

4. Merge to the default branch.
   The release workflow refuses a tag whose commit is not on it.
5. Tag the merged commit and push the tag:

   ```bash
   git tag go/v0.1.0
   git push origin go/v0.1.0
   ```

   Use `go/v0.2.0-rc.1` for a pre-release.
6. `.github/workflows/go-release.yml` then:
   - runs `go-ci.yml` on the tag (Go 1.23.0, oldstable and stable, vet, staticcheck, generated code),
   - checks the tag against `Version` in `go/config.go` and the module path in `go/go.mod`,
   - creates the GitHub Release with generated notes,
   - fetches the version through `proxy.golang.org` (retrying for about two minutes) and asks `pkg.go.dev` to index it.
7. Check it from a clean directory:

   ```bash
   mkdir /tmp/check && cd /tmp/check && go mod init example.com/check
   GOPROXY=https://proxy.golang.org go get github.com/Vaquill-AI/vaquill-sdks/go@v0.1.0
   ```

   The docs appear at https://pkg.go.dev/github.com/Vaquill-AI/vaquill-sdks/go.

## Rules

- Never move or delete a published tag.
  The proxy caches a version forever and the checksum database remembers it.
  Fix forward with the next patch version.
  If a version is broken, add `retract v0.1.0 // reason` to `go/go.mod` in the next release.
- The `go` directive in `go/go.mod` is the real minimum (`iter.Seq2` needs 1.23).
  Raising it is a breaking change for users; change the matrix entry in `go-ci.yml` at the same time (CI checks they agree).
- The Python and JavaScript packages release independently with `python-v*` and `js-v*` tags.
