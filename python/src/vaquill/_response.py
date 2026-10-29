"""Response wrappers, the forward-compatible model base and the lenient enum helper."""

from __future__ import annotations

import enum
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Generic, TypeVar, cast

import httpx
from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, PrivateAttr
from pydantic.alias_generators import to_camel

from ._config import REPLAYED_HEADER, REQUEST_ID_HEADER

__all__ = [
    "APIResponse",
    "RateLimit",
    "ResponseModel",
    "VaquillModel",
    "lenient_enum",
    "lenient_validator",
]

T = TypeVar("T")
E = TypeVar("E", bound=enum.Enum)


class VaquillModel(BaseModel):
    """Base for response models: camelCase wire names, unknown fields kept, never raised on."""

    model_config = ConfigDict(extra="allow", populate_by_name=True, alias_generator=to_camel)


class ResponseModel(VaquillModel):
    """Top-level response model. Carries metering and request metadata."""

    credits_consumed: float | None = Field(default=None, alias="creditsConsumed")
    _request_id: str | None = PrivateAttr(default=None)
    _idempotent_replayed: bool = PrivateAttr(default=False)

    @property
    def request_id(self) -> str | None:
        return self._request_id

    @property
    def idempotent_replayed(self) -> bool:
        return self._idempotent_replayed


def lenient_enum(enum_cls: type[E], value: Any) -> E | Any:
    """Return the enum member for ``value``, or ``value`` unchanged if the server sent a new one."""
    try:
        return enum_cls(value)
    except ValueError:
        return value


def lenient_validator(enum_cls: type[E]) -> BeforeValidator:
    """For fields: ``Annotated[Status | str, lenient_validator(Status)]``."""
    return BeforeValidator(lambda v: lenient_enum(enum_cls, v))


def _int(value: str | None) -> int | None:
    try:
        return int(value) if value is not None else None
    except ValueError:
        return None


def _num(value: str | None) -> float | None:
    try:
        return float(value) if value is not None else None
    except ValueError:
        return None


@dataclass(frozen=True)
class RateLimit:
    """Parsed ``X-RateLimit-*`` headers. Any field is None when the server omitted it."""

    limit: int | None = None
    remaining: int | None = None
    reset: float | None = None
    limit_day: int | None = None
    remaining_day: int | None = None
    reset_day: float | None = None

    @classmethod
    def from_headers(cls, headers: httpx.Headers) -> RateLimit:
        g = headers.get
        return cls(
            limit=_int(g("X-RateLimit-Limit")),
            remaining=_int(g("X-RateLimit-Remaining")),
            reset=_num(g("X-RateLimit-Reset")),
            limit_day=_int(g("X-RateLimit-Limit-Day")),
            remaining_day=_int(g("X-RateLimit-Remaining-Day")),
            reset_day=_num(g("X-RateLimit-Reset-Day")),
        )


class APIResponse(Generic[T]):
    """What ``with_raw_response`` returns: the parsed body plus headers and metadata."""

    def __init__(self, http_response: httpx.Response, data: Any, cast: Callable[[Any], T]) -> None:
        self.http_response = http_response
        self._data = data
        self._cast = cast

    @property
    def status_code(self) -> int:
        return self.http_response.status_code

    @property
    def headers(self) -> httpx.Headers:
        return self.http_response.headers

    @property
    def request_id(self) -> str | None:
        return self.headers.get(REQUEST_ID_HEADER)

    @property
    def rate_limit(self) -> RateLimit:
        return RateLimit.from_headers(self.headers)

    @property
    def idempotent_replayed(self) -> bool:
        return self.headers.get(REPLAYED_HEADER, "").lower() == "true"

    @property
    def credits_consumed(self) -> float | None:
        """``creditsConsumed`` from the body when present. The stored figure on a replay."""
        data: Any = self._data
        value: Any = (
            cast("dict[str, Any]", data).get("creditsConsumed") if isinstance(data, dict) else None
        )
        return (
            float(value) if isinstance(value, int | float) and not isinstance(value, bool) else None
        )

    @property
    def credits_charged_this_call(self) -> float:
        """Zero on an idempotent replay, otherwise ``credits_consumed`` (0 when absent)."""
        return 0.0 if self.idempotent_replayed else (self.credits_consumed or 0.0)

    def json(self) -> Any:
        return self._data

    def parse(self) -> T:
        parsed = self._cast(self._data)
        if isinstance(parsed, ResponseModel):
            parsed._request_id = self.request_id  # pyright: ignore[reportPrivateUsage]
            parsed._idempotent_replayed = self.idempotent_replayed  # pyright: ignore[reportPrivateUsage]
        return parsed
