# P3 — Sandbox Execution Service

> Read `AGENTS.md` first. Then `docs/handoff/P3.md` — that is your memory from previous sessions.

You own the only ground truth in the project. Every other service reasons *about*
the workflow; you actually run it.

**Spiff is the primary runner. We have no UiPath tenant.** The original plan
assumed sandbox tenant access would be confirmed by Day 2; that assumption
changed. `runners/spiff/` runs artifacts locally with SpiffWorkflow: free, in
process, seconds, CI-friendly, no consumption units, no credentials, no
external dependency at all. `runners/uipath/` is a **deferred stub** — kept in
the same shape so it can be dropped in the day a tenant exists, but every
method raises for now. See `docs/decisions/0002-spiff-primary-runner.md`.

This means you are no longer the credential-holding, tenant-blocked,
schedule-risk service the original plan described. You are unblocked from Day
1. The one thing that changes: **L5 platform acceptance — "does this actually
deploy to and run on Maestro" — is deferred, not deleted.** Spiff cannot
substitute for it: it never talks to Maestro, so it has no way to know whether
Maestro would accept the artifact. `/v1/deploy` is a pass-through no-op
(`accepted: true` + an info diagnostic saying so) until `runners/uipath/`
stops raising.

---

## Ownership

**You may edit**

```
services/sandbox/**              # :8003, including runners/spiff/ and runners/uipath/
sandbox-infra/**                 # compose, WireMock stubs, seed processes (uipath path)
tests/unit/sandbox/**             # your unit tests
tests/fixtures/spiff/**           # executable BPMN fixtures for engine tests —
                                  # NOT the same thing as contracts/examples/artifact.bpmn,
                                  # see the trap below
contracts/examples/execution.response.json
contracts/examples/assets.response.json
```

**You must never edit**

```
packages/**    services/validation/**   services/intent/**
services/cost/**   services/gateway/**
```

`TaskStub` (testcase.py), `RunnerFidelity`/`Trace.runner`/`Trace.fidelity`
(trace.py), and `ExecutionReport.runner`/`.fidelity`/`.confidence` (report.py)
are all in `packages/wfeval-core`, which you don't own. Changes there went
through `docs/decisions/0003` and `0004` — propose further changes the same
way, don't edit directly.

**Credentials never enter the repo.** This matters less now that Spiff needs
none, but the rule doesn't change: `.env` is gitignored; `sandbox-infra/.env.example`
documents variable names only, for the day `runners/uipath/` needs them again.

---

## Your contract — `:8003`

```
POST /v1/deploy         { platform, artifact }
  -> { accepted: bool, diagnostics: [Diagnostic] }
  DEFERRED pass-through: always accepted=true + PLT-DEPLOY-DEFERRED (info) until
  runners/uipath/ has a real tenant. Never blocks on this — see the gate-split
  note below.

POST /v1/executions     { artifact, test_cases[], mocks[], timeout_s, callback_url? }
  -> 202 { execution_id, poll_url }
  Spiff runs synchronously under the hood (it's seconds, not minutes) but the
  contract stays 202-shaped for parity with the eventual UiPath runner.

GET  /v1/executions/{id}
  -> ExecutionReport      # results + traces (incl. Actuals) + EXE-*/PLT-* diagnostics
                          # + runner/fidelity/confidence (see below)

GET  /v1/assets
  -> deployed asset registry, consumed by P1's L2 reference checks. Spiff has
     no orchestrator asset-folder concept; this stays a golden stub.

GET  /healthz
```

### This is not the blocking gate

