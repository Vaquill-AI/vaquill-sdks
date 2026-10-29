# @vaquill-ai/ai-sdk

Vaquill US primary law as tools for the [Vercel AI SDK](https://ai-sdk.dev).
Give `generateText`, `streamText` or a `ToolLoopAgent` the ability to search statutes and regulations, read a section, verify a citation and check what changed.
Built on [`@vaquill-ai/sdk`](https://www.npmjs.com/package/@vaquill-ai/sdk).

## Cost warning

**Almost every tool spends credits, and an agent loop can call tools many times.**
Search, section reads, citation resolution and the rest are charged per call; only `creditBalance` is free.
This package therefore caps spending for you: `maxCredits` defaults to **200** credits per process.
Set it deliberately for your use case, and pair it with a step limit (`stopWhen`) on the AI SDK side.

The cap is checked before each call against credits already spent, so the last call may take the total slightly past the limit.
Once the limit is reached, every further paid call returns a `spend_limit` result and sends no request.
Pass `maxCredits: Infinity` to switch the cap off.

## Install

```bash
npm install @vaquill-ai/ai-sdk ai zod
```

`ai` (5.0.15 or newer, 6 or 7) and `zod` (3.25.76+ or 4) are peer dependencies.
The same test suite passes against `ai` 5, 6 and 7 (and `zod` 3 and 4); CI runs all of them.
Node 20 or newer is required (`@vaquill-ai/sdk` needs 20).
`ai` 7 itself requires Node 22 or newer, so use 22+ with it.
`ai` 5.0.0 to 5.0.14 are not supported (agents and invalid-argument handling are unreliable there).
Get an API key from the Vaquill dashboard and set it:

```bash
export VAQUILL_API_KEY=vq_key_...
```

## generateText

```ts
import { generateText, isStepCount } from "ai";
import { createVaquillTools } from "@vaquill-ai/ai-sdk";

const { text } = await generateText({
  model: "anthropic/claude-sonnet-4.5",
  tools: createVaquillTools({ maxCredits: 50 }),
  stopWhen: isStepCount(6),
  prompt: "What is the statute of limitations for medical malpractice in Texas? Cite the section.",
});
```

## streamText

```ts
import { streamText, isStepCount } from "ai";
import { createVaquillTools } from "@vaquill-ai/ai-sdk";

const result = streamText({
  model: "anthropic/claude-sonnet-4.5",
  tools: createVaquillTools({ maxCredits: 50 }),
  stopWhen: isStepCount(6),
  prompt: "Does 12 CFR 1026.3 still say what it said in 2020?",
});

for await (const chunk of result.textStream) process.stdout.write(chunk);
```

## Agent loop

```ts
import { ToolLoopAgent, isStepCount } from "ai";
import { createVaquillTools } from "@vaquill-ai/ai-sdk";

const researcher = new ToolLoopAgent({
  model: "anthropic/claude-sonnet-4.5",
  instructions:
    "You are a legal research assistant. Verify every citation with resolveCitation before relying on it. " +
    "Quote statute text only from getStatuteSectionText. Never cite a section you did not retrieve. " +
    "If a tool returns spend_limit, stop and answer from what you have.",
  tools: createVaquillTools({
    maxCredits: 100,
    // Read tools only; leave out the expensive ones if you do not need them.
    exclude: ["extractCitations", "listDivisions"],
  }),
  stopWhen: isStepCount(10),
});

const { text } = await researcher.generate({
  prompt: "Compare how California and New York define 'trade secret'.",
});
```

## Next.js route handler

```ts
// app/api/research/route.ts
import { convertToModelMessages, isStepCount, streamText, type UIMessage } from "ai";
import { createVaquillTools } from "@vaquill-ai/ai-sdk";

export const maxDuration = 60;

export async function POST(req: Request) {
  const { messages }: { messages: UIMessage[] } = await req.json();

  // Build the tools per request so each request gets its own spend cap.
  const tools = createVaquillTools({ maxCredits: 25 });

  const result = streamText({
    model: "anthropic/claude-sonnet-4.5",
    system: "You are a US legal research assistant. Verify citations before relying on them.",
    messages: await convertToModelMessages(messages),
    tools,
    stopWhen: isStepCount(8),
  });
  return result.toUIMessageStreamResponse();
}
```

The key stays on the server (`VAQUILL_API_KEY` in your environment).
Never ship a `vq_key_` key to a browser.

## Tools

| Tool | What it does | Cost |
| --- | --- | --- |
| `searchStatutes` | Search statutes, regulations, constitutions, court rules. Accepts topics or citations. | credits |
| `getStatuteSection` | Metadata of one section by `actId`. | credits |
| `getStatuteSectionText` | Full text of one section (plain, markdown or operative), optional subsection and as-of date. | credits |
| `resolveCitation` | One citation to its section. | credits |
| `resolveCitations` | Up to 100 citations in one call. | credits per citation |
| `extractCitations` | Find citations in a block of text and resolve them. | credits per distinct citation |
| `countSections` | Count sections matching a filter. | credits |
| `listDivisions` | Browse titles, chapters, parts. | credits per page |
| `sectionChanges` | Amendment history of a section. | credits per page |
| `citedBy` | Sections that cite this one. | credits |
| `definitions` | Defined terms that apply to a section. | credits |
| `neighbors` | Sections before and after this one. | credits |
| `searchSessionLaws` | Search acts as enacted. | credits per page |
| `getSessionLaw` | Metadata of one session law. | credits |
| `creditBalance` | Remaining credits. | free |

With `allowWrites: true` five more appear: `listWatches`, `createWatch`, `updateWatch`, `deleteWatch`, `testWatch` (law-change alerts).
`createWatch` makes Vaquill email or POST to an address the model chooses, so enable writes only for agents you trust with that, and consider a human approval step.
`testWatch` sends a real test event to the watch's webhook or email, so it is write-gated like the others.
Bulk fetches and full session law text are deliberately not exposed; see `UNMAPPED_OPERATIONS` for each reason.

## Options

```ts
import { Vaquill } from "@vaquill-ai/sdk";
import { createVaquillTools } from "@vaquill-ai/ai-sdk";

createVaquillTools({
  apiKey: process.env.VAQUILL_API_KEY, // default: process.env.VAQUILL_API_KEY
  client: new Vaquill(), // your own configured Vaquill client (base URL, retries, fetch)
  maxCredits: 100, // hard spend cap, default 200, Infinity to disable
  include: ["searchStatutes", "resolveCitation"], // only these tool names
  exclude: ["extractCitations"], // everything except these (applied after include)
  allowWrites: false, // expose the watch tools, default false
  maxResultChars: 60_000, // replace results larger than this with a preview, default 60000
  redact: ["internal-secret"], // extra strings to scrub from error messages
});
```

`vaquillTools()` is the same with defaults and reads `VAQUILL_API_KEY` when called.

With `client`, the cap is applied to a derived client that shares your client's spend counter, so credits you already spent on it count.
While a cap is set, paid calls run one at a time, so parallel tool calls cannot overshoot it.

Each tool is also exported as a factory for tree-shaking:

```ts
import { Vaquill } from "@vaquill-ai/sdk";
import { searchStatutesTool, getStatuteSectionTextTool } from "@vaquill-ai/ai-sdk";

const client = new Vaquill({ maxCredits: 30 });
const tools = {
  searchStatutes: searchStatutesTool(client),
  getStatuteSectionText: getStatuteSectionTextTool(client),
};
```

## Results and errors

A tool never throws for an API problem.
Success returns `{ ok: true, data, creditsSpentSoFar }`.
A failure returns a structured result the model can act on:

```json
{
  "ok": false,
  "error": {
    "kind": "not_found",
    "message": "...",
    "retryable": false,
    "hint": "Nothing exists at that identifier. Find the right actId ...",
    "status": 404,
    "requestId": "req_..."
  }
}
```

`kind` is one of `spend_limit`, `insufficient_credits`, `authentication`, `permission_denied`, `not_found`, `invalid_request`, `rate_limited`, `daily_cap`, `server_error`, `timeout`, `connection`, `bad_response`, `error` or `unexpected`.
Results carry no stack traces, and anything shaped like an API key is replaced with `[redacted]`.
Only an abort (the AI SDK's `abortSignal`) is rethrown, so cancelling a request stops the loop.

A result larger than `maxResultChars` is replaced by `{ ok: true, truncated: true, preview, note }` so one long section cannot fill the context window.
Credits are still spent for it; ask for a `pinpoint` subsection or a narrower search.

## Development

```bash
npm install
npm run lint && npm run typecheck && npm test   # fake local server, no network
npm run build && npm run lint:package
VAQUILL_LIVE=1 VAQUILL_API_KEY=... npm run test:live   # optional, at most 5 credits
```

A drift test fails when `openapi/vaquill-us.json` gains an operation that is neither a tool nor listed with a reason in `UNMAPPED_OPERATIONS`.

## Licence

MIT
