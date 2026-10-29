# langchain-vaquill

LangChain and LangGraph tools, a toolkit and a retriever for the [Vaquill](https://www.vaquill.ai) US primary law Data API.
Built on the published [`vaquill`](https://pypi.org/project/vaquill/) Python SDK.

It gives an agent search, citation resolution, section text, amendment history, cited-by, definitions and session laws over US federal and state statutes, regulations, court rules and constitutions.

## Install

```bash
pip install langchain-vaquill
export VAQUILL_API_KEY="vq_key_..."
```

Python 3.11 or newer (the `vaquill` SDK requires it).
For the agent example also `pip install "langchain-vaquill[agents]" langchain-openai` (`langchain` 1.0 or newer, which provides `create_agent`).

## Cost warning

Almost every Vaquill call spends credits.
A search costs 4 credits, a section's text 6, a citation resolve 2, definitions 4.
An agent in a loop can spend a lot without anyone noticing, so:

* Set `max_credits` on the toolkit and the retriever. It is a hard cap: once reached, paid tools return a message telling the model to stop.
* Use `free_only=True` to expose only tools that never spend (`vaquill_credit_balance`, `vaquill_get_pricing`, `vaquill_statutes_coverage`, `vaquill_list_boards`, `vaquill_list_watches`, `vaquill_extract_citations` with its default `resolve=false`).
* Every tool description states what it costs, so the model can plan. `vaquill_get_pricing` returns the live prices.

## Agent

```python
from langchain_openai import ChatOpenAI
from langchain.agents import create_agent

from langchain_vaquill import VaquillToolkit

toolkit = VaquillToolkit(max_credits=100)  # reads VAQUILL_API_KEY
agent = create_agent(ChatOpenAI(model="gpt-4o"), toolkit.get_tools())

result = agent.invoke(
    {"messages": [("user", "Is California Penal Code 187 in force, and what does it say?")]}
)
print(result["messages"][-1].content)
print("credits spent:", toolkit.credits_spent)
```

`create_agent` replaces the deprecated `langgraph.prebuilt.create_react_agent`.
It returns a LangGraph graph, so checkpointers and streaming work as before.
This exact example runs offline against a scripted chat model in `tests/test_agent_example.py`.

### Tool selection

```python
VaquillToolkit(tools=["vaquill_search_statutes", "vaquill_get_statute_text"])
VaquillToolkit(free_only=True)
VaquillToolkit.available_tool_names()
```

The default is read-only.
The watch tools (`vaquill_create_watch`, `vaquill_update_watch`, `vaquill_delete_watch`) change the account and exist only with `include_watch_tools=True`.

## Retriever

```python
from langchain_vaquill import VaquillRetriever

retriever = VaquillRetriever(
    k=3,
    filters={"state": "ca", "corpus_type": ["STATE"], "exclude_repealed": True},
    max_credits=30,
)
docs = retriever.invoke("homicide with malice aforethought")
docs[0].page_content  # section text
docs[0].metadata[
    "citation"
]  # also: id, jurisdiction, sourceUrl, effectiveDate, lastAmendedDate, currentThrough
```

`include_body=True` (the default) returns section text and costs about 4 + 6 per row.
`include_body=False` returns the excerpt for the search price only.
A call that could push the total past `max_credits` is refused before any request is sent (`vaquill.SpendGuardExceeded`).

## Configuration

* `api_key=` or the `VAQUILL_API_KEY` environment variable. A missing key fails at construction.
* `client=` / `async_client=` reuse an existing `vaquill.Vaquill` / `vaquill.AsyncVaquill`. With a sync client only, async calls run it in a worker thread.
* Requests carry the User-Agent `vaquill-python/<sdk> ... langchain-vaquill/<version>`, set through the SDK's `default_headers` option.

## Errors

Tools never raise SDK exceptions or stack traces at the model.
They raise `ToolException` with an instruction: out of credits (stop), bad key (stop), rate limited (wait, retry once), not found (resolve the citation first), bad arguments (fix and call again), spend cap reached (answer with what you have).
Anything shaped like an API key or bearer token is removed from messages.

## Tests

```bash
pip install -e ".[dev]"
pytest
```

The default suite points the SDK at a local fake HTTP server and makes no live calls.
One optional live smoke test (at most 5 credits) runs with `VAQUILL_API_KEY=... pytest -m live`.

## Licence

MIT.
