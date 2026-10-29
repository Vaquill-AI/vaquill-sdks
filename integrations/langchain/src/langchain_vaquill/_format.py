"""Turn SDK response models into compact JSON the model can read."""

from __future__ import annotations

import json
from typing import Any

from ._errors import redact

__all__ = ["STATUTE_KEEP", "dump", "project_statutes", "prune", "render", "section_text"]

# The fields of a section row worth a model's context. The full row has about 170 members.
STATUTE_KEEP = (
    "actId",
    "citation",
    "citationShort",
    "sectionTitle",
    "title",
    "state",
    "corpusType",
    "actStatus",
    "goodLawStatus",
    "excerpt",
    "body",
    "sourceUrl",
    "effectiveDate",
    "lastAmendedDate",
    "currentThrough",
    "currencyNote",
    "relevanceScore",
    "displayPath",
    "breadcrumb",
    "bodyUnavailable",
    "renumberedTo",
    "transferredTo",
    "supersededBy",
    "amendmentNote",
    "history",
    "wordCount",
)
_DROP_KEYS = {"processingTimeMs", "parsedQuery", "href"}
_SECRET_MARKERS = ("secret", "password", "token")


def dump(value: Any) -> Any:
    """A JSON-safe dict (wire names, no None) from a pydantic model, or the value itself."""
    if hasattr(value, "model_dump"):
        return value.model_dump(by_alias=True, exclude_none=True, mode="json")
    return value


def prune(value: Any) -> Any:
    """Drop None, empty containers, bookkeeping fields and secret-looking values, recursively."""
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, item in value.items():
            if key in _DROP_KEYS:
                continue
            if any(marker in key.lower() for marker in _SECRET_MARKERS) and isinstance(item, str):
                continue
            cleaned = prune(item)
            if cleaned in (None, "", [], {}):
                continue
            out[key] = cleaned
        return out
    if isinstance(value, list):
        return [c for c in (prune(v) for v in value) if c not in (None, "", [], {})]
    return value


def project_statutes(value: Any) -> Any:
    """Cut section-shaped rows (they carry ``actId`` and dozens of members) to STATUTE_KEEP."""
    if isinstance(value, dict):
        if "actId" in value and len(value) > 25:
            return {k: value[k] for k in STATUTE_KEEP if k in value}
        return {k: project_statutes(v) for k, v in value.items()}
    if isinstance(value, list):
        return [project_statutes(v) for v in value]
    return value


def _clip(value: Any, limit: int) -> Any:
    if isinstance(value, str):
        return value if len(value) <= limit else value[:limit] + "...[cut]"
    if isinstance(value, dict):
        return {k: _clip(v, limit) for k, v in value.items()}
    if isinstance(value, list):
        return [_clip(v, limit) for v in value]
    return value


def render(value: Any, max_chars: int = 30000) -> str:
    """Compact JSON, shrunk (long strings first) until it fits ``max_chars``."""
    data = redact_strings(prune(dump(value)))
    text = json.dumps(data, ensure_ascii=False, separators=(",", ":"), default=str)
    limit = 20000
    while len(text) > max_chars and limit > 200:
        limit //= 2
        text = json.dumps(
            _clip(data, limit), ensure_ascii=False, separators=(",", ":"), default=str
        )
    if len(text) > max_chars:
        text = text[: max_chars - 40] + '..."output cut to fit the limit"'
    return text


def redact_strings(value: Any) -> Any:
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, dict):
        return {k: redact_strings(v) for k, v in value.items()}
    if isinstance(value, list):
        return [redact_strings(v) for v in value]
    return value


def section_text(body: dict[str, Any], max_chars: int) -> dict[str, Any]:
    """Reduce a ``/body`` response to its text (operative text preferred) plus provenance."""
    text, kind = None, None
    if body.get("content"):
        text, kind = body["content"], "operative"
    else:
        for key in ("plain", "markdown", "html"):
            if body.get(key):
                text, kind = body[key], "full"
                break
    out: dict[str, Any] = {
        k: body[k]
        for k in (
            "actId",
            "resolvedFrom",
            "available",
            "bodyUnavailable",
            "bodyUnavailableReason",
            "pinpoint",
            "asOf",
            "note",
            "sourceUrl",
            "sourceCredit",
            "creditsConsumed",
        )
        if k in body
    }
    if text is not None:
        out["textKind"] = kind
        out["totalChars"] = len(text)
        if len(text) > max_chars:
            out["text"] = text[:max_chars]
            out["truncated"] = True
        else:
            out["text"] = text
    if body.get("subsections"):
        out["subsections"] = body["subsections"]
    return out
