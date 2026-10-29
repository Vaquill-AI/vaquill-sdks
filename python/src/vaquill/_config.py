"""Constants shared by the transport. Values mirror openai-python's retry defaults."""

from __future__ import annotations

import httpx

DEFAULT_BASE_URL = "https://api.vaquill.ai"
API_KEY_ENV = "VAQUILL_API_KEY"
BASE_URL_ENV = "VAQUILL_BASE_URL"
API_KEY_PREFIX = "vq_key_"  # pragma: allowlist secret

DEFAULT_TIMEOUT = httpx.Timeout(60.0, connect=5.0)
DEFAULT_MAX_RETRIES = 2
INITIAL_RETRY_DELAY = 0.5
MAX_RETRY_DELAY = 8.0
# A server-requested wait longer than this is not worth holding the caller for.
MAX_RETRY_AFTER_DELAY = 120.0

IDEMPOTENCY_HEADER = "Idempotency-Key"
REPLAYED_HEADER = "Idempotent-Replayed"
IDEMPOTENCY_STATUS_HEADER = "Idempotency-Status"
REQUEST_ID_HEADER = "X-Request-ID"
