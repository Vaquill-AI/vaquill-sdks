"""``VaquillToolkit``: the Vaquill tools, ready for an agent."""

from __future__ import annotations

from typing import Any

from langchain_core.tools import BaseTool, BaseToolkit
from pydantic import ConfigDict, Field, SecretStr
from vaquill import AsyncVaquill, Vaquill

from ._client import ClientProvider
from .tools import READ_ONLY_TOOLS, WATCH_WRITE_TOOLS, VaquillTool, all_tool_classes, tool_name

__all__ = ["VaquillToolkit"]


class VaquillToolkit(BaseToolkit):
    """Vaquill US primary-law tools for LangChain and LangGraph agents.

    By default the toolkit returns the read-only tools. Most of them spend credits (see each
    tool's description); set ``max_credits`` to cap what one toolkit can spend. The watch
    create, update and delete tools exist only with ``include_watch_tools=True``.

    Args:
        api_key: ``vq_key_...``. Defaults to the ``VAQUILL_API_KEY`` environment variable.
        client: An existing :class:`vaquill.Vaquill` to reuse instead of building one.
        async_client: An existing :class:`vaquill.AsyncVaquill`. Without it, async calls run the
            sync client in a worker thread.
        base_url: Override the API origin (tests, proxies).
        max_credits: Spend cap in credits for this toolkit. Paid calls raise a ToolException
            telling the model to stop once the cap is reached.
        include_watch_tools: Also offer create, update and delete watch tools. Off by default.
        tools: Names of the tools to return (see :meth:`available_tool_names`). Default: all
            read-only tools, plus the watch tools when ``include_watch_tools`` is true.
        free_only: Return only tools that never spend credits.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    api_key: SecretStr | None = Field(default=None, repr=False)
    client: Vaquill | None = Field(default=None, exclude=True)
    async_client: AsyncVaquill | None = Field(default=None, exclude=True)
    base_url: str | None = None
    max_credits: float | None = Field(default=None, gt=0)
    include_watch_tools: bool = False
    tools: list[str] | None = None
    free_only: bool = False
    timeout: float | None = None
    max_retries: int | None = None

    _provider: ClientProvider | None = None

    def model_post_init(self, __context: Any) -> None:
        self._provider = ClientProvider(
            api_key=self.api_key.get_secret_value() if self.api_key else None,
            client=self.client,
            async_client=self.async_client,
            base_url=self.base_url,
            max_credits=self.max_credits,
            timeout=self.timeout,
            max_retries=self.max_retries,
        )
        self._selection()  # validate eagerly so a typo fails at construction

    @property
    def provider(self) -> ClientProvider:
        assert self._provider is not None
        return self._provider

    @property
    def credits_spent(self) -> float:
        """Credits consumed through this toolkit's clients so far."""
        return self.provider.credits_spent

    @staticmethod
    def available_tool_names(*, include_watch_tools: bool = True) -> list[str]:
        classes = all_tool_classes() if include_watch_tools else READ_ONLY_TOOLS
        return [tool_name(c) for c in classes]

    def _selection(self) -> list[type[VaquillTool]]:
        by_name = {tool_name(c): c for c in all_tool_classes()}
        if self.tools is not None:
            unknown = [n for n in self.tools if n not in by_name]
            if unknown:
                raise ValueError(
                    f"Unknown Vaquill tool name(s): {', '.join(unknown)}. "
                    f"Valid names: {', '.join(by_name)}."
                )
            chosen = [by_name[n] for n in dict.fromkeys(self.tools)]
            blocked = [tool_name(c) for c in chosen if c.mutating and not self.include_watch_tools]
            if blocked:
                raise ValueError(
                    f"{', '.join(blocked)} change the account; set include_watch_tools=True "
                    "to allow them."
                )
        else:
            chosen = list(READ_ONLY_TOOLS)
            if self.include_watch_tools:
                chosen += list(WATCH_WRITE_TOOLS)
        if self.free_only:
            chosen = [c for c in chosen if not c.charged]
        return chosen

    def get_tools(self) -> list[BaseTool]:
        return [cls(provider=self.provider) for cls in self._selection()]  # pyright: ignore[reportCallIssue, reportReturnType]

    def close(self) -> None:
        self.provider.close()

    async def aclose(self) -> None:
        await self.provider.aclose()
