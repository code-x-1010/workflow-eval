# Integration guide

For teams outside this project who want to call the Gateway. If you're one
of the four agents building this system, you don't need this file — read
`AGENTS.md` and your charter instead.

The full machine-readable contract is `contracts/gateway.openapi.yaml`
(OpenAPI 3.1, self-contained — no external `$ref`s to resolve). This guide
is the human-readable walkthrough of that same contract, with real request
and response bodies.

## What this is

A quality layer that sits downstream of your workflow generator. You give
it a BPMN or DMN artifact; it tells you whether that artifact will load and
run, whether it matches what the user asked for, whether it behaves
correctly when actually executed, and what it will cost. One front door —
the Gateway, `:8000` — fans out to four services behind it.

You will call exactly one of two endpoints, depending on when in your
pipeline you're calling.

## Endpoint 1: `POST /v1/validate` — the pre-deployment gate

Call this **synchronously, before every deploy**. Sub-2-second response.
Runs Validation's four-tier static ladder (schema, references, structure,
soundness/dataflow) plus Cost. Never calls Sandbox or Intent — those take
minutes, not seconds, and don't belong in a deploy-blocking check.

```bash
curl -X POST http://gateway-host:8000/v1/validate \
  -H "Content-Type: application/json" \
  -H "X-Api-Key: $YOUR_API_KEY" \
  -d '{
    "request_id": "gen-7f3a91",
    "platform": "uipath_maestro",
    "artifact": { "format": "bpmn", "content": "<definitions>...</definitions>" },
    "prompt": "When an invoice arrives, extract the amount and vendor..."
  }'
```

Always returns **200**, even when the artifact fails — a failing gate is a
valid result, not a request error. Check `verdict` and `validation.gates`,
not the HTTP status code:

```json
{
  "evaluation_id": "ev_a1b2c3d4",
  "request_id": "gen-7f3a91",
  "platform": "uipath_maestro",
  "verdict": "pass_with_warnings",
  "scoring_version": "0.1.0",
  "overall": 0.94,
  "validation": {
    "gates": { "schema_validity": true, "reference_integrity": true },
    "scores": { "structural_soundness": 0.9786, "process_soundness": 1.0, "dataflow_correctness": 1.0 },
    "diagnostics": [
      {
        "code": "STR-GATEWAY-NO-DEFAULT",
        "severity": "warning",
        "message": "Exclusive gateway 'Gateway_amount' has 2 outgoing flows; 2 have no condition and none is marked default.",
        "suggested_fix": "Mark one outgoing flow from 'Gateway_amount' as the default flow, or add a condition to every outgoing flow.",
        "element_id": "Gateway_amount",
        "locator": "/definitions/process/exclusiveGateway[@id='Gateway_amount']"
      }
    ],
    "ast_digest": "sha256:debed6...",
    "tiers_run": ["L1", "L2", "L3", "L4"],
    "tiers_skipped": {}
  },
  "intent": null,
  "execution": null,
  "cost": { "currency": "USD", "pricing_version": "...", "per_instance": { "expected": 0.04 } },
  "timings_ms": { "validation": 340, "cost": 210 },
  "short_circuited_at": null
}
```

`intent` and `execution` are always `null` on this endpoint. That's
expected, not a short-circuit — this endpoint doesn't run those tiers at
all. **Every `diagnostics[]` entry is a keyed, versioned code** (`STR-*`,
`SCH-*`, `REF-*`, `FLW-*`, `DMN-*` — see `GET /v1/diagnostics/codes` on the
Validation service, or `packages/wfeval-core/src/wfeval/core/diagnostics.py`
for the full registry). Key your own repair logic off `code`, not
`message` — messages are for humans and may be reworded; codes are
append-only and never renamed.

`gates` is binary pass/fail. `severity: "warning"` diagnostics degrade
`scores` but never flip a gate — only `error`-severity findings do that.

## Endpoint 2: `POST /v1/evaluations` — the full pipeline

Call this when you want the complete quality signal for generator
improvement or regression tracking — not per-deploy. Runs the full
pipeline: validation → deploy to a sandbox → execution against generated
test cases → intent alignment → cost. Minutes, not seconds, dominated by
sandbox execution.

