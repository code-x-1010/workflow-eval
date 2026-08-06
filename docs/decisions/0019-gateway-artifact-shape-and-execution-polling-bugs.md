# 0019 — Two real bugs found writing D10's sample client against live services

**Author:** P1   **Date:** 2026-08-06   **Status:** accepted   **Affects:** P1, P3 (awareness only — contract already correct)

## Context

D10 ("someone outside the team can integrate from the docs alone") asks for
more than documentation — the only way to trust that claim is to actually
run the sample client against real, live services rather than the
mocked-HTTP-layer unit tests every other session relied on. Doing that for
the first time surfaced two real bugs, both entirely within P1's own
`services/gateway/**` — not P3's.

### Bug 1: `_artifact_body` read the wrong request shape

`orchestrate.py`'s `_artifact_body()` read `request["content"]` and
`request.get("format")` as flat top-level fields. `contracts/gateway.openapi.yaml`'s
`ArtifactSubmission` schema — unchanged, always correct — defines a nested
`artifact: {format, content}` object. Every request built from the actual
contract (the sample client, any real integrator) got a `KeyError` ->
500. `tests/unit/gateway/`'s own `REQUEST` fixtures used the same flat,
wrong shape as the implementation, so the mismatch was invisible to every
existing test — bug and test agreed with each other, just not with the
contract either was supposed to satisfy.

### Bug 2: Sandbox execution results were never actually fetched

`contracts/sandbox.openapi.yaml` documents `POST /v1/executions` as
202-shaped: it returns `{execution_id, poll_url}`, and the real
`ExecutionReport` lives behind `GET /v1/executions/{execution_id}`.
`orchestrate.py`'s stage 3 was parsing the POST response itself as an
`ExecutionReport`, which doesn't have the required fields (`runner`,
`fidelity`, etc.) — a `pydantic.ValidationError` on the very first real
`/v1/evaluations` call. P3's Sandbox was doing exactly what its own contract
says; nothing there needed to change.

Both were invisible to `tests/unit/gateway/test_orchestrate.py` because its
mocked routes returned `golden("execution.response.json")` — the real
report shape — directly from the POST route, for convenience, without
distinguishing "what the POST actually returns" from "what the eventual GET
returns." The mock was more correct than the code it was standing in for.

## Decision

- Fixed `_artifact_body` to read the nested shape.
- Fixed stage 3 to `POST` then `GET` the execution result, matching
  Sandbox's contract. Added an explanatory comment at the call site (not
  just here) since this is exactly the kind of thing a future session could
  silently regress again without an obvious signal.
- Added `ALL_GATES_OK_ROUTES["http://sandbox:8003/v1/executions/ex_test"]`
  as a second mock route distinct from the POST route, and a direct
  regression test for `_artifact_body`.

## Consequences

- `POST /v1/validate` and `POST /v1/evaluations` now actually work against
  real services for the first time — verified live in this session (all 5
  services running, real HTTP, HMAC-signed webhook delivered and verified,
  polling verified). Not just unit-tested; run for real.
- P3: no action needed. Your contract was right; flagging this so you know
  the Gateway integration was silently broken until today, not currently
  broken by anything on your side.
- General lesson, not a new rule: mocking the HTTP *transport* (as this
  codebase's convention already does, correctly, per `test_orchestrate.py`'s
  own module docstring) still isn't the same as verifying against a live
  peer. Worth someone occasionally actually running `make dev-real`.

## Sign-off

- [x] P1
- [ ] P3 — awareness only, no action needed
