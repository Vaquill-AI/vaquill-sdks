"""Webhook verification: Standard Webhooks (preferred) and the legacy signature header."""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import logging
import time
from collections.abc import Mapping, Sequence

from ._errors import WebhookVerificationError
from ._response import VaquillModel

__all__ = ["WebhookEvent", "WebhookPayloadError", "WebhookVerificationError", "verify_webhook"]

log = logging.getLogger("vaquill")
SECRET_PREFIX = "whsec_"  # pragma: allowlist secret


class WebhookEvent(VaquillModel):
    """Event envelope. Every other member of the payload is kept as an extra field."""

    event: str
    fired_at: str | None = None


def _key(secret: str) -> bytes:
    if secret.startswith(SECRET_PREFIX):
        try:
            return base64.b64decode(secret[len(SECRET_PREFIX) :], validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ValueError(
                "The webhook secret starts with 'whsec_' but is not valid base64."
            ) from exc
    return secret.encode("utf-8")


def _require_secrets(secrets: Sequence[str]) -> None:
    """An unset environment variable must never verify a forged event: refuse a blank secret."""
    if not secrets:
        raise ValueError("A webhook secret is required.")
    for s in secrets:
        if not isinstance(s, str) or not s.strip() or s.strip() == SECRET_PREFIX:  # pyright: ignore[reportUnnecessaryIsInstance]
            raise ValueError("The webhook secret is empty or blank.")


def _any_match(candidates: Sequence[str], expected: Sequence[str]) -> bool:
    # No early exit: every comparison runs so timing does not reveal which one matched.
    matched = False
    for given in candidates:
        for want in expected:
            matched |= hmac.compare_digest(given.encode(), want.encode())
    return matched


class WebhookPayloadError(WebhookVerificationError):
    """The signature matched but the body is not a Vaquill event."""


def verify_webhook(
    payload: bytes | str,
    headers: Mapping[str, str],
    secret: str | Sequence[str],
    tolerance: int = 300,
    *,
    allow_legacy: bool = False,
    now: float | None = None,
) -> WebhookEvent:
    """Verify a delivery and return its parsed event. Raises ``WebhookVerificationError``.

    ``payload`` must be the raw request body, never re-serialised JSON. ``secret`` may be a
    list to accept both secrets during a rotation. Raises ``ValueError`` (not a verification
    error) for an empty or whitespace-only secret, so a missing configuration value is a loud
    failure and can never accept a forged event.

    Standard Webhooks (``webhook-id``, ``webhook-timestamp``, ``webhook-signature``) is
    checked first, with a ``tolerance`` window in seconds either side of ``now``.

    Legacy ``X-Vaquill-Signature: sha256=<hmac>`` deliveries are rejected unless
    ``allow_legacy=True``. WARNING: the legacy scheme signs only the body, so it has NO
    replay protection; a captured delivery verifies forever. Opt in only while your
    endpoint still receives deliveries without the Standard Webhooks headers.
    """
    body = payload.encode("utf-8") if isinstance(payload, str) else payload
    h = {k.lower(): v for k, v in headers.items()}
    secrets = [secret] if isinstance(secret, str) else list(secret)
    _require_secrets(secrets)

    msg_id, stamp, sig = h.get("webhook-id"), h.get("webhook-timestamp"), h.get("webhook-signature")
    if msg_id and stamp and sig:
        try:
            ts = int(stamp)
        except ValueError as exc:
            raise WebhookVerificationError("Invalid webhook-timestamp.") from exc
        if abs((time.time() if now is None else now) - ts) > tolerance:
            raise WebhookVerificationError("Webhook timestamp is outside the tolerance window.")
        signed = f"{msg_id}.{ts}.".encode() + body
        expected = [
            base64.b64encode(hmac.new(_key(s), signed, hashlib.sha256).digest()).decode()
            for s in secrets
        ]
        given = [p[3:] for p in sig.split() if p.startswith("v1,")]
        if not _any_match(given, expected):
            raise WebhookVerificationError("No matching signature.")
    else:
        legacy = h.get("x-vaquill-signature")
        if not allow_legacy or not legacy:
            raise WebhookVerificationError("Missing webhook signature headers.")
        log.warning("Verifying a legacy X-Vaquill-Signature: there is no replay protection.")
        expected = [
            "sha256=" + hmac.new(s.encode("utf-8"), body, hashlib.sha256).hexdigest()
            for s in secrets
        ]
        if not _any_match([legacy], expected):
            raise WebhookVerificationError("No matching signature.")

    try:
        return WebhookEvent.model_validate(json.loads(body))
    except (ValueError, TypeError) as exc:
        raise WebhookPayloadError("Payload is not a valid event.") from exc