```bash
curl -X POST http://gateway-host:8000/v1/evaluations \
  -H "Content-Type: application/json" \
  -H "X-Api-Key: $YOUR_API_KEY" \
  -d '{
    "request_id": "gen-7f3a91",
    "platform": "uipath_maestro",
    "artifact": { "format": "bpmn", "content": "<definitions>...</definitions>" },
    "prompt": "When an invoice arrives, extract the amount and vendor...",
    "callback_url": "https://your-service.example/webhooks/wfeval"
  }'
```

Returns **202** immediately:

```json
{ "evaluation_id": "ev_7f3a91cc", "status": "queued", "poll_url": "/v1/evaluations/ev_7f3a91cc" }
```

Get the result two ways — pick one or use both:

### Polling

```
GET /v1/evaluations/ev_7f3a91cc
```

Returns **202** with the same `EvaluationAccepted` shape while still
running, **200** with the full `EvaluationReport` (same shape as
`/v1/validate`'s response, but with `intent`/`execution` populated too)
once finished.

### Webhook (`callback_url`)

If you set `callback_url`, the Gateway `POST`s the final `EvaluationReport`
there once the pipeline finishes — no polling needed. The body is
HMAC-SHA256 signed:

```
X-Wfeval-Signature: sha256=<hex-encoded HMAC of the raw request body>
```

Verify it before trusting the payload (see `docs/examples/sample_client.py`
for a runnable receiver):

```python
import hashlib
import hmac

def verify(secret: str, body: bytes, header_value: str) -> bool:
    expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header_value)
```

`secret` here is whatever value the Gateway's operator configured via
`GATEWAY_WEBHOOK_SECRET` — get it from them out of band, it is never sent
in the request. Delivery retries up to 3 times on failure; if all three
fail, the result is still sitting at `poll_url` indefinitely, so treat the
webhook as a convenience, not the only path to the result.

### Idempotency

`request_id` is your idempotency key. Submitting the same `request_id`
twice to `POST /v1/evaluations` does **not** start a second pipeline run —
you get back the original `evaluation_id`, immediately, with no new work
done. Safe to retry a submission on a network timeout without worrying
about double-running an expensive evaluation.

## Auth

If the Gateway's operator has configured API keys, every endpoint except
`GET /healthz` requires:

```
X-Api-Key: <your key>
```

A missing or wrong key gets a **401**. Get your key from whoever operates
the Gateway — it isn't self-service.

## Errors

| Status | Meaning | What to do |
|---|---|---|
| 200 / 202 | Normal — check `verdict`/`gates` for the actual result | — |
| 401 | Missing/invalid `X-Api-Key` | Check your key |
| 404 | Unknown `evaluation_id` | Check the id, or it may have rolled off (see runbook) |
| 422 | Your request body failed schema validation | Fix the body against `contracts/gateway.openapi.yaml` |
| 502 | A downstream service (Validation/Intent/Sandbox/Cost) was unreachable | Not your fault — retry with backoff. This is a Gateway-side outage, not a problem with your artifact |

`platform` currently only really supports `uipath_maestro`. `n8n` is
accepted in the schema (won't 422) but deferred — full behavior isn't there
yet.

## Timeouts to plan around

- `POST /v1/validate`: sub-2s in practice, no hard client-side timeout
  needed beyond ordinary HTTP defaults.
- `POST /v1/evaluations`: the pipeline itself has no fixed deadline — it's
  gated by Sandbox execution, which can genuinely take minutes for a
  complex artifact. Don't set an aggressive client timeout on the *poll*
  calls; each individual poll is fast, you're just polling repeatedly until
  the status flips from 202 to 200.
- Each Gateway→downstream-service HTTP call has a 30-second internal
  timeout; a 502 after that long means a real outage, not a slow artifact.

## Sample client

`docs/examples/sample_client.py` is a small, runnable script covering both
endpoints plus a webhook receiver with signature verification. Read it
before writing your own integration — it's shorter than this document.
