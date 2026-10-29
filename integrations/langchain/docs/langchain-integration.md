---
title: "Vaquill integration"
description: "Integrate US primary law (statutes, regulations, court rules, constitutions) into LangChain agents and RAG with the langchain-vaquill package."
---

[Vaquill](https://www.vaquill.ai) is a data API for US primary law.
The `langchain-vaquill` package provides LangChain tools, a toolkit and a retriever on top of the [`vaquill`](https://pypi.org/project/vaquill/) Python SDK.

<Warning>
Almost every Vaquill call spends credits (a search is 4, a section's text is 6, a citation resolve is 2).
Set `max_credits` on the toolkit and the retriever, which is a hard cap, before you hand them to an agent.
</Warning>

## Overview

### Integration details

| Class | Package | Serializable | Python support | Downloads | Version |
| :--- | :--- | :---: | :---: | :---: | :---: |
| `VaquillToolkit` | `langchain-vaquill` | no | 3.11+ | ![PyPI - Downloads](https://img.shields.io/pypi/dm/langchain-vaquill?style=flat-square&label=%20) | ![PyPI - Version](https://img.shields.io/pypi/v/langchain-vaquill?style=flat-square&label=%20) |
| `VaquillRetriever` | `langchain-vaquill` | no | 3.11+ | ![PyPI - Downloads](https://img.shields.io/pypi/dm/langchain-vaquill?style=flat-square&label=%20) | ![PyPI - Version](https://img.shields.io/pypi/v/langchain-vaquill?style=flat-square&label=%20) |

### Tool features

| Native async | Returns artifact | Pricing |
| :---: | :---: | :---: |
| yes | no | Credits per call, stated in each tool description |

### Retriever features

| Self-host | Cloud offering | Package |
| :---: | :---: | :---: |
| no | yes | `langchain-vaquill` |

## Setup

```bash
pip install -U langchain-vaquill
```

Create an API key at [vaquill.ai](https://www.vaquill.ai) and set it:

```python
import getpass
import os

if not os.environ.get("VAQUILL_API_KEY"):
    os.environ["VAQUILL_API_KEY"] = getpass.getpass("Vaquill API key: ")
```

## Tools

### Instantiation

`VaquillToolkit` returns read-only tools by default.

```python
from langchain_vaquill import VaquillToolkit

toolkit = VaquillToolkit(max_credits=100)
tools = toolkit.get_tools()
[tool.name for tool in tools]
```

```text
['vaquill_search_statutes', 'vaquill_get_statute_section', 'vaquill_get_statute_text', ...]
```

| Tool | Returns | Credits |
| :--- | :--- | :--- |
| `vaquill_search_statutes` | Ranked sections with excerpt, status, source link, dates | 4 (+6 per row with `include_body`) |
| `vaquill_get_statute_section` | One section's metadata, no text | 2 |
| `vaquill_get_statute_text` | One section's text, optional pinpoint and as-of date | 6 |
| `vaquill_resolve_citation`, `vaquill_resolve_citations` | The section a citation names | 2 per citation |
| `vaquill_extract_citations` | Citations found in a text | free, or 2 per distinct citation with `resolve=true` |
| `vaquill_count_sections` | Number of sections in a scope | 1 |
| `vaquill_list_divisions` | One level of a code's hierarchy | 1 |
| `vaquill_section_changes` | Observed amendments to a section | 1 |
| `vaquill_section_cited_by` | Sections that cite a section | 2 |
| `vaquill_section_definitions` | Terms a section defines or uses | 4 |
| `vaquill_section_neighbors` | Neighbouring and related sections | 2 |
| `vaquill_section_cross_state` | Comparable sections in other states | 6 |
| `vaquill_search_session_laws`, `vaquill_get_session_law`, `vaquill_get_session_law_text` | Acts as enacted | 4, 2, 6 per page |
| `vaquill_credit_balance`, `vaquill_get_pricing`, `vaquill_statutes_coverage` | Account and reference data | free |

The watch tools (`vaquill_create_watch`, `vaquill_update_watch`, `vaquill_delete_watch`) change the account and are returned only with `VaquillToolkit(include_watch_tools=True)`.
Pick tools with `tools=[...]`, or only never-charged ones with `free_only=True`.

### Invocation

```python
tool = {t.name: t for t in tools}["vaquill_resolve_citation"]
tool.invoke({"cite": "42 U.S.C. 1983"})
```

### Use within an agent

```python
from langchain_openai import ChatOpenAI
from langchain.agents import create_agent

agent = create_agent(ChatOpenAI(model="gpt-4o"), tools)
result = agent.invoke(
    {"messages": [("user", "Is California Penal Code 187 in force, and what does it say?")]}
)
print(result["messages"][-1].content)
print("credits spent:", toolkit.credits_spent)
```

Errors reach the model as short instructions (stop on a bad key or no credits, wait on a rate limit, resolve the citation first on a 404), never as stack traces.

## Retriever

### Instantiation

```python
from langchain_vaquill import VaquillRetriever

retriever = VaquillRetriever(
    k=3,
    filters={"state": "ca", "corpus_type": ["STATE"], "exclude_repealed": True},
    max_credits=30,
)
```

| Argument | Meaning |
| :--- | :--- |
| `k` | Documents per query, 1 to 50 |
| `filters` | Search filters (snake_case names of the SDK's `statutes.search`) |
| `include_body` | `True` (default): `page_content` is the section text, about 6 extra credits per row. `False`: the excerpt |
| `max_credits` | Hard cap (default 50). A call that could exceed it is refused before it is sent |

### Usage

```python
docs = retriever.invoke("homicide with malice aforethought")
docs[0].page_content
docs[0].metadata
```

```text
{'id': '<actId>', 'citation': 'Cal. Penal Code § 187', 'jurisdiction': 'ca',
 'sourceUrl': 'https://...', 'effectiveDate': '...', 'lastAmendedDate': '...'}
```

### Use within a chain

```python
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnablePassthrough
from langchain_openai import ChatOpenAI

prompt = ChatPromptTemplate.from_template(
    "Answer from the statutes below and cite them.\n\n{context}\n\nQuestion: {question}"
)


def format_docs(docs):
    return "\n\n".join(f"{d.metadata['citation']}\n{d.page_content}" for d in docs)


chain = (
    {"context": retriever | format_docs, "question": RunnablePassthrough()}
    | prompt
    | ChatOpenAI(model="gpt-4o")
    | StrOutputParser()
)
chain.invoke("What is the penalty for murder in California?")
```

## Configuration

* `api_key` or `VAQUILL_API_KEY`. A missing key fails at construction.
* `client=` and `async_client=` reuse your own `vaquill.Vaquill` and `vaquill.AsyncVaquill`.
* Requests carry the User-Agent `vaquill-python/<sdk> ... langchain-vaquill/<version>`.

## API reference

For the REST API see the [Vaquill documentation](https://www.vaquill.ai/docs/api-guide/sdks/overview).
Source: [`integrations/langchain`](https://github.com/Vaquill-AI/vaquill-sdks/tree/main/integrations/langchain).
