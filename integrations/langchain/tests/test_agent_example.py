"""The README agent example, run offline against a scripted fake chat model.

It uses ``langchain.agents.create_agent``, the current LangChain agent API (the old
``langgraph.prebuilt.create_react_agent`` is deprecated). The fake server stands in for Vaquill, so
no key and no credits are involved.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

import pytest
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import BaseTool

from langchain_vaquill import VaquillToolkit

pytest.importorskip("langchain.agents", reason="needs langchain>=1.0 (the 'agents' extra)")
from langchain.agents import create_agent


class ScriptedChatModel(BaseChatModel):
    """Replays AIMessages in order; ``bind_tools`` is a no-op so ``create_agent`` accepts it."""

    script: list[AIMessage]
    cursor: int = 0

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def bind_tools(  # type: ignore[override]
        self, tools: Sequence[dict[str, Any] | type | Callable | BaseTool], **kwargs: Any
    ) -> ScriptedChatModel:
        return self

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        message = self.script[min(self.cursor, len(self.script) - 1)]
        self.cursor += 1
        return ChatResult(generations=[ChatGeneration(message=message)])


def test_readme_agent_example_runs_offline(provider_kwargs: dict[str, Any]) -> None:
    toolkit = VaquillToolkit(**provider_kwargs, max_credits=100)
    model = ScriptedChatModel(
        script=[
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "vaquill_resolve_citation",
                        "args": {"cite": "42 U.S.C. 1983"},
                        "id": "call_1",
                        "type": "tool_call",
                    }
                ],
            ),
            AIMessage(content="42 U.S.C. 1983 resolves to a federal statute."),
        ]
    )
    agent = create_agent(model, toolkit.get_tools())

    result = agent.invoke(
        {"messages": [("user", "Is 42 U.S.C. 1983 in force, and what does it say?")]}
    )

    messages = result["messages"]
    assert messages[-1].content == "42 U.S.C. 1983 resolves to a federal statute."
    tool_messages = [m for m in messages if isinstance(m, ToolMessage)]
    assert len(tool_messages) == 1
    assert tool_messages[0].name == "vaquill_resolve_citation"
    assert tool_messages[0].status != "error"
    assert "1983" in str(tool_messages[0].content)
    assert toolkit.credits_spent >= 0
