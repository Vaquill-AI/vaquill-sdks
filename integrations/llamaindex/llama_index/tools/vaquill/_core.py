"""Client construction, the shared spend guard and the sync/async call plumbing."""

import asyncio
import os
import platform
from typing import Any, Awaitable, Callable, Dict, List, Optional, TypeVar, cast

import vaquill
from llama_index.tools.vaquill._version import __version__
from vaquill import AsyncVaquill, SpendGuardExceeded, Vaquill

__all__ = ["INTEGRATION_NAME", "VaquillConnection", "integration_user_agent"]

INTEGRATION_NAME = "llama-index-tools-vaquill"
API_KEY_ENV = "VAQUILL_API_KEY"

T = TypeVar("T")


def integration_user_agent(suffix: Optional[str] = None) -> str:
    """The SDK's own User-Agent plus this integration, and an optional caller suffix.

    The SDK sends ``vaquill-python/<v> python/<v> <os>`` and lets ``default_headers`` replace the
    ``user-agent`` header (Authorization and Idempotency-Key stay protected), so this is the
    supported way to add an integration token.
    """
    base = f"vaquill-python/{vaquill.__version__} python/{platform.python_version()} {platform.system().lower()}"
    agent = f"{base} {INTEGRATION_NAME}/{__version__}"
    if suffix:
        agent = f"{agent} {' '.join(suffix.split())}"
    return agent


class VaquillConnection:
    """One place that owns the SDK clients for a tool spec or a retriever.

    Args:
        api_key: A ``vq_key_...`` key. Defaults to the ``VAQUILL_API_KEY`` environment variable.
        client: A pre-built :class:`vaquill.Vaquill`. Used as is (its User-Agent is not changed).
        async_client: A pre-built :class:`vaquill.AsyncVaquill`. When omitted, async calls use
            ``client`` in a worker thread if one was given, otherwise a client built from the key.
        base_url: Overrides ``VAQUILL_BASE_URL`` and the default ``https://api.vaquill.ai``.
        max_credits: Hard cap on credits spent through this connection, across the sync and the
            async client together. Defaults to the pre-built client's own cap, if any.
        timeout: Seconds or an ``httpx.Timeout`` for clients built here.
        max_retries: Retries for clients built here.
        user_agent_suffix: Extra token appended to the integration User-Agent.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        *,
        client: Optional[Vaquill] = None,
        async_client: Optional[AsyncVaquill] = None,
        base_url: Optional[str] = None,
        max_credits: Optional[float] = None,
        timeout: Optional[float] = None,
        max_retries: Optional[int] = None,
        user_agent_suffix: Optional[str] = None,
    ) -> None:
        self._sync: Optional[Vaquill] = client
        self._async: Optional[AsyncVaquill] = async_client
        self._sync_is_prebuilt = client is not None
        self._api_key = api_key or (os.environ.get(API_KEY_ENV) if client is None else None)
        if client is None and async_client is None and not self._api_key:
            raise ValueError(
                f"No Vaquill API key. Pass api_key=... or set the {API_KEY_ENV} environment "
                "variable (keys start with vq_key_), or pass a pre-built client."
            )
        self._build_kwargs: Dict[str, Any] = {
            "default_headers": {"user-agent": integration_user_agent(user_agent_suffix)}
        }
        if base_url is not None:
            self._build_kwargs["base_url"] = base_url
        if timeout is not None:
            self._build_kwargs["timeout"] = timeout
        if max_retries is not None:
            self._build_kwargs["max_retries"] = max_retries
        if max_credits is not None:
            self._build_kwargs["max_credits"] = max_credits
        inherited = [getattr(c, "max_credits", None) for c in (client, async_client) if c]
        inherited = [c for c in inherited if c is not None]
        self.max_credits: Optional[float] = (
            max_credits if max_credits is not None else (min(inherited) if inherited else None)
        )

    @property
    def secrets(self) -> List[str]:
        return [self._api_key] if self._api_key else []

    @property
    def sync_client(self) -> Vaquill:
        if self._sync is None:
            self._sync = Vaquill(api_key=self._api_key, **self._build_kwargs)
        return self._sync

    @property
    def async_client(self) -> Optional[AsyncVaquill]:
        """The async client, or None when async calls should run the sync client in a thread."""
        if self._async is None and not self._sync_is_prebuilt:
            self._async = AsyncVaquill(api_key=self._api_key, **self._build_kwargs)
        return self._async

    @property
    def credits_spent(self) -> float:
        """Credits consumed by every client of this connection so far."""
        clients = [c for c in (self._sync, self._async) if c is not None]
        return float(sum(c.credits_spent for c in clients))

    def check_budget(self, estimate: float = 0.0) -> None:
        """Raise :class:`vaquill.SpendGuardExceeded` before a request that would break the cap.

        With ``estimate`` 0 this mirrors the SDK (stop once the cap is reached). With a worst-case
        ``estimate`` it stops a call that could overshoot the cap.
        """
        cap = self.max_credits
        if cap is None:
            return
        spent = self.credits_spent
        over = spent + estimate > cap if estimate > 0 else spent >= cap
        if over:
            raise SpendGuardExceeded(
                f"Spend guard reached: {spent:g} of {cap:g} credits used"
                + (f", and this call could cost up to {estimate:g} more." if estimate > 0 else ".")
            )

    def call(self, fn: Callable[[Any], T], estimate: float = 0.0) -> T:
        """Run ``fn(sync_client)`` after the budget check."""
        self.check_budget(estimate)
        return fn(self.sync_client)

    async def acall(self, fn: Callable[[Any], Awaitable[T]] | Callable[[Any], T], estimate: float = 0.0) -> T:
        """Run ``fn`` on the async client, or on the sync client in a thread when none exists."""
        self.check_budget(estimate)
        client = self.async_client
        if client is None:
            return await asyncio.to_thread(cast(Callable[[Any], T], fn), self.sync_client)
        return await cast(Callable[[Any], Awaitable[T]], fn)(client)
