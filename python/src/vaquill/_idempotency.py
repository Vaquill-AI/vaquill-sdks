"""Idempotency keys: one UUIDv4 per logical call, reused across every retry."""

from __future__ import annotations

import uuid

from ._errors import VaquillError


def new_key() -> str:
    return str(uuid.uuid4())


def validate_key(key: str) -> str:
    """The server accepts 16 to 255 visible ASCII characters."""
    if not 16 <= len(key) <= 255 or not all(33 <= ord(c) <= 126 for c in key):
        raise VaquillError("idempotency_key must be 16 to 255 visible ASCII characters.")
    return key


def redact_key(key: str) -> str:
    """Keys are logged by their first 8 characters only."""
    return key[:8] + "..."
