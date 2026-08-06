"""D9 hardening: HMAC-signed webhook delivery with retry.

Best-effort side channel, not a second source of truth -- `GET
/v1/evaluations/{id}` always has the result regardless of whether webhook
delivery succeeds, so a failed delivery never fails the evaluation itself
(see `deliver()`'s docstring: it never raises).

Signing: HMAC-SHA256 over the raw JSON body, sent as `X-Wfeval-Signature:
sha256=<hex>`, keyed by `GATEWAY_WEBHOOK_SECRET`. If that env var isn't set,
delivery is skipped (logged) rather than signing with a predictable default
-- a caller who could guess a shared default secret could forge deliveries.

`callback_url` is caller-supplied and untrusted -- restricted to http(s)
schemes here as a minimal guard, but this is NOT a full SSRF defense (no
egress allow-listing, no private-IP/metadata-endpoint blocking). Flagged,
not solved -- same posture as decision 0015's pm4py licensing flag: a real
production deployment needs an actual egress policy, which is
infrastructure this repo doesn't have yet. See decision 0018.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
import os
from urllib.parse import urlparse

import httpx

from wfeval.core.report import EvaluationReport

logger = logging.getLogger(__name__)

_SECRET_ENV_VAR = "GATEWAY_WEBHOOK_SECRET"
_MAX_ATTEMPTS = 3
_BACKOFF_SECONDS = (0.5, 2.0)  # delay before attempt 2, then before attempt 3
_TIMEOUT_SECONDS = 5.0
_SIGNATURE_HEADER = "X-Wfeval-Signature"


def sign(secret: str, body: bytes) -> str:
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


async def deliver(callback_url: str, report: EvaluationReport) -> bool:
    """Best-effort. Returns whether delivery succeeded; never raises -- a
    webhook failure must not fail the evaluation it's reporting on."""
    parsed = urlparse(callback_url)
    if parsed.scheme not in ("http", "https"):
        logger.warning("Webhook not sent: callback_url %r has an unsupported scheme.", callback_url)
        return False

    secret = os.environ.get(_SECRET_ENV_VAR)
    if not secret:
        logger.warning(
            "Webhook not sent: %s is not set. Refusing to sign with a predictable "
            "default -- see webhook.py's module docstring.", _SECRET_ENV_VAR,
        )
        return False

    body = report.model_dump_json().encode("utf-8")
    headers = {"Content-Type": "application/json", _SIGNATURE_HEADER: sign(secret, body)}

    for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
                resp = await client.post(callback_url, content=body, headers=headers)
                resp.raise_for_status()
            return True
        except httpx.HTTPError as e:
            logger.warning(
                "Webhook delivery attempt %d/%d to %s failed: %s", attempt, _MAX_ATTEMPTS, callback_url, e,
            )
            if attempt < _MAX_ATTEMPTS:
                await asyncio.sleep(_BACKOFF_SECONDS[attempt - 1])
    return False
