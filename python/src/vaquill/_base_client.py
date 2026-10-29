"""Transport shared by the sync and async clients: auth, retries, idempotency, metering."""

from __future__ import annotations

import asyncio
import logging
import os
import platform
import threading
from collections.abc import Mapping
from types import TracebackType
from typing import Any, Self, TypeVar

import httpx
from pydantic import TypeAdapter

from . import _retry
from ._config import (
    API_KEY_ENV,
    API_KEY_PREFIX,
    BASE_URL_ENV,
    DEFAULT_BASE_URL,
    DEFAULT_MAX_RETRIES,
    DEFAULT_TIMEOUT,
    IDEMPOTENCY_HEADER,
    IDEMPOTENCY_STATUS_HEADER,
    REQUEST_ID_HEADER,
)
from ._errors import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    ResponseParseError,
    SpendGuardExceeded,
    VaquillError,
    make_status_error,
)
from ._idempotency import new_key, redact_key, validate_key
from ._response import APIResponse
from ._version import __version__

log = logging.getLogger("vaquill")

T = TypeVar("T")
Query = Mapping[str, Any]
Timeout = float | httpx.Timeout


class SpendTracker:
    """Running total of credits this client (and clients derived from it) has consumed."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._total = 0.0
        # Held from check to count by sync charged calls when max_credits is set.
        self.serial_lock = threading.Lock()

    @property
    def total(self) -> float:
        return self._total

    def add(self, credits: float) -> None:
        with self._lock:
            self._total += credits


def _resolve_api_key(api_key: str | None) -> str:
    key = api_key if api_key is not None else os.environ.get(API_KEY_ENV)
    # A key pasted from a file or a secret store often carries a trailing newline.
    key = key.strip() if key is not None else key
    if not key:
        raise VaquillError(f"No API key. Pass api_key=... or set the {API_KEY_ENV} variable.")
    if any(not 33 <= ord(c) <= 126 for c in key):
        # The key is deliberately not echoed.
        raise ValueError(
            "Invalid API key: it contains control, whitespace or non-ASCII characters. "
            "Check for a stray newline or quote in the value."
        )
    if not key.startswith(API_KEY_PREFIX):
        # The key is deliberately not echoed.
        raise VaquillError(f"Invalid API key: Vaquill keys start with '{API_KEY_PREFIX}'.")
    return key


def _user_agent() -> str:
    py, os_name = platform.python_version(), platform.system().lower()
    return f"vaquill-python/{__version__} python/{py} {os_name}"


class BaseClient:
    def __init__(
        self,
        *,
        api_key: str | None,
        base_url: str | None,
        timeout: Timeout | None,
        max_retries: int,
        default_headers: Mapping[str, str] | None,
        idempotency_keys: bool,
        max_credits: float | None,
    ) -> None:
        if max_retries < 0:
            raise VaquillError("max_retries must be >= 0.")
        self._api_key = _resolve_api_key(api_key)
        self.base_url = (base_url or os.environ.get(BASE_URL_ENV) or DEFAULT_BASE_URL).rstrip("/")
        self.timeout: Timeout = DEFAULT_TIMEOUT if timeout is None else timeout
        self.max_retries = max_retries
        self.default_headers: dict[str, str] = dict(default_headers or {})
        self.idempotency_keys = idempotency_keys
        self.max_credits = max_credits
        self._spend = SpendTracker()
        self._deprecations_seen: set[tuple[str, str]] = set()
        self._deprecations_lock = threading.Lock()

    def __repr__(self) -> str:
        return f"{type(self).__name__}(base_url={self.base_url!r})"

    @property
    def credits_spent(self) -> float:
        """Credits consumed by charged calls since construction (shared with derived clients)."""
        return self._spend.total

    def _derived_kwargs(
        self,
        *,
        api_key: str | None,
        base_url: str | None,
        timeout: Timeout | None,
        max_retries: int | None,
        default_headers: Mapping[str, str] | None,
        idempotency_keys: bool | None,
        max_credits: float | None,
    ) -> dict[str, Any]:
        return {
            "api_key": api_key or self._api_key,
            "base_url": base_url or self.base_url,
            "timeout": self.timeout if timeout is None else timeout,
            "max_retries": self.max_retries if max_retries is None else max_retries,
            "default_headers": {**self.default_headers, **(default_headers or {})},
            "idempotency_keys": (
                self.idempotency_keys if idempotency_keys is None else idempotency_keys
            ),
            "max_credits": self.max_credits if max_credits is None else max_credits,
        }

    def _check_spend(self, charged: bool) -> None:
        if charged and self.max_credits is not None and self._spend.total >= self.max_credits:
            raise SpendGuardExceeded(
                f"Spend guard reached: {self._spend.total:g} of {self.max_credits:g} credits used."
            )

    def _key_for(self, charged: bool, idempotency_key: str | None) -> str | None:
        if idempotency_key is not None:
            return validate_key(idempotency_key)
        return new_key() if charged and self.idempotency_keys else None

    def _headers(self, key: str | None, extra: Mapping[str, str] | None) -> dict[str, str]:
        headers = {"user-agent": _user_agent(), "accept": "application/json"}
        # Case-insensitive merge. Authorization and Idempotency-Key are ours alone.
        protected = {"authorization", IDEMPOTENCY_HEADER.lower()}
        for source in (self.default_headers, extra or {}):
            for name, value in source.items():
                if name.lower() not in protected:
                    headers[name.lower()] = value
        headers["authorization"] = f"Bearer {self._api_key}"
        if key is not None:
            headers[IDEMPOTENCY_HEADER.lower()] = key
        return headers

    def _target(self, path: str, params: Query | None) -> tuple[str, httpx.QueryParams | None]:
        """The URL (without query) and the merged query. ``params`` wins over the path's own."""
        path, _, _fragment = path.partition("#")
        path, _, query = path.partition("?")
        merged = httpx.QueryParams(query)
        given = self._params(params)
        if given:
            merged = merged.merge(given)
        return f"{self.base_url}/{path.lstrip('/')}", (merged if merged else None)

    def _url(self, path: str) -> str:
        return f"{self.base_url}/{path.lstrip('/')}"

    @staticmethod
    def _params(params: Query | None) -> dict[str, Any] | None:
        return None if params is None else {k: v for k, v in params.items() if v is not None}

    @staticmethod
    def _error_for(response: httpx.Response) -> APIStatusError:
        try:
            body: object = response.json()
        except ValueError:
            body = response.text
        return make_status_error(response, body)

    def _finish(
        self, response: httpx.Response, charged: bool, cast_to: Any, key: str | None
    ) -> APIResponse[Any]:
        if response.headers.get(IDEMPOTENCY_STATUS_HEADER, "").lower() == "unavailable":
            log.warning(
                "Server could not deduplicate this request (idempotency store unavailable)."
            )
        try:
            data = response.json() if response.content else None
        except ValueError as exc:
            raise ResponseParseError(
                f"Response was not valid JSON (status {response.status_code}).",
                request_id=response.headers.get(REQUEST_ID_HEADER),
                status_code=response.status_code,
            ) from exc
        adapter: TypeAdapter[Any] | None = None if cast_to is Any else TypeAdapter(cast_to)
        result: APIResponse[Any] = APIResponse(
            response, data, (lambda d: d) if adapter is None else adapter.validate_python
        )
        if charged:
            self._spend.add(result.credits_charged_this_call)
        log.debug("Response %s key=%s", response.status_code, redact_key(key) if key else None)
        return result

    def _note_deprecation(self, request: httpx.Request, response: httpx.Response) -> None:
        """One warning per (method, path) per client when the server flags an endpoint."""
        deprecation = response.headers.get("Deprecation")
        sunset = response.headers.get("Sunset")
        if deprecation is None and sunset is None:
            return
        seen = (request.method, request.url.path)
        with self._deprecations_lock:
            if seen in self._deprecations_seen:
                return
            self._deprecations_seen.add(seen)
        details = ", ".join(
            f"{name}: {value}"
            for name, value in (("Deprecation", deprecation), ("Sunset", sunset))
            if value is not None
        )
        log.warning("%s %s is deprecated (%s).", request.method, request.url.path, details)

    def _log_retry(self, why: str, delay: float, attempt: int, retries: int) -> None:
        log.debug("Retrying after %s in %.2fs (retry %d of %d)", why, delay, attempt + 1, retries)


