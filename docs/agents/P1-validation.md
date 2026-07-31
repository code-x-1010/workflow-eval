# P1 — Validation Service + Gateway + Shared Core

> Read `AGENTS.md` first. Then `docs/handoff/P1.md` — that is your memory from previous sessions.

You own the structural truth of the layer and the front door the generation team integrates against. You are also the custodian of `wfeval-core`, which means **three other agents are blocked on you in week 1.** Treat the Day 2 type freeze as your single most important commitment.

---

## Ownership

**You may edit**

```
packages/wfeval-core/**          # shared types — everyone depends on this
packages/wfeval-adapters/**      # BPMN/DMN -> canonical AST
services/validation/**           # :8001
services/gateway/**              # :8000  (except weights.yaml/score.py/render.py — P4)
.github/**  Makefile  pyproject.toml  .importlinter  CODEOWNERS
```

**You must never edit**

```
services/intent/**    services/sandbox/**    services/cost/**
```

---

## Your contracts

### Validation — `:8001`, sync, no LLM, sub-second

```
POST /v1/validate
  { request_id, platform, artifact{format,content}, prompt?, options{tiers[]} }
  -> ValidationReport   (packages/wfeval-core/src/wfeval/core/report.py)

GET  /v1/diagnostics/codes   -> the public code registry
GET  /healthz
```

### Gateway — `:8000`, async

```
POST /v1/evaluations   -> 202 { evaluation_id, poll_url }
GET  /v1/evaluations/{id} -> EvaluationReport
```

Orchestration, **with short-circuit**:

```
1. Validation /v1/validate                        (sync, ~500ms)
   any gate false -> verdict=fail, SKIP 2-4, set short_circuited_at="validation"
2. parallel:  Intent /v1/intent + /v1/testcases  |  Cost /v1/cost  |  Sandbox /v1/deploy
   deploy rejected -> verdict=fail, SKIP 3, set short_circuited_at="deploy"
3. Sandbox /v1/executions   (consumes step 2's test cases)   <- minutes, the long pole
4. P4's score() + render(), deliver via callback
```

The short-circuit is not an optimisation, it is the difference between a corpus run taking an hour and taking a day. Build it into `orchestrate.py` from the start, not as a later pass.

---

## What you consume

| From | What | Where to get it before it exists |
|---|---|---|
| P3 | `GET /v1/assets` — deployed asset registry for L2 reference checks | `contracts/examples/assets.response.json` |
| P2 | `IntentReport` | `contracts/examples/intent.response.json` |
| P3 | `ExecutionReport` | `contracts/examples/execution.response.json` |
| P4 | `CostReport`, `score()`, `render()` | `contracts/examples/cost.response.json` |

**Never hard-depend on P3 being up.** Sandbox is the riskiest service in the project. If `GET /v1/assets` is unreachable, L2 reference checks must record `tiers_skipped["L2"] = "asset registry unavailable"` and the artifact proceeds. A validation service that goes down when the sandbox goes down is a validation service nobody can rely on.

## What others consume from you

| Who | What | Your obligation |
|---|---|---|
| **Everyone** | `packages/wfeval-core` | **Frozen D2 EOD.** Non-negotiable. |
| **Everyone** | `packages/wfeval-adapters` — `parse()` -> `WorkflowAST` | Working on the shared fixture by D3 |
| P4 | `contracts/examples/validation.response.json` | Committed by **D2** |
| Generation team | Gateway API + integration guide | D10 |

---

## The validation ladder

| Tier | Check | Latency |
|---|---|---|
| **L1** Schema | XML well-formedness, BPMN 2.0 XSD, DMN 1.3 XSD, UiPath extension attributes | ~50ms |
| **L2** References | Every task's `asset_ref` resolves against P3's registry; referenced decisions exist; variables declared before use | ~200ms |
| **L3** Structure | Exactly one reachable start event; every element reachable; every path reaches an end event; gateway split/join balance; no mixed inclusive/exclusive join; valid ISO-8601 timers | ~100ms |
| **L4** Soundness + dataflow | BPMN -> workflow net -> WOFLAN (option to complete, proper completion, no dead transitions). Every referenced variable assigned on **all** incoming paths. DMN gap + overlap. | ~1s |

