"""Transport shared by the sync and async clients: auth, retries, idempotency, metering."""

from __future__ import annotations

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
)
from ._errors import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
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

    @property
    def total(self) -> float:
        return self._total

    def add(self, credits: float) -> None:
        with self._lock:
            self._total += credits


def _resolve_api_key(api_key: str | None) -> str:
    key = api_key if api_key is not None else os.environ.get(API_KEY_ENV)
    if not key:
        raise VaquillError(f"No API key. Pass api_key=... or set the {API_KEY_ENV} variable.")
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
        headers = {"User-Agent": _user_agent(), "Accept": "application/json"}
        headers.update(self.default_headers)
        headers["Authorization"] = f"Bearer {self._api_key}"
        if key is not None:
            headers[IDEMPOTENCY_HEADER] = key
        headers.update(extra or {})
        return headers

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
            raise VaquillError(
                f"Response was not valid JSON (status {response.status_code})."
            ) from exc
        adapter: TypeAdapter[Any] | None = None if cast_to is Any else TypeAdapter(cast_to)
        result: APIResponse[Any] = APIResponse(
            response, data, (lambda d: d) if adapter is None else adapter.validate_python
        )
        if charged:
            self._spend.add(result.credits_charged_this_call)
        log.debug("Response %s key=%s", response.status_code, redact_key(key) if key else None)
        return result

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
        self._check_spend(charged)
        key = self._key_for(charged, idempotency_key)
        retries = self.max_retries if max_retries is None else max_retries
        attempt = 0
        while True:
            request = self._http.build_request(
                method,
                self._url(path),
                params=self._params(params),
                json=json,
                headers=self._headers(key, headers),
                timeout=self.timeout if timeout is None else timeout,
            )
            log.debug("Request %s %s key=%s", method, request.url, redact_key(key) if key else None)
            try:
                response = self._http.send(request)
            except httpx.TransportError as exc:
                if attempt < retries and _retry.connection_error_is_retryable(
                    exc, charged=charged, has_idempotency_key=key is not None
                ):
                    delay = _retry.backoff_delay(attempt)
                    self._log_retry(type(exc).__name__, delay, attempt, retries)
                    _retry.sleep(delay)
                    attempt += 1
                    continue
                if isinstance(exc, httpx.TimeoutException):
                    raise APITimeoutError(request=request) from exc
                raise APIConnectionError(request=request) from exc
            if response.is_success:
                return self._finish(response, charged, cast_to, key)
            error = self._error_for(response)
            delay = _retry.delay_for_status(error, attempt) if attempt < retries else None
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
        self._check_spend(charged)
        key = self._key_for(charged, idempotency_key)
        retries = self.max_retries if max_retries is None else max_retries
        attempt = 0
        while True:
            request = self._http.build_request(
                method,
                self._url(path),
                params=self._params(params),
                json=json,
                headers=self._headers(key, headers),
                timeout=self.timeout if timeout is None else timeout,
            )
            log.debug("Request %s %s key=%s", method, request.url, redact_key(key) if key else None)
            try:
                response = await self._http.send(request)
            except httpx.TransportError as exc:
                if attempt < retries and _retry.connection_error_is_retryable(
                    exc, charged=charged, has_idempotency_key=key is not None
                ):
                    delay = _retry.backoff_delay(attempt)
                    self._log_retry(type(exc).__name__, delay, attempt, retries)
                    await _retry.asleep(delay)
                    attempt += 1
                    continue
                if isinstance(exc, httpx.TimeoutException):
                    raise APITimeoutError(request=request) from exc
                raise APIConnectionError(request=request) from exc
            if response.is_success:
                return self._finish(response, charged, cast_to, key)
            error = self._error_for(response)
            delay = _retry.delay_for_status(error, attempt) if attempt < retries else None
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