class SyncAPIClient(BaseClient):
    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout: Timeout | None = None,
        max_retries: int = DEFAULT_MAX_RETRIES,
        default_headers: Mapping[str, str] | None = None,
        idempotency_keys: bool = True,
        max_credits: float | None = None,
        http_client: httpx.Client | None = None,
    ) -> None:
        super().__init__(
            api_key=api_key,
            base_url=base_url,
            timeout=timeout,
            max_retries=max_retries,
            default_headers=default_headers,
            idempotency_keys=idempotency_keys,
            max_credits=max_credits,
        )
        self._owns_http = http_client is None
        self._http = http_client or httpx.Client()

    def with_options(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout: Timeout | None = None,
        max_retries: int | None = None,
        default_headers: Mapping[str, str] | None = None,
        idempotency_keys: bool | None = None,
        max_credits: float | None = None,
    ) -> Self:
        """A copy with overrides. Shares the HTTP client and the spend total with this one."""
        new = type(self)(
            **self._derived_kwargs(
                api_key=api_key,
                base_url=base_url,
                timeout=timeout,
                max_retries=max_retries,
                default_headers=default_headers,
                idempotency_keys=idempotency_keys,
                max_credits=max_credits,
            ),
            http_client=self._http,
        )
        new._spend = self._spend  # pyright: ignore[reportPrivateUsage]
        return new

    def close(self) -> None:
        if self._owns_http:
            self._http.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    @property
    def with_raw_response(self) -> SyncRawRequester:
        return SyncRawRequester(self)

    def request(
        self,
        method: str,
        path: str,
        *,
        cast_to: type[T],
        params: Query | None = None,
        json: Any = None,
        headers: Mapping[str, str] | None = None,
        charged: bool = False,
        idempotency_key: str | None = None,
        timeout: Timeout | None = None,
        max_retries: int | None = None,
    ) -> T:
        """Send a request and return the parsed ``cast_to``.

        ``charged=True`` marks an operation that consumes credits: it gets an idempotency key
        (unless disabled), is checked against ``max_credits`` and is counted afterwards.
        """
        return self.request_with_response(
            method,
            path,
            cast_to=cast_to,
            params=params,
            json=json,
            headers=headers,
            charged=charged,
            idempotency_key=idempotency_key,
            timeout=timeout,
            max_retries=max_retries,
        ).parse()

    def raw_request(
        self,
        method: str,
        path: str,
        *,
        params: Query | None = None,
        json: Any = None,
        headers: Mapping[str, str] | None = None,
        charged: bool = False,
        idempotency_key: str | None = None,
        timeout: Timeout | None = None,
        max_retries: int | None = None,
    ) -> APIResponse[Any]:
        """Escape hatch for endpoints newer than this SDK. The body is returned as plain JSON."""
        return self.request_with_response(
            method,
            path,
            cast_to=Any,
            params=params,
            json=json,
            headers=headers,
            charged=charged,
            idempotency_key=idempotency_key,
            timeout=timeout,
            max_retries=max_retries,
        )

    def request_with_response(
        self,
        method: str,
        path: str,
        *,
        cast_to: Any,
        params: Query | None = None,
        json: Any = None,
        headers: Mapping[str, str] | None = None,
        charged: bool = False,
        idempotency_key: str | None = None,
        timeout: Timeout | None = None,
        max_retries: int | None = None,
    ) -> APIResponse[Any]:
        if charged and self.max_credits is not None:
            # Check-then-act must be exact: hold the lock from the check until the call is counted.
            with self._spend.serial_lock:
                self._check_spend(charged)
                return self._execute(
                    method, path, cast_to, params, json, headers, charged,
                    idempotency_key, timeout, max_retries,
                )  # fmt: skip
        self._check_spend(charged)
        return self._execute(
            method, path, cast_to, params, json, headers, charged,
            idempotency_key, timeout, max_retries,
        )  # fmt: skip

    def _execute(
        self,
        method: str,
        path: str,
        cast_to: Any,
        params: Query | None,
        json: Any,
        headers: Mapping[str, str] | None,
        charged: bool,
        idempotency_key: str | None,
        timeout: Timeout | None,
        max_retries: int | None,
    ) -> APIResponse[Any]:
        key = self._key_for(charged, idempotency_key)
        retries = self.max_retries if max_retries is None else max_retries
        url, query = self._target(path, params)
        attempt = 0
        while True:
            request = self._http.build_request(
                method,
                url,
                params=query,
                json=json,
                headers=self._headers(key, headers),
                timeout=self.timeout if timeout is None else timeout,
            )
            log.debug("Request %s %s key=%s", method, request.url, redact_key(key) if key else None)
            try:
                response = self._http.send(request)
            except httpx.RequestError as exc:
                if attempt < retries and _retry.connection_error_is_retryable(
                    exc, method=method, has_idempotency_key=key is not None
                ):
                    delay = _retry.backoff_delay(attempt)
                    self._log_retry(type(exc).__name__, delay, attempt, retries)
                    _retry.sleep(delay)
                    attempt += 1
                    continue
                if isinstance(exc, httpx.TimeoutException):
                    raise APITimeoutError(request=request) from exc
                raise APIConnectionError(request=request) from exc
            self._note_deprecation(request, response)
            if response.is_success:
                return self._finish(response, charged, cast_to, key)
            error = self._error_for(response)
            replay_safe = key is not None or not charged
            delay = (
                _retry.delay_for_status(error, attempt, replay_safe=replay_safe)
                if attempt < retries
                else None
            )
            if delay is None:
                raise error
            self._log_retry(f"status {response.status_code}", delay, attempt, retries)
            _retry.sleep(delay)
            attempt += 1


