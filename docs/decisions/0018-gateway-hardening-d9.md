# 0018 — Gateway hardening (charter D9): idempotency, webhook, API-key auth

**Author:** P1   **Date:** 2026-08-06   **Status:** accepted   **Affects:** P1, whoever operates this commercially

## Context

Charter D9: "Gateway hardening: async queue, webhook retry + HMAC,
idempotency on `request_id`, API-key auth. Done when: replaying the same
`request_id` returns the cached report, not a second run." The Gateway's own
contract (`contracts/gateway.openapi.yaml`) already documented `request_id`
as an idempotency key and `callback_url` as "HMAC-signed, retried" from D2 --
none of that was implemented until now.

**Scoped out, deliberately:** the "async queue" half of D9. `orchestrate.py`
already documents why the pipeline runs synchronously in the request handler
today (Spiff execution is seconds, not minutes) and that a real queue is
D9-or-later infrastructure, not a correctness requirement. `arq` is already a
base dependency in `pyproject.toml`, suggesting a Redis-backed queue was the
original intent -- but standing that up needs Redis and a worker process,
neither of which exist in this repo's `docker-compose` yet, and I have no
way to verify a Redis-backed flow actually works in this environment (no
Redis available to test against). Implementing untested queue infrastructure
would be worse than not implementing it. The charter's own "done when" for
D9 is specifically about idempotency, not queue infrastructure -- satisfied
below without one.

## Decision

- **Idempotency** (`orchestrate.py`): new module-level `_REQUEST_ID_INDEX:
  dict[str, str]` (request_id -> evaluation_id). `run_full_evaluation`
  checks it first; a known `request_id` returns the original `evaluation_id`
  immediately, no HTTP calls, no second webhook delivery. Keyed on
  `request_id` alone, matching the contract's literal wording -- it doesn't
  ask us to also compare artifact content.
- **Webhook** (new `services/gateway/src/webhook.py`): HMAC-SHA256 over the
  raw JSON body (`X-Wfeval-Signature: sha256=<hex>`), keyed by
  `GATEWAY_WEBHOOK_SECRET`. 3 attempts, backing off 0.5s/2s. Best-effort --
  `deliver()` never raises, since a failed webhook must not fail the
  evaluation it's reporting on (`GET /v1/evaluations/{id}` is always the
  source of truth regardless). If `GATEWAY_WEBHOOK_SECRET` isn't set,
  delivery is skipped rather than signing with a predictable default.
  `callback_url` is restricted to `http`/`https` schemes as a minimal guard
  -- **this is not a full SSRF defense** (no egress allow-listing, no
  private-IP/metadata-endpoint blocking). Flagged, not solved, same posture
  as decision 0015's pm4py licensing flag.
- **API-key auth** (new `services/gateway/src/auth.py`): `X-Api-Key` header
  checked against `GATEWAY_API_KEYS` (comma-separated). **Open by default
  when unset** -- a deliberate rollout choice: failing closed would silently
  break every existing test and dev workflow for a security property nothing
  else in this repo has yet. `/healthz` is always exempt.
- Contract changes to `contracts/gateway.openapi.yaml` (frozen after D2,
  hence this record): added `securitySchemes.ApiKeyAuth` and a top-level
  `security` requirement, with `/healthz` overridden to `security: []`. The
  block describes the hardened shape a real deployment should reach, not a
  guarantee every environment enforces it (documented inline).

## Consequences

- `test_orchestrate.py` needed an autouse fixture clearing
  `_EVALUATIONS`/`_REQUEST_ID_INDEX` between tests -- multiple existing
  tests share one hardcoded `request_id`, which is exactly what idempotency
  is now supposed to catch. Real idempotency working correctly surfaced a
  pre-existing test-isolation gap; fixed there, not by weakening the feature.
- A production deployment still needs: an actual egress policy for
  `callback_url` (SSRF), a real secret-management story for
  `GATEWAY_WEBHOOK_SECRET`/`GATEWAY_API_KEYS` (currently plain env vars),
  and the async queue if Sandbox execution ever stops being seconds-fast.
  None of these are pretended to be solved here.

## Sign-off

- [x] P1
