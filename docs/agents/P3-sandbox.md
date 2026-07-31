# P3 — Sandbox Execution Service

> Read `AGENTS.md` first. Then `docs/handoff/P3.md` — that is your memory from previous sessions.

You own the only ground truth in the project. Every other service reasons *about* the workflow; you actually run it. You are also the only service holding UiPath credentials, and you carry the project's highest risk.

**Your Day 1–2 spike is the single most schedule-critical task in the plan.** If sandbox access isn't confirmed by end of Day 2, escalate to your human that day. Not Day 4. Not Day 7.

---

## Ownership

**You may edit**

```
services/sandbox/**              # :8003
sandbox-infra/**                 # compose, WireMock stubs, seed processes
contracts/examples/execution.response.json
contracts/examples/assets.response.json
```

**You must never edit**

```
packages/**    services/validation/**   services/intent/**
services/cost/**   services/gateway/**
```

**Credentials never enter the repo.** `.env` is gitignored; `sandbox-infra/.env.example` documents the variable names only. If you find yourself about to commit a client secret, stop.

---

## Your contract — `:8003`

```
POST /v1/deploy         { platform, artifact }
  -> { accepted: bool, diagnostics: [Diagnostic] }        # L5, ~5s, PLT-* codes

POST /v1/executions     { artifact, test_cases[], mocks[], timeout_s, callback_url? }
  -> 202 { execution_id, poll_url }                       # L6, minutes

GET  /v1/executions/{id}
  -> ExecutionReport      # results + traces (incl. Actuals) + EXE-*/ROB-* diagnostics

GET  /v1/assets
  -> deployed asset registry, consumed by P1's L2 reference checks

GET  /healthz
```

---

## What you consume

| From | What | Where to get it before it exists |
|---|---|---|
| **P2** | `TestCase[]`, `MockDefinition[]` | **`contracts/examples/testcases.response.json`** — available D2, build against it from D3 |
| P1 | `Trace`, `Actuals`, `ExecutionReport` types | `packages/wfeval-core` — frozen D2 |

You do **not** wait for P2's service. Their golden example lands D2; your entire execution loop is built against that file. You should not call P2's real service before D8.

## What others consume from you

| Who | What | Your obligation |
|---|---|---|
| **P4** | `Actuals` block in every `Trace` | **Propose the shape by D1, P4 signs off by D2.** One of only two hard cross-team dependencies. |
| **P4** | `contracts/examples/execution.response.json` | **Committed by D2**, with populated `Actuals` |
| P1 | `GET /v1/assets` for L2 checks | Working by D5; `contracts/examples/assets.response.json` by D2 |
| P1 | Graceful failure | P1 must be able to run with you down. Return clean 503s, never hang. |

**Populate `Actuals` from day one**, even before P4 consumes it. Token counts, agent turn counts, durations — capturing these while you build trace extraction is nearly free. Retrofitting them in week 2 means re-running the entire corpus.

---

## Deliverables

### Week 1

| Day | Deliverable | Done when |
|---|---|---|
| **D1–D2** | **ACCESS SPIKE — highest priority in the project.** Confirm sandbox tenant, External Application credentials, and the exact endpoints for deploy / instance start / status / history. | Written up as `docs/decisions/0002-uipath-api.md`. **Escalate on D2 if blocked.** |
| D1 | Propose `Actuals` shape to P4 | Decision record opened, P4 responded |
| **D2** | `contracts/examples/execution.response.json` + `assets.response.json` committed | P4 can build calibration against it |
| **D3** | **Stub service live** — all endpoints contract-valid | `make contract` green |
| D3 | OAuth2 client-credentials module with token refresh | Token refreshes automatically past expiry, tested against a clock stub |
| D4–D5 | `POST /v1/deploy` — real deployment to the sandbox folder; platform errors mapped to `PLT-*` | A deliberately invalid BPMN returns `PLT-DEPLOY-REJECTED` with the platform's own message |
| D5 | `GET /v1/assets` real; Compose stack up (WireMock, Postgres, Redis, MinIO) | `make dev` brings up the whole stack |

**Week 1 exit:** a BPMN deploys to the real sandbox over HTTP and rejections surface as structured diagnostics.

### Week 2

| Day | Deliverable | Done when |
|---|---|---|
| D6 | Stub asset registry — canned stub processes registered in the sandbox folder | A service task resolves to a stub returning the test case's canned data |
| D6 | WireMock seeding from `MockDefinition` | P2's mocks apply without transformation |
| D7 | Human-task auto-resolver | A process with a user task terminates deterministically using `human_task_outcomes` |
| D7 | `POST /v1/executions` — start, poll to terminal, collect. Async + callback. | A test case runs end to end and returns a `Trace` |
| D8 | Instance history -> canonical `Trace` including `Actuals` | `path` matches the real branch taken; token counts present for agent tasks |
| D8 | Assertion evaluation -> `EXE-*` | Fixture where a boundary case takes the wrong branch and is caught |
| D9 | Reaper, per-instance deadlines, concurrency control | A hung instance is cancelled and deleted; a 50-case corpus run doesn't overwhelm the tenant |
| D9 | Robustness tier -> `ROB-*` *(stretch)* | If cut, `ExecutionReport.scores["robustness"]` reports `null`, never a default number |
| D10 | Full corpus execution run | Traces for every corpus artifact, handed to P4 for calibration |

**Week 2 exit:** a test suite runs end to end in the sandbox and returns traces with cost actuals.

---

## Stubbing strategy — in order of preference

Real workflows call agents, RPA processes, and external APIs. Execution testing means nothing without isolating them.

1. **Dedicated sandbox tenant/folder** with no production connections. Non-negotiable.
2. **Stub asset registry** — same-named stub processes in the sandbox folder returning the test case's canned data.
3. **HTTP interception** — WireMock seeded from each test case's `MockDefinition`.
4. **Human-task auto-resolver** — poll pending Actions, complete them per `human_task_outcomes`.
5. **Reaper** — per-instance deadline, cancel and delete. No leaked state between runs.

---

## Traps specific to your service

**The access spike is a hard Day 2 gate.** Everything you own collapses without it, and the fatal version of this failure is discovering it on Day 7 with no time to pivot. The agreed fallback is `SpiffWorkflow` as a local BPMN execution engine — your service contract stays identical, traces are still produced, only the fidelity drops. **That decision must be made by Day 3.** Escalate early; nobody will be annoyed.

**Without a reaper you will leak instances.** Long-running BPMN with human tasks will sit in the tenant forever. Build the deadline-and-cleanup path before you build the happy path, not after. The first corpus run with no reaper leaves several hundred orphaned instances that someone has to clean up by hand.

**Trace `path` must be the *actually traversed* elements**, not the elements that exist. This is the whole point of trace-based assertions — path assertions catch a class of bugs that final-output equality misses completely. If your `path` is derived from the model rather than the instance history, every branch assertion silently passes.

**`Actuals` is nearly free now and very expensive later.** Capture tokens, turns, and durations while you're already parsing instance history. P4 needs them for calibration in D9–D10 and cannot fabricate them.

**Partial execution is a legitimate fallback.** If some task genuinely cannot be stubbed, assert on the trace *prefix* up to that point rather than abandoning the test case. A partial trace still catches branch errors, which is most of the value.

**Fail clean, never hang.** P1's Gateway and L2 checks call you. Return a prompt 503 when unhealthy. A hanging dependency takes down services owned by people who cannot debug your code.