class AsyncAPIClient(BaseClient):
    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout: Timeout | None = None,
        max_retries: int = DEFAULT_MAX_RETRIES,
        default_headers: Mapping[str, str] | None = None,
        idempotency_keys: bool = True,
        max_credits: float | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        super().__init__(
            api_key=api_key,
            base_url=base_url,
            timeout=timeout,
            max_retries=max_retries,
            default_headers=default_headers,
            idempotency_keys=idempotency_keys,
            max_credits=max_credits,
        )
        self._owns_http = http_client is None
        self._http = http_client or httpx.AsyncClient()
        # Serialises charged calls when max_credits is set (see the Vaquill docstring).
        self._charge_lock = asyncio.Lock()

    def with_options(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout: Timeout | None = None,
        max_retries: int | None = None,
        default_headers: Mapping[str, str] | None = None,
        idempotency_keys: bool | None = None,
        max_credits: float | None = None,
    ) -> Self:
        """A copy with overrides. Shares the HTTP client and the spend total with this one."""
        new = type(self)(
            **self._derived_kwargs(
                api_key=api_key,
                base_url=base_url,
                timeout=timeout,
                max_retries=max_retries,
                default_headers=default_headers,
                idempotency_keys=idempotency_keys,
                max_credits=max_credits,
            ),
            http_client=self._http,
        )
        new._spend = self._spend  # pyright: ignore[reportPrivateUsage]
        new._charge_lock = self._charge_lock  # pyright: ignore[reportPrivateUsage]
        return new

    async def aclose(self) -> None:
        if self._owns_http:
            await self._http.aclose()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.aclose()

    @property
    def with_raw_response(self) -> AsyncRawRequester:
        return AsyncRawRequester(self)

    async def request(
        self,
        method: str,
        path: str,
        *,
        cast_to: type[T],
        params: Query | None = None,
        json: Any = None,
        headers: Mapping[str, str] | None = None,
        charged: bool = False,
        idempotency_key: str | None = None,
        timeout: Timeout | None = None,
        max_retries: int | None = None,
    ) -> T:
        """Async twin of :meth:`SyncAPIClient.request`."""
        response = await self.request_with_response(
            method,
            path,
            cast_to=cast_to,
            params=params,
            json=json,
            headers=headers,
            charged=charged,
            idempotency_key=idempotency_key,
            timeout=timeout,
            max_retries=max_retries,
        )
        return response.parse()

    async def raw_request(
        self,
        method: str,
        path: str,
        *,
        params: Query | None = None,
        json: Any = None,
        headers: Mapping[str, str] | None = None,
        charged: bool = False,
        idempotency_key: str | None = None,
        timeout: Timeout | None = None,
        max_retries: int | None = None,
    ) -> APIResponse[Any]:
        """Escape hatch for endpoints newer than this SDK. The body is returned as plain JSON."""
        return await self.request_with_response(
            method,
            path,
            cast_to=Any,
            params=params,
            json=json,
            headers=headers,
            charged=charged,
            idempotency_key=idempotency_key,
            timeout=timeout,
            max_retries=max_retries,
        )

    async def request_with_response(
        self,
        method: str,
        path: str,
        *,
        cast_to: Any,
        params: Query | None = None,
        json: Any = None,
        headers: Mapping[str, str] | None = None,
        charged: bool = False,
        idempotency_key: str | None = None,
        timeout: Timeout | None = None,
        max_retries: int | None = None,
    ) -> APIResponse[Any]:
        if charged and self.max_credits is not None:
            # Check-then-act must be exact: hold the lock from the check until the call is counted.
            async with self._charge_lock:
                self._check_spend(charged)
                return await self._execute(
                    method, path, cast_to, params, json, headers, charged,
                    idempotency_key, timeout, max_retries,
                )  # fmt: skip
        self._check_spend(charged)
        return await self._execute(
            method, path, cast_to, params, json, headers, charged,
            idempotency_key, timeout, max_retries,
        )  # fmt: skip

    async def _execute(
        self,
        method: str,
        path: str,
        cast_to: Any,
        params: Query | None,
        json: Any,
        headers: Mapping[str, str] | None,
        charged: bool,
        idempotency_key: str | None,
        timeout: Timeout | None,
        max_retries: int | None,
    ) -> APIResponse[Any]:
        key = self._key_for(charged, idempotency_key)
        retries = self.max_retries if max_retries is None else max_retries
        url, query = self._target(path, params)
        attempt = 0
        while True:
            request = self._http.build_request(
                method,
                url,
                params=query,
                json=json,
                headers=self._headers(key, headers),
                timeout=self.timeout if timeout is None else timeout,
            )
            log.debug("Request %s %s key=%s", method, request.url, redact_key(key) if key else None)
            try:
                response = await self._http.send(request)
            except httpx.RequestError as exc:
                if attempt < retries and _retry.connection_error_is_retryable(
                    exc, method=method, has_idempotency_key=key is not None
                ):
                    delay = _retry.backoff_delay(attempt)
                    self._log_retry(type(exc).__name__, delay, attempt, retries)
                    await _retry.asleep(delay)
                    attempt += 1
                    continue
                if isinstance(exc, httpx.TimeoutException):
                    raise APITimeoutError(request=request) from exc
                raise APIConnectionError(request=request) from exc
            self._note_deprecation(request, response)
            if response.is_success:
                return self._finish(response, charged, cast_to, key)
            error = self._error_for(response)
            replay_safe = key is not None or not charged
            delay = (
                _retry.delay_for_status(error, attempt, replay_safe=replay_safe)
                if attempt < retries
                else None
            )
            if delay is None:
                raise error
            self._log_retry(f"status {response.status_code}", delay, attempt, retries)
            await _retry.asleep(delay)
            attempt += 1


class SyncRawRequester:
    """``client.with_raw_response``: the same requests, returning :class:`APIResponse`."""

    def __init__(self, client: SyncAPIClient) -> None:
        self._client = client

    def request(self, method: str, path: str, *, cast_to: type[T], **kwargs: Any) -> APIResponse[T]:
        return self._client.request_with_response(method, path, cast_to=cast_to, **kwargs)

    def raw_request(self, method: str, path: str, **kwargs: Any) -> APIResponse[Any]:
        return self._client.raw_request(method, path, **kwargs)


class AsyncRawRequester:
    def __init__(self, client: AsyncAPIClient) -> None:
        self._client = client

    async def request(
        self, method: str, path: str, *, cast_to: type[T], **kwargs: Any
    ) -> APIResponse[T]:
        return await self._client.request_with_response(method, path, cast_to=cast_to, **kwargs)

    async def raw_request(self, method: str, path: str, **kwargs: Any) -> APIResponse[Any]:
        return await self._client.raw_request(method, path, **kwargs)
