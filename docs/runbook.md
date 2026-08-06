# Runbook

For whoever operates the Gateway and the four services behind it. If you're
integrating *against* this system rather than running it, read
`docs/integration-guide.md` instead.

## Starting it

```bash
uv sync --all-extras
make dev          # all 5 services, dependencies stubbed -- always works, no config needed
make dev-real     # real inter-service calls -- needs the env vars below
```

`make dev` sets `WFEVAL_STUB_DEPS=1` for every service, so each one serves
its committed golden example (`contracts/examples/*.json`) instead of
calling anything downstream. Use it to smoke-test a single service, or when
you don't have the other four running. `make dev-real` is what actually
exercises the fan-out described in `docs/integration-guide.md`.

## Environment variables

None of these are required for `make dev` (stub mode). For `make dev-real`
or a real deployment:

| Variable | Read by | Default | Purpose |
|---|---|---|---|
| `VALIDATION_URL` | Gateway | `http://validation:8001` | Where to reach Validation |
| `INTENT_URL` | Gateway | `http://intent:8002` | Where to reach Intent |
| `SANDBOX_URL` | Gateway, Validation | `http://sandbox:8003` | Where to reach Sandbox. Validation uses it for L2 reference checks; Gateway uses it for deploy/execution. |
| `COST_URL` | Gateway | `http://cost:8004` | Where to reach Cost |
| `GATEWAY_API_KEYS` | Gateway | unset (auth open) | Comma-separated valid `X-Api-Key` values. **Unset means every non-`/healthz` route is open to anyone who can reach it.** Set this before exposing the Gateway outside a trusted network. |
| `GATEWAY_WEBHOOK_SECRET` | Gateway | unset (webhooks skipped) | HMAC key for signing `callback_url` deliveries. Without it, a request with `callback_url` set still runs and completes normally -- delivery is just silently skipped, logged as a warning. |

The default hostnames (`validation`, `intent`, `sandbox`, `cost`) are
`docker-compose` service names, not resolvable outside that network -- set
all four explicitly if you're running services on separate hosts or bare
ports.

## Health checks

Every service exposes `GET /healthz`, unauthenticated always (even with
`GATEWAY_API_KEYS` set):

```json
{ "status": "ok", "service": "gateway", "owner": "P1" }
```

A 200 here means the process is up and can serve requests — it does **not**
mean its downstream dependencies are reachable. There is no deep/readiness
check that pings the other four services; the first real sign of a
downstream outage is a `502` on an actual request.

## Diagnosing a `502`

A `502` from the Gateway means a downstream service was completely
unreachable (connection refused, DNS failure, or timeout after 30s) — not
that it returned an error. Check:

1. Is the failing service's own `/healthz` responding?
2. Are the `*_URL` env vars pointing at the right host for your deployment
   (docker-compose service name vs. a real hostname)?
3. Check that service's own logs for a crash-on-startup.

`POST /v1/validate` degrades gracefully around exactly one dependency:
Sandbox being down doesn't fail Validation's L2 tier, it just moves `L2`
into `tiers_skipped` with `"asset registry unavailable"` and returns 200
anyway. Every other dependency in every other path is hard -- if Cost,
Intent, or Sandbox's deploy/execution endpoints are unreachable during
`/v1/validate` or `/v1/evaluations`, that request 502s.

## Data durability

`_EVALUATIONS` (Gateway) and `_REQUEST_ID_INDEX` (Gateway's idempotency
index) are **in-memory, per-process**. A restart loses every in-flight and
completed evaluation, and the idempotency guarantee ("replaying `request_id`
returns the cached result") only holds within one process's uptime. Same
limitation on Sandbox's `_EXECUTIONS`. None of this is durable storage —
acceptable for a dev/single-instance deployment, not for one that restarts
or scales horizontally. See `docs/decisions/0018-gateway-hardening-d9.md`
for what a real fix would need (a real store, plus the async queue that
decision also scoped out for the same reason: nothing here to build or test
it against yet).

## Webhook delivery failures

Check the Gateway's logs for `Webhook delivery attempt N/3 to <url> failed`.
Delivery is best-effort and retried 3 times with backoff; **a failed
webhook never fails the evaluation itself** — the result is always sitting
at `GET /v1/evaluations/{id}` regardless. If a consumer reports never
receiving a webhook, get them to poll instead while you investigate; don't
treat it as data loss.

Two things that silently produce zero webhook attempts, not an error: no
`GATEWAY_WEBHOOK_SECRET` configured, or a `callback_url` with a scheme other
than `http`/`https`. Both log a warning; neither raises.

## Known gaps (not bugs — see the linked decisions for why)

- **AGPL licensing**: Validation's L4 soundness check depends on `pm4py`
  (AGPL v3). This is a network service. Get a legal read on this before
  treating it as production-ready. See `docs/decisions/0015-pm4py-agpl-license-flag.md`.
- **Webhook SSRF**: `callback_url` is only scheme-checked (http/https), not
  validated against an egress allow-list. A caller could point it at an
  internal address. See `docs/decisions/0018-gateway-hardening-d9.md`.
- **No async queue**: Sandbox execution runs synchronously inside the
  request handler. Fine while Spiff is the only runner (seconds, not
  minutes); would need real infrastructure (Redis + a worker) the moment a
  slower runner (e.g. real UiPath Maestro) is added. `arq` is already a
  declared dependency for exactly this, unused today.
- **`platform: n8n`** is accepted by every schema (won't 422) but not
  actually implemented behind any of the four services yet.