The generation team's blocking pre-deployment check is the Gateway's sync
`POST /v1/validate` — L1-L4 (Validation) + cost, sub-2s, never touches you.
Your `/v1/deploy` and `/v1/executions` live entirely inside the Gateway's
*async* `/v1/evaluations` — a quality signal for generator improvement and
regression tracking, not a per-artifact block. And even inside that async
pipeline: **your sandbox deploy targets your own sandbox tenant (or, today,
nothing at all — Spiff doesn't deploy anywhere). It is not the production
Maestro deploy.** The generation team deploys to production separately, after
the sync gate clears; they do not wait on you to do it. See
`docs/decisions/0002-spiff-primary-runner.md`.

---

## What you consume

| From | What | Where to get it before it exists |
|---|---|---|
| **P2** | `TestCase[]` (incl. `task_stubs`), `MockDefinition[]` | **`contracts/examples/testcases.response.json`** |
| P1 | `Trace`, `Actuals`, `ExecutionReport` types | `packages/wfeval-core` |
| P1 | `WorkflowAST` (optional) for `asset_ref` resolution | `wfeval.adapters.parse()` — **may not exist yet; degrade gracefully, see traps** |

You do **not** wait for P2's service. Their golden example is what you build
against.

## What others consume from you

| Who | What | Your obligation |
|---|---|---|
| **P4** | `Actuals` block in every `Trace` | Populate from day one, even placeholder-null where a real value genuinely isn't known yet |
| **P4** | `contracts/examples/execution.response.json` | Kept current, now with `runner`/`fidelity` |
| P1 | `GET /v1/assets` for L2 checks | Golden stub is enough for now; P1 must be able to run with you down regardless |
| P1 | Graceful failure | Return clean 503s, never hang. The engine's own timeout_s / stalled-task detection is the local version of this — see below. |

---

## TaskStub — how Spiff resolves a task without a network call

A bare `<serviceTask>`/`<userTask>` with no embedded script (which is exactly
what UiPath-generated BPMN looks like to Spiff — the real activity is
described via extension attributes Spiff doesn't understand) never
auto-completes. Every automated task needs an explicit resolution step.
`TestCase.task_stubs: list[TaskStub]` (in `wfeval-core/testcase.py`, see
`docs/decisions/0003-taskstub-contract.md`) is P2's answer: `element_id` or
`asset_ref` → a queue of output dicts, one per invocation (so a loop calling
the same task twice gets two different outputs). `MockDefinition` is
unrelated — Spiff never makes a real outbound HTTP call, so it simply ignores
the `mocks` list; that field only matters to the (deferred) UiPath runner,
where a deployed process really would hit the network and WireMock needs to
intercept it.

`element_id` is always resolvable (Spiff's own BPMN parser gives you element
ids directly). `asset_ref` is resolved by calling `wfeval.adapters.parse()` —
P1's package, which may not exist yet. **Degrade gracefully**: if the import
fails or parsing errors, asset_ref-keyed stubs are simply unavailable and
element_id-keyed ones carry the whole load. See `runners/spiff/asset_refs.py`.
Same philosophy as P1's own "L2 skipped when the asset registry is down" —
never hard-depend on another agent's package landing on schedule.

A reached task with **no** stub, no `human_task_outcomes` entry (for a
manual/user task), and no other way to resolve it is not a failure — it's
**`EXE-RUNNER-UNSUPPORTED`** (severity `info`), and the case status is
`skipped`, never `fail`. A runner limitation is not an artifact defect. See
`runners/spiff/engine.py`'s module docstring for the exact mechanics
(verified by hand against SpiffWorkflow 3.1).

---

## Deliverables

The original Week 1 plan (D1-D2 access spike, D3 OAuth, D4-D5 real deploy,
D6 stub registry + WireMock seeding, D7 executions, D8 instance history) was
built around a UiPath tenant landing on schedule. It didn't. This replaces it.

### Week 1

| Day | Deliverable | Done when |
|---|---|---|
| D1 | `runners/base.py` Runner interface; `runners/spiff/` engine harness; `runners/uipath/` deferred stub | `run_case()` executes a hand-written executable BPMN fixture end to end |
| D1 | Propose `TaskStub` shape to P2, `runner`/`fidelity` shape to P4 | Decision records `0003`, `0004` opened |
| **D2** | `contracts/examples/execution.response.json` (with `runner`/`fidelity`) + `assets.response.json` committed | P4 can build calibration against it |
| **D2** | Service-task/user-task handler registration: `TaskStubResolver`, human-task auto-resolver via `human_task_outcomes` | A test case with a loop resolves each invocation to a different stubbed output |
| **D3** | **Stub service live** — all endpoints contract-valid | `make contract` green |
| D3 | Task-tree trace extraction: `path` built from *actually completed* tasks only (Spiff's synthetic Start/End/join wrappers filtered out), never from the model | Fixture where a boundary case takes the wrong branch and is caught |
| D4 | `EXE-RUNNER-UNSUPPORTED` wired: unparseable artifact **and** stalled/unresolvable task both produce it, case marked `skipped` | Fixture for each of the two triggers |
| D4-D5 | `POST /v1/deploy` as a deferred pass-through (`PLT-DEPLOY-DEFERRED`, info) | Documented as deferred, not silently dropped |
| D5 | `GET /v1/assets` golden stub; Compose stack up (WireMock retained for the day UiPath needs it, Postgres, Redis) | `make dev` brings up the whole stack |

**Week 1 exit:** a BPMN executes for real, locally, in seconds, and rejections
of unresolvable constructs surface as `EXE-RUNNER-UNSUPPORTED`, not hangs or
false failures.

### Week 2

| Day | Deliverable | Done when |
|---|---|---|
| D6 | PATH assertion evaluation -> `EXE-WRONG-BRANCH` etc. (already partially live — see `runners/assertions.py`) | Fixture where a boundary case takes the wrong branch and is caught |
| D7 | OUTPUT / INVARIANT / BUDGET assertion evaluation | Expression evaluator over `final_variables`; until then these are unchecked, never silently passed |
| D7 | Per-instance deadline via `timeout_s` (already live in the engine loop) + concurrency control for a corpus run | A 50-case corpus run doesn't block on one hung case |
| D8 | Instance history -> canonical `Trace` including `Actuals` (already partially live) | Token counts present for agent tasks once `TaskStub` outputs carry them |
| D9 | `runners/uipath/`: the day a tenant exists — OAuth2 client-credentials, real `/v1/deploy`, real Action Center polling, WireMock seeding from `MockDefinition` | Runner swap is a config change, not a rewrite — the interface hasn't moved |
| D9 | Robustness tier -> `ROB-*` *(stretch)* | If cut, `ExecutionReport.scores["robustness"]` reports `null`, never a default number |
| D10 | Full corpus execution run on Spiff | Traces for every corpus artifact that parses; artifacts that don't are reported, not silently dropped |

**Week 2 exit:** a test suite runs end to end on Spiff and returns traces with
cost actuals; the UiPath path is ready to receive credentials the day they exist.

---

## Stubbing strategy — in order of preference (updated)

1. **Spiff, in-process.** No tenant, no folder, no credentials. This is not a
   fallback — it is the primary path.
2. **`TaskStub`** — canned per-invocation output for any agent/service task,
   keyed by element_id or asset_ref. Replaces "dedicated stub asset registry"
   as the main resolution mechanism.
3. **Human-task auto-resolver** — `human_task_outcomes`, unchanged from the
   original plan; Spiff manual tasks stop at `TaskState.READY` the same way a
   real Action Center task would wait.
4. **`EXE-RUNNER-UNSUPPORTED` + skip** — the fallback of last resort when
   nothing above resolves a reached task. Never hang, never fabricate a
   pass or fail.
5. **WireMock / reaper / OAuth2** — retained in `sandbox-infra/` and
   `runners/uipath/` for the day a real tenant exists, but off the critical
   path.

---

## Traps specific to your service

**The shared `contracts/examples/artifact.bpmn` does not execute on Spiff as
committed — verified by hand.** `Gateway_amount`'s outgoing flows have neither
a `default` marking nor a `conditionExpression`. This is not a bug in Spiff:
it's the planted defect behind `validation.response.json`'s
`STR-UNREACHABLE-TASK` diagnostic, and any compliant BPMN engine would reject
it too. In the real pipeline this never matters — Sandbox only ever receives
artifacts that already cleared the sync L1-L4 gate, which catches exactly
this. For engine tests, use `tests/fixtures/spiff/executable_invoice.bpmn` (a
gate-cleared copy of the same story), not the shared fixture. Don't "fix" the
shared fixture yourself — it's deliberately broken for P1's demo.

**Data does not flow through `BpmnWorkflow.data`.** It flows task-to-task,
copied from a completed predecessor's `task.data` into its successor. Seed
test-case input on the START task before the first engine step, and always
`set_data(**everything_accumulated_so_far)` — not just the new output — before
`complete()`, or a downstream gateway condition silently evaluates against an
empty scope. Costly to get wrong and easy to miss because it fails silently
(`NameError` inside the script engine, not a clear "you forgot to seed this").

**`EXE-RUNNER-UNSUPPORTED` marks a case skipped, never failed.** A construct
Spiff can't run, or a task nothing resolves, is a statement about the runner,
not the artifact. Getting this backwards would fail artifacts for a Spiff
limitation they don't actually have on the real platform — exactly the kind
of false-negative that destroys trust in the whole layer (same principle as
L4 shipping at `warning` first).

**Your sandbox deploy is not the production deploy path**, with or without
Spiff. Even once `runners/uipath/` is real, an accept from your `/v1/deploy`
means "this artifact deployed to *our* sandbox folder," not "this is live in
the generation team's Maestro tenant." Don't let `/v1/evaluations`'s
`platform_acceptance` gate be read as a production deploy confirmation by
anyone downstream — say so in the report if you're not sure it's obvious.

**Trace `path` must be the *actually traversed* elements**, filtered to real
BPMN ids. Spiff wraps every process in synthetic Start/End/join tasks with
`task_spec.bpmn_id is None` — verified by hand. Leaving them in `path` doesn't
break assertions (they never match a real element id) but it's noise a future
session will waste time debugging; filter them at the source.

**Partial execution is a legitimate fallback.** If some task genuinely cannot
be stubbed, the engine already asserts on the trace *prefix* up to that point
(via `EXE-RUNNER-UNSUPPORTED` + `skipped`) rather than abandoning the test
case silently. A partial trace still catches branch errors, which is most of
the value.

**Fail clean, never hang.** `timeout_s` bounds every case; a stalled
(unresolvable) task is detected in one iteration, not by waiting for a
deadline. P1's Gateway and L2 checks call you — return a prompt result or a
clean failure, never a hang.
