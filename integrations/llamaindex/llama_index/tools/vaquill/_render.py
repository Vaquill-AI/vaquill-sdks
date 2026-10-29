"""Shrink SDK responses to compact JSON text for a model."""

import json
import re
from typing import Any, Iterable, Optional

__all__ = ["render", "to_data"]

_DROP_KEYS = {"processingTimeMs", "requestId"}
_SECRET_KEY = re.compile(r"secret|authorization|password|token|apikey", re.IGNORECASE)


def to_data(obj: Any) -> Any:
    """A JSON-ready structure with camelCase keys and no nulls."""
    if hasattr(obj, "model_dump"):
        return obj.model_dump(mode="json", by_alias=True, exclude_none=True)
    if isinstance(obj, (list, tuple)):
        return [to_data(item) for item in obj]
    return obj


def _clean(value: Any, max_chars: int) -> Any:
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            if key in _DROP_KEYS:
                continue
            if _SECRET_KEY.search(str(key)):
                out[key] = "[redacted]"
                continue
            out[key] = _clean(item, max_chars)
        return out
    if isinstance(value, list):
        return [_clean(item, max_chars) for item in value]
    if isinstance(value, str) and len(value) > max_chars:
        return value[:max_chars] + f"...[truncated {len(value) - max_chars} characters]"
    return value


def _project(data: Any, keep: Iterable[str]) -> Any:
    wanted = set(keep)
    if isinstance(data, dict):
        return {k: v for k, v in data.items() if k in wanted}
    return data


def render(
    obj: Any,
    *,
    max_chars: int = 12000,
    list_key: Optional[str] = None,
    keep: Optional[Iterable[str]] = None,
) -> str:
    """Compact JSON for ``obj``.

    Args:
        max_chars: Longest string kept; longer text is cut with a marker the model can see.
        list_key: A top-level list whose rows are projected onto ``keep``.
        keep: Row fields to keep (everything else is dropped to save context).
    """
    data = to_data(obj)
    if list_key and keep is not None and isinstance(data, dict) and isinstance(data.get(list_key), list):
        data[list_key] = [_project(row, keep) for row in data[list_key]]
    return json.dumps(_clean(data, max_chars), ensure_ascii=False, separators=(",", ":"))
