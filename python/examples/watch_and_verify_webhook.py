"""Create a law-change watch, then verify a delivery in your webhook handler.

VAQUILL_API_KEY=vq_key_... python examples/watch_and_verify_webhook.py
"""

from __future__ import annotations

from collections.abc import Mapping

from vaquill import Vaquill, WebhookEvent, WebhookVerificationError, verify_webhook

SECRET = "whsec_MfKQ9r8GKYqrTwjUPD8ILPZIo2LaLaSw"  # pragma: allowlist secret


def create_watch(client: Vaquill) -> str:
    """Watch Washington state statutes. Watches are free."""
    created = client.watches.create(
        "state",
        state="wa",
        webhook_url="https://example.com/hooks/law-changes",
        webhook_secret=SECRET,
    )
    print(f"watching: {created.data.id}")
    return created.data.id


def handle_delivery(raw_body: bytes, headers: Mapping[str, str]) -> WebhookEvent | None:
    """Call this from your HTTP handler with the RAW request body, never re-serialised JSON."""
    try:
        event = verify_webhook(raw_body, headers, SECRET, allow_legacy=False)
    except WebhookVerificationError:
        return None  # answer 400 and do not process
    print(f"verified event: {event.event}")
    return event


def main(client: Vaquill) -> str:
    return create_watch(client)


if __name__ == "__main__":
    main(Vaquill())
