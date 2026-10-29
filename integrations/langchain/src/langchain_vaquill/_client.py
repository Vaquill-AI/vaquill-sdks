"""Client configuration shared by the tools, the toolkit and the retriever."""

from __future__ import annotations

import asyncio
import os
import platform
from collections.abc import Awaitable, Callable, Mapping
from typing import Any, TypeVar

import vaquill
from vaquill import AsyncVaquill, Vaquill, VaquillError

from ._version import __version__

__all__ = ["ClientProvider", "integration_user_agent"]

T = TypeVar("T")

API_KEY_ENV = "VAQUILL_API_KEY"


def integration_user_agent() -> str:
    """The SDK's own User-Agent with this integration appended."""
    py, os_name = platform.python_version(), platform.system().lower()
    return f"vaquill-python/{vaquill.__version__} python/{py} {os_name} langchain-vaquill/{__version__}"


class ClientProvider:
    """Owns (or wraps) the Vaquill SDK clients used by one toolkit or retriever.

    * ``api_key`` defaults to the ``VAQUILL_API_KEY`` environment variable.
    * A passed ``client`` (and optional ``async_client``) is reused. We derive a copy with the
      integration User-Agent through the SDK's ``with_options`` (the copy shares the HTTP client
      and the spend total with yours), and the original is never closed by us.
    * With a sync client only, async calls run that client in a worker thread.
    * ``max_credits`` is the SDK spend guard: charged calls raise ``SpendGuardExceeded`` once
      the credits consumed through the client reach the cap.
    """

    def __init__(
        self,
        *,
        api_key: str | None = None,
        client: Vaquill | None = None,
        async_client: AsyncVaquill | None = None,
        base_url: str | None = None,
        max_credits: float | None = None,
        timeout: float | None = None,
        max_retries: int | None = None,
        default_headers: Mapping[str, str] | None = None,
    ) -> None:
        if api_key is not None and not isinstance(api_key, str):
            raise TypeError("api_key must be a string.")
        self._api_key = api_key
        self._base_url = base_url
        self._timeout = timeout
        self._max_retries = max_retries
        self._max_credits = max_credits
        self._headers = {**(default_headers or {}), "User-Agent": integration_user_agent()}
        self._owned: list[Any] = []
        # Fail at construction, not on the first model call.
        no_key = not (api_key or os.environ.get(API_KEY_ENV))
        if client is None and async_client is None and no_key:
            raise ValueError(
                f"No Vaquill API key. Pass api_key=... or set the {API_KEY_ENV} variable, "
                "or pass an existing vaquill.Vaquill client."
            )
        self._sync = self._adopt(client) if client is not None else None
        self._async = self._adopt(async_client) if async_client is not None else None
        self._client_given = client is not None or async_client is not None

    def __repr__(self) -> str:
        return f"ClientProvider(base_url={self._base_url!r}, max_credits={self._max_credits!r})"

    def _adopt(self, client: Any) -> Any:
        merged = {**getattr(client, "default_headers", {}), **self._headers}
        merged = {k: v for k, v in merged.items() if k.lower() != "user-agent"}
        merged["User-Agent"] = self._headers["User-Agent"]
        kwargs: dict[str, Any] = {"default_headers": merged}
        if self._max_credits is not None:
            kwargs["max_credits"] = self._max_credits
        return client.with_options(**kwargs)

    def _build_kwargs(self) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "api_key": self._api_key,
            "base_url": self._base_url,
            "default_headers": self._headers,
            "max_credits": self._max_credits,
        }
        if self._timeout is not None:
            kwargs["timeout"] = self._timeout
        if self._max_retries is not None:
            kwargs["max_retries"] = self._max_retries
        return kwargs

    @property
    def sync_client(self) -> Vaquill:
        if self._sync is None:
            if self._client_given:
                raise ValueError(
                    "Only an AsyncVaquill client was supplied; use the async interface "
                    "(ainvoke / aget_relevant_documents) or also pass a sync Vaquill client."
                )
            self._sync = Vaquill(**self._build_kwargs())
            self._owned.append(self._sync)
        return self._sync  # type: ignore[no-any-return]

    @property
    def async_client(self) -> AsyncVaquill | None:
        """The async client, or None when only a sync client was supplied."""
        if self._async is None and not self._client_given:
            self._async = AsyncVaquill(**self._build_kwargs())
            self._owned.append(self._async)
        return self._async  # type: ignore[no-any-return]

    @property
    def credits_spent(self) -> float:
        """Credits consumed through this provider's clients (the SDK's own running total)."""
        for client in (self._sync, self._async):
            if client is not None:
                return float(client.credits_spent)
        return 0.0

    async def acall(self, fn: Callable[[Any], Any]) -> Any:
        """Run ``fn(client)`` on the async client, or ``fn(sync_client)`` in a thread."""
        aclient = self.async_client
        if aclient is not None:
            result: Awaitable[Any] = fn(aclient)
            return await result
        return await asyncio.to_thread(fn, self.sync_client)

    def close(self) -> None:
        for client in self._owned:
            if isinstance(client, Vaquill):
                client.close()

    async def aclose(self) -> None:
        for client in self._owned:
            if isinstance(client, AsyncVaquill):
                await client.aclose()
            elif isinstance(client, Vaquill):
                client.close()


# Re-exported for convenience in error handling.
VaquillError = VaquillError
