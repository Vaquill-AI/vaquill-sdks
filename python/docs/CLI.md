# Command line

`vaquill` is installed with the package.
It uses only the standard library and the SDK client, so it adds no dependencies.
Run `vaquill COMMAND --help` for the flags of any command.

## Authentication and global options

The key comes from `--api-key` or the `VAQUILL_API_KEY` variable.
It is never stored on disk and never printed: error text and `--debug` logs have any `vq_key_` value replaced with `vq_key_[redacted]`.

| Option | Meaning |
| --- | --- |
| `--api-key KEY` | API key. Prefer the variable, because a flag is visible in the process list. |
| `--base-url URL` | API host. Defaults to `VAQUILL_BASE_URL`, then `https://api.vaquill.ai`. |
| `--timeout SECONDS` | Per-request timeout. |
| `--max-retries N` | Retries after the first attempt (default 2). |
| `--max-credits N` | Spend guard: a charged call is refused once N credits have been used in this run. |
| `--json` | Print the response as JSON on stdout. |
| `--no-color` | Never use colour. |
| `--debug` | Log requests to stderr and show a traceback on failure. |

Global options work before or after the command name.

## Commands

| Command | What it does | Cost |
| --- | --- | --- |
| `search QUERY [--corpus-type T ...] [--state S] [--limit N] [--offset N]` | Search statutes, regulations and rules | charged |
| `resolve CITATION` | Resolve a citation to its section | charged |
| `section ACT_ID [--body]` | A section's metadata, or its text with `--body` | charged |
| `coverage` | What the corpus holds per jurisdiction | free |
| `credits` | Your credit balance | free |
| `pricing` | The credit price of every endpoint | free |
| `watches list [--limit N] [--offset N]` | List watches | free |
| `watches create CORPUS_TYPE [--state S] [--channel C] [--webhook-url U] [--webhook-secret S] [--email E]` | Create a watch | free |
| `watches delete WATCH_ID` | Delete a watch | free |
| `watches changes WATCH_ID [--limit N] [--since-id N] [--before-id N] [--order asc\|desc]` | Changes a watch recorded | free |
| `watches deliveries WATCH_ID [--limit N]` | Recent deliveries and delivery health | free |
| `webhook verify --secret S --id I --timestamp T --signature SIG [--file F] [--tolerance N]` | Verify a Standard Webhooks signature offline | none |
| `version` | Print the SDK and Python versions | none |
| `api METHOD PATH [--query K=V ...] [--data JSON] [--limit N] [--charged]` | Call any endpoint and print the JSON | see below |

Prices are not repeated here: run `vaquill pricing` for the live table.

## Output

Human output is a compact table or a list of `key  value` lines, clipped to the terminal width.
Colour is used only when stdout (or stderr, for messages) is a terminal and `NO_COLOR` is unset and `--no-color` is absent.

`--json` prints the response model dumped by alias, so the keys are the API's camelCase names (`creditsConsumed`, `actId`).
The shape is the same as the SDK's `model_dump(mode="json", by_alias=True)`.
`watches delete` prints `{"deleted": true, "id": "..."}`, `version` prints `{"version": ..., "python": ...}` and `webhook verify` prints `{"valid": true, "event": ...}`.

Messages never go to stdout.
Charged commands print `credits used: N` on stderr after the result, so `vaquill search ... --json | jq` stays clean.

## Pages and cost

The CLI never paginates or loops by itself.
`search`, `watches list` and `watches changes` make exactly one request.
When the server reports more results, a notice on stderr names the flag that continues (`--offset N`, `--before-id N`, `--since-id N`).
Each continued search call is charged again.

## The `api` command

`vaquill api GET /api/v1/watches --query limit=5` sends one request and prints the JSON body.
`--query` can repeat, and a repeated key becomes a repeated query parameter.
`--data` takes a JSON string, or `-` to read it from stdin.
`--limit N` sets the `limit` query parameter.
The CLI cannot know which paths are charged, so pass `--charged` for one that is.
That adds an idempotency key, applies `--max-credits` and counts the credits in `credits used`.
When the body says `hasMore`, a notice names the next page value if the body has one (`nextCursor` or `nextOffset`).

## Webhook verification

```bash
vaquill webhook verify --secret "$WEBHOOK_SECRET" \
  --id "$WEBHOOK_ID" --timestamp "$WEBHOOK_TIMESTAMP" --signature "$WEBHOOK_SIGNATURE" \
  --file body.json
```

It makes no network call and needs no API key.
The body must be the exact bytes received: a trailing newline added by `echo` makes the signature fail, so use `--file`, a redirect (`< body.json`) or `printf %s`.
`--secret` falls back to the `VAQUILL_WEBHOOK_SECRET` variable.
Timestamps more than `--tolerance` seconds (default 300) from the current time are rejected.
Only Standard Webhooks headers are accepted; the legacy header has no replay protection.
The signature is checked before the body is parsed, so a body that is not a Vaquill event still passes with `"event": null`.

## Exit codes

| Code | Meaning |
| --- | --- |
| 0 | Success |
| 1 | Any other error, including a failed webhook verification |
| 2 | Usage error (bad flag, unreadable file, invalid JSON) |
| 3 | Authentication: missing or malformed key, HTTP 401 or 403 |
| 4 | Insufficient credits (HTTP 402) or the `--max-credits` guard |
| 5 | Rate limited, including the daily cap (HTTP 429) |
| 6 | Not found (HTTP 404) |
| 7 | Network failure or timeout |

A failure prints one line to stderr, `error: MESSAGE (status N, code C, request id R)`, and no traceback unless `--debug` is set.