Short-circuit inside the ladder too: don't run L4 if L1 failed. The results are meaningless and the runtime isn't free.

---

## Deliverables

### Week 1

| Day | Deliverable | Done when |
|---|---|---|
| D1 | Repo scaffold, uv workspace, Compose, CI green | `make lint test` passes on an empty repo |
| **D2** | **`wfeval-core` frozen. All 5 OpenAPI specs drafted in `contracts/`.** | Types merged; specs circulated; you have told the other three in standup |
| D2 | `contracts/examples/validation.response.json` committed | P4 can build Gateway aggregation against it |
| D2 | Spec negotiation opened with the generation team | ADR started in `docs/decisions/` |
| D2 | UiPath adapter: BPMN/DMN -> `WorkflowAST`, XPath locators preserved | `artifact.bpmn` parses; every element has a `locator` |
| **D3** | **Gateway skeleton: fan-out + short-circuit, calling stubbed services** | `make contract` green; `POST /v1/evaluations` returns a valid `EvaluationReport` built from golden examples |
| D4–D5 | L1 (XSD) + L3 (structure) | ≥1 broken-BPMN fixture per `SCH-*` and `STR-*` code, all passing |

**Week 1 exit:** `POST /v1/evaluations` returns a real structural report for a real BPMN file.

### Week 2

| Day | Deliverable | Done when |
|---|---|---|
| D6–D7 | L4 soundness — BPMN -> workflow net -> WOFLAN -> `FLW-*` | Ships at `warning` severity. Fixtures for deadlock and dead-transition. |
| D7 | L4 dataflow — `lark` grammar, variable extraction, assigned-on-all-paths via dominators | Fixture where a variable is assigned on one branch only |
| D8 | L2 references against P3's registry, degrading gracefully | Kill the sandbox container; validation still returns 200 with `tiers_skipped` |
| D8 | DMN gap + overlap analysis | Fixtures for `DMN-INPUT-GAP` and `DMN-RULE-OVERLAP` |
| D9 | Gateway hardening: async queue, webhook retry + HMAC, idempotency on `request_id`, API-key auth | Replaying the same `request_id` returns the cached report, not a second run |
| D9 | `.importlinter` rule enforcing P2's testgen isolation | CI fails if `services/intent/src/testgen/**` imports `wfeval.core.ast` |
| D10 | Handoff: OpenAPI bundle, `docs/integration-guide.md`, sample client, runbook | Someone outside the team can integrate from the docs alone |

**Week 2 exit:** full static ladder complete; generation team can integrate against a documented async API.

---

## Traps specific to your service

**Freezing types late is the project's biggest self-inflicted risk.** Three agents cannot start until `wfeval-core` is stable. If D2 is slipping, ship a smaller frozen core and add optional fields later — optional additions are backward-compatible, renames are not.

**L4 soundness ships at `warning`, not `error`.** BPMN-to-workflow-net conversion loses fidelity in ways that produce false positives. Promote to `error` only after fixtures validate it. An unvalidated analyser that hard-fails artifacts will destroy the generation team's trust in the entire layer within a week, and you don't get it back.

**L4 dataflow is where LLM output fails most often**, and it's the tier most implementations skip. An expression referencing a variable is only valid if that variable is assigned on *every* incoming path — not just some path. Use dominators, not naive reachability.

**Preserve locators from the very first parse.** Retrofitting XPath locators after the fact is miserable, and without them your diagnostics say "something is wrong somewhere", which is useless to a repair loop.

**You own the Gateway but P4 owns scoring.** Do not implement `score()`. Call it. If P4's scoring isn't ready, call the stub.
