# llama-index-tools-vaquill

LlamaIndex tools and a retriever for the [Vaquill](https://www.vaquill.ai) US primary-law Data API.
Search and read statutes, regulations, court rules, constitutions and session laws from a LlamaIndex agent or RAG pipeline.
Built on the published [`vaquill`](https://pypi.org/project/vaquill/) Python SDK.

This one distribution ships two import paths:

- `llama_index.tools.vaquill`: `VaquillToolSpec`, for agents.
- `llama_index.retrievers.vaquill`: `VaquillRetriever`, for query engines and pipelines.

Requires Python 3.11 or newer, because the `vaquill` SDK does.

## Install

```bash
pip install llama-index-tools-vaquill
export VAQUILL_API_KEY="vq_key_..."
```

Get a key at <https://www.vaquill.ai>.

## Cost warning

Almost every Vaquill call spends credits, and an agent will call tools in a loop.
Typical prices: search 4, section metadata 2, section text 6, citation resolve 2, definitions 4, count 1.
`get_credit_balance` and `extract_citations` with `resolve=False` are free.
Read the live prices with `client.pricing.get()` (free) before a large job.
Always set `max_credits` when you hand tools to an agent or a retriever to a pipeline.
It is a hard cap shared by the sync and async paths: once it is reached no further request is sent.
One call that is already in flight can still finish, so choose a cap with some headroom.

## Agent example

```python
import asyncio

from llama_index.core.agent.workflow import FunctionAgent
from llama_index.llms.openai import OpenAI
from llama_index.tools.vaquill import VaquillToolSpec

tool_spec = VaquillToolSpec(max_credits=50)  # key from VAQUILL_API_KEY

agent = FunctionAgent(
    tools=tool_spec.to_tool_list(),
    llm=OpenAI(model="gpt-4.1"),
    system_prompt=(
        "You are a legal research assistant. Find the section with search_statutes or "
        "resolve_citation, then read it with get_section(include_body=true). "
        "Quote the citation and sourceUrl. Each call costs credits, so avoid repeats."
    ),
)


async def main() -> None:
    answer = await agent.run("What does 42 U.S.C. 1983 provide? Quote the first sentence.")
    print(answer)
    print("credits spent:", tool_spec.credits_spent)


asyncio.run(main())
```

### Tools

| Tool | What it returns | Credits |
| --- | --- | --- |
| `search_statutes` | Ranked sections with excerpts (or full text with `include_body`) | 4 per call, plus text price per row with `include_body` |
| `get_section` | Section metadata, or the text with `include_body=True` | 2, or 6 with text |
| `resolve_citation` | A citation resolved to its section | 2 |
| `resolve_citations` | Many citations resolved | 2 each |
| `extract_citations` | Citations found in a passage | 0 (2 each distinct one with `resolve=True`) |
| `count_sections` | A count for a scope or query | 1 |
| `list_divisions` | One level of a code's hierarchy | 1 |
| `get_section_changes` | Observed amendments to a section | 1 |
| `get_cited_by` | Sections that cite a section | 2 |
| `get_definitions` | Terms a section defines or uses | 4 |
| `get_neighbors` | Related sections | 2 |
| `search_session_laws` | Session laws by topic or wording | 4 |
| `get_session_law` | One session law's record | 2 |
| `get_credit_balance` | Credits left, plan, rate limit | free |

Each tool has an `_async` twin (`search_statutes_async`, and so on).
`to_tool_list()` wires both into one `FunctionTool`, so async agents use the async client.
Prices come from the SDK documentation and can change; the per-call figure on a response is `creditsConsumed`.

### Read-only by default

`create_watch`, `update_watch` and `delete_watch` (law-change alerts) are not exposed unless you opt in:

```python
tool_spec = VaquillToolSpec(enable_watch_management=True)
```

Operations that are not tools (batch fetches, rulemaking, session-law bodies, watch reads and so on) are listed with a reason in `llama_index/tools/vaquill/_operations.py`.
A test fails when the OpenAPI contract gains an operation that is neither exposed nor listed there.

### Errors

By default a failure comes back as a short string the model can act on, for example `Vaquill error: Out of credits (402). ...`.
There are no stack traces and the API key is scrubbed from every message.
Set `raise_on_error=True` to raise `VaquillToolError` instead.

### Configuration

```python
VaquillToolSpec(
    api_key=None,  # or env VAQUILL_API_KEY
    client=None,  # a pre-built vaquill.Vaquill
    async_client=None,  # a pre-built vaquill.AsyncVaquill
    base_url=None,  # or env VAQUILL_BASE_URL
    max_credits=None,  # hard spend cap
    max_chars=12000,  # longest text field handed to the model
    timeout=None,
    max_retries=None,
    user_agent_suffix=None,  # appended to the integration User-Agent
)
```

Clients built here send `User-Agent: vaquill-python/<v> python/<v> <os> llama-index-tools-vaquill/<v> [suffix]`.
A pre-built client keeps its own User-Agent.
If you pass only a sync `client`, async calls run on it in a worker thread.

## Retriever example

```python
from llama_index.core.query_engine import RetrieverQueryEngine
from llama_index.retrievers.vaquill import VaquillRetriever

retriever = VaquillRetriever(
    similarity_top_k=5,
    filters={"state": "ca", "corpus_type": "STATE"},
    max_credits=40,
)

for hit in retriever.retrieve("elements of first degree murder"):
    print(hit.score, hit.node.metadata["citation"], hit.node.metadata["sourceUrl"])
    print(hit.node.get_content()[:200])

query_engine = RetrieverQueryEngine.from_args(retriever)  # uses your configured LLM
```

Each hit is a `NodeWithScore` holding a `TextNode`.
The text is the section text (the excerpt when the body is not held or `include_body=False`).
Metadata has `citation`, `jurisdiction`, `id`, `sourceUrl`, `effectiveDate`, `lastAmendedDate`, `currentThrough`, `expirationDate`, `corpusType`, `actStatus` and `sectionTitle` when present.
`aretrieve` is supported natively.

- **Cost:** each retrieval is one search: 4 credits, plus the text price per row when `include_body=True` (the default).
  Set `include_body=False` for excerpts at 4 credits.
- **`max_credits`:** before each request the retriever adds the worst-case cost of that retrieval (4 plus 6 per row when text is on) to what it has spent, and raises `vaquill.SpendGuardExceeded` without sending anything if the total would pass the cap.
  The worst case uses documented prices, so it is conservative.
- **Filters:** a dict or `MetadataFilters` (`EQ` and `IN`, flat). Keys: `state`, `corpus_type`, `act_status`, `agency`, `article`, `changed_since`, `chapter`, `code`, `document_type`, `exclude_repealed`, `match_type`, `part`, `published_from`, `published_to`, `source`, `title_number`, `year_from`, `year_to`. camelCase works too.
- **Errors:** API failures raise `VaquillToolError` with the same scrubbed message the tools use.

## Development

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
make lint
make test      # offline: a local fake HTTP server, coverage must stay above 85 percent
make live      # optional: needs VAQUILL_API_KEY, spends at most 5 credits
```

The offline suite never makes a network call beyond 127.0.0.1 and ignores any `VAQUILL_API_KEY` in your shell.
The drift test reads `../../openapi/vaquill-us.json`, so run the suite from a checkout of the full `vaquill-sdks` repository.

## Licence

MIT. See `LICENSE`.
