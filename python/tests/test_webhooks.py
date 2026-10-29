from __future__ import annotations

import base64
import hashlib
import hmac
import logging

import pytest

from vaquill import WebhookVerificationError, verify_webhook

# Known-answer vector from the Standard Webhooks README.
SECRET = "whsec_MfKQ9r8GKYqrTwjUPD8ILPZIo2LaLaSw"  # pragma: allowlist secret
MSG_ID = "msg_p5jXN8AQM9LWM0D4loKWxJek"
TS = 1614265330
PAYLOAD = b'{"test": 2432232314}'
SIG = "v1,g0hM9SsE+OTPJTGt/tmIKtSyZlE3uFJELVlNIOLJ1OE="
NOW = TS + 10


def headers(sig: str = SIG, ts: int = TS) -> dict[str, str]:
    return {"webhook-id": MSG_ID, "webhook-timestamp": str(ts), "webhook-signature": sig}


def sign(secret: str, body: bytes, msg_id: str = MSG_ID, ts: int = TS) -> str:
    key = base64.b64decode(secret[6:]) if secret.startswith("whsec_") else secret.encode()
    mac = hmac.new(key, f"{msg_id}.{ts}.".encode() + body, hashlib.sha256).digest()
    return "v1," + base64.b64encode(mac).decode()


def test_known_answer_vector() -> None:
    assert sign(SECRET, PAYLOAD) == SIG
    # The README payload has no `event`, so use a tolerant body check via a real event too.
    with pytest.raises(WebhookVerificationError, match="valid event"):
        verify_webhook(PAYLOAD, headers(), SECRET, now=NOW)


EVENT = b'{"event": "watch.changed", "firedAt": "2026-10-29T00:00:00Z", "extra": 1}'


def test_valid_event_returned_with_extras() -> None:
    event = verify_webhook(EVENT, headers(sign(SECRET, EVENT)), SECRET, now=NOW)
    assert event.event == "watch.changed" and event.fired_at == "2026-10-29T00:00:00Z"
    assert event.model_extra == {"extra": 1}


def test_str_payload_and_header_case_insensitive() -> None:
    h = {k.title(): v for k, v in headers(sign(SECRET, EVENT)).items()}
    assert verify_webhook(EVENT.decode(), h, SECRET, now=NOW).event == "watch.changed"


def test_tampered_body_rejected() -> None:
    with pytest.raises(WebhookVerificationError, match="signature"):
        verify_webhook(EVENT + b" ", headers(sign(SECRET, EVENT)), SECRET, now=NOW)


def test_wrong_secret_and_wrong_id_rejected() -> None:
    with pytest.raises(WebhookVerificationError):
        verify_webhook(EVENT, headers(sign(SECRET, EVENT)), "whsec_AAAA", now=NOW)
    bad = headers(sign(SECRET, EVENT, msg_id="other"))
    with pytest.raises(WebhookVerificationError):
        verify_webhook(EVENT, bad, SECRET, now=NOW)


def test_stale_and_future_timestamps_rejected() -> None:
    h = headers(sign(SECRET, EVENT))
    with pytest.raises(WebhookVerificationError, match="tolerance"):
        verify_webhook(EVENT, h, SECRET, now=TS + 301)
    with pytest.raises(WebhookVerificationError, match="tolerance"):
        verify_webhook(EVENT, h, SECRET, now=TS - 301)
    verify_webhook(EVENT, h, SECRET, tolerance=600, now=TS + 301)


def test_bad_timestamp_header() -> None:
    h = headers(sign(SECRET, EVENT))
    h["webhook-timestamp"] = "yesterday"
    with pytest.raises(WebhookVerificationError, match="timestamp"):
        verify_webhook(EVENT, h, SECRET, now=NOW)


def test_rotation_multiple_signatures_and_secrets() -> None:
    old = "whsec_" + base64.b64encode(b"old-secret-bytes").decode()
    two = f"{sign(SECRET, EVENT)} {sign(old, EVENT)}"
    verify_webhook(EVENT, headers(two), SECRET, now=NOW)
    verify_webhook(EVENT, headers(two), old, now=NOW)
    # Receiver rotating: only the old signature present, both secrets accepted.
    verify_webhook(EVENT, headers(sign(old, EVENT)), [SECRET, old], now=NOW)
    with pytest.raises(WebhookVerificationError):
        verify_webhook(EVENT, headers(sign(old, EVENT)), SECRET, now=NOW)


def test_unknown_signature_versions_ignored() -> None:
    with pytest.raises(WebhookVerificationError):
        verify_webhook(EVENT, headers("v2,abc"), SECRET, now=NOW)


def test_plain_secret_uses_utf8_bytes() -> None:
    plain = "my-plain-stored-secret"
    verify_webhook(EVENT, headers(sign(plain, EVENT)), plain, now=NOW)


def legacy(secret: str, body: bytes) -> dict[str, str]:
    digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return {"X-Vaquill-Event": "watch.changed", "X-Vaquill-Signature": f"sha256={digest}"}


def test_legacy_fallback_valid_and_warns(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.WARNING, logger="vaquill")
    event = verify_webhook(EVENT, legacy("plain-secret", EVENT), "plain-secret", allow_legacy=True)
    assert event.event == "watch.changed" and "replay" in caplog.text


def test_legacy_has_no_replay_protection() -> None:
    # A delivery signed years ago still verifies: that is the documented limitation.
    verify_webhook(EVENT, legacy("s", EVENT), "s", allow_legacy=True, now=TS + 10**9)


def test_legacy_tamper_disabled_and_missing() -> None:
    with pytest.raises(WebhookVerificationError):
        verify_webhook(EVENT + b"x", legacy("s", EVENT), "s", allow_legacy=True)
    with pytest.raises(WebhookVerificationError, match="Missing"):
        verify_webhook(EVENT, legacy("s", EVENT), "s")
    with pytest.raises(WebhookVerificationError, match="Missing"):
        verify_webhook(EVENT, legacy("s", EVENT), "s", allow_legacy=False)
    with pytest.raises(WebhookVerificationError, match="Missing"):
        verify_webhook(EVENT, {}, "s", allow_legacy=True)


def test_standard_headers_take_precedence_over_legacy() -> None:
    h = {**headers("v1,wrong"), **legacy("s", EVENT)}
    with pytest.raises(WebhookVerificationError):
        verify_webhook(EVENT, h, "s", now=NOW)


def test_valid_signature_with_non_event_body_raises_payload_error() -> None:
    from vaquill._webhooks import WebhookPayloadError

    body = b"not json"
    with pytest.raises(WebhookPayloadError):
        verify_webhook(body, headers(sign("s", body)), "s", now=NOW)
    with pytest.raises(WebhookVerificationError, match="No matching"):
        verify_webhook(body, headers("v1,wrong"), "s", now=NOW)


def test_whsec_secret_that_is_not_base64_is_refused() -> None:
    # Falling back to the literal text as the key would verify nothing the sender signed.
    with pytest.raises(ValueError, match="base64"):
        verify_webhook(EVENT, headers(sign(SECRET, EVENT)), "whsec_not*base64!", now=NOW)
