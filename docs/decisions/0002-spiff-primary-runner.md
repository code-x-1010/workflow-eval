# 0002 — Spiff as the primary Sandbox runner; UiPath deferred

**Author:** P3   **Date:** 2026-07-30   **Status:** accepted   **Affects:** P1, P3, P4

## Context
The original plan made P3's Day 1-2 UiPath sandbox tenant access spike the single
most schedule-critical task in the project, with a SpiffWorkflow fallback agreed
only as a contingency if access wasn't confirmed by Day 3. There is no UiPath
tenant available at all. Waiting on one is not a schedule risk to manage, it's a
blocker with no date.

## Decision
Spiff (`SpiffWorkflow`, already an optional dependency) becomes the **primary**
runner, not a fallback. `services/sandbox/src/runners/spiff/` is real,
verified-by-hand-against-the-actual-library code: BPMN parsing, a resolution
loop that drives every automated task via `TaskStub` (see `0003`) and every
manual task via `human_task_outcomes`, task-tree trace extraction filtered to
real BPMN element ids, and a `timeout_s`-bounded loop that never hangs.
`services/sandbox/src/runners/uipath/` keeps the same `Runner` interface
implemented but every method raises `NotImplementedError` — it is deferred, not
deleted, and the interface is stable so dropping in a real implementation later
is a config change, not a rewrite.

L5 platform acceptance ("does this artifact actually deploy to and run on
Maestro") is the one thing Spiff cannot substitute for — it never talks to
Maestro. `POST /v1/deploy` becomes a pass-through: `accepted: true` plus a new
`PLT-DEPLOY-DEFERRED` (info) diagnostic saying so explicitly, so nobody mistakes
"we didn't check" for "we checked and it's fine."

This also clarifies something the sync/async gate split already implied:
Sandbox's deploy/execute pipeline lives entirely inside the Gateway's async
`/v1/evaluations` (quality signal, regression tracking), never the sync
`/v1/validate` blocking gate. And Sandbox's own deploy — real tenant or Spiff —
targets our own sandbox, never the generation team's production Maestro. They
deploy to production separately, after the sync gate clears.

## Consequences
- P3 is unblocked from Day 1 instead of gated on a Day 2 access spike. The
  schedule-critical-path framing in the original charter no longer applies.
- `ExecutionReport`/`Trace` gain `runner`/`fidelity` fields (see `0004`) so
  every downstream consumer knows a result came from a substitute engine, not
  the real platform.
- `contracts/examples/execution.response.json` is updated to reflect
  `runner: "spiff"`, `fidelity: "reduced"`.
- The shared `contracts/examples/artifact.bpmn` does not execute on Spiff as
  committed (`Gateway_amount` has no default flow / condition — the planted
  defect behind `STR-UNREACHABLE-TASK`). This is correct behavior, not a bug:
  in the real pipeline Sandbox only sees gate-cleared artifacts. Engine tests
  use a separate, executable fixture: `tests/fixtures/spiff/executable_invoice.bpmn`.
- `sandbox-infra/` (WireMock, `.env.example`, OAuth2 module plans) is retained
  for the day a UiPath tenant exists, but is off the critical path.
- P1: `/v1/deploy`'s new `PLT-DEPLOY-DEFERRED` code needs no action from you —
  it's under P3's own `PLT` prefix. Flagging only because `platform_acceptance`
  as a gate now always reads `true` until a real tenant exists; don't let
  anyone read that as a production-deploy confirmation.
- P4: calibration priors trained on Spiff traces are calibrating against a
  substitute engine. `Actuals` (tokens, turns, durations) are still real where
  `TaskStub` outputs carry them, but `robot_minutes`/`human_minutes` have no
  meaning without a real RPA/orchestrator layer — expect `null` there until
  `runners/uipath/` exists.

## Sign-off
- [x] P3
- [ ] P1 — no action required; flagged for awareness (platform_acceptance semantics)
- [ ] P4 — no action required; flagged for awareness (Actuals provenance under Spiff)
