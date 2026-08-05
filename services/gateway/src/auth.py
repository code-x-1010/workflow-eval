"""D9 hardening: API-key auth on every Gateway endpoint except /healthz.

Keys come from `GATEWAY_API_KEYS` (comma-separated), checked against the
`X-Api-Key` header. **If `GATEWAY_API_KEYS` is unset, auth is a no-op
(open)** -- matches every other service in this repo, none of which have
auth yet, and keeps `WFEVAL_STUB_DEPS`/local dev working without extra
setup. This is a deliberate rollout choice, not an oversight: failing
*closed* by default would silently break every existing test and dev
workflow the moment this file is imported, for a security property nothing
else in the repo has established yet. A real deployment must set
`GATEWAY_API_KEYS` explicitly -- nothing here warns if it's left unset. See
decision 0018.
"""
from __future__ import annotations

import os

from fastapi import Header, HTTPException

_KEYS_ENV_VAR = "GATEWAY_API_KEYS"


def require_api_key(x_api_key: str | None = Header(None)) -> None:
    raw = os.environ.get(_KEYS_ENV_VAR)
    if not raw:
        return  # auth disabled -- see module docstring
    valid_keys = {k.strip() for k in raw.split(",") if k.strip()}
    if x_api_key not in valid_keys:
        raise HTTPException(status_code=401, detail="Missing or invalid X-Api-Key.")
