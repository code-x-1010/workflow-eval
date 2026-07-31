# workflow-eval

A quality layer for LLM-generated workflows. Sits downstream of a workflow generator (owned by another team) and answers four questions about every artifact it produces:

| Question | Service | Port | Owner |
|---|---|---|---|
| Will it load and run on the platform? | **Validation** | `:8001` | P1 |
| Does it match what the user asked for, and what would prove it? | **Intent & Test Generation** | `:8002` | P2 |
| Does it behave correctly when actually run? | **Sandbox Execution** | `:8003` | P3 |
| What will it cost per run? | **Cost** | `:8004` | P4 |

A thin **Gateway** (`:8000`) fans out to all four, short-circuits on failure, and returns one scored report. The generation team integrates against a single endpoint, or calls individual services directly.

**Primary platform:** UiPath Maestro (BPMN 2.0 + DMN). n8n deferred to v1.1.

---

## If you are a coding agent

**Read [`AGENTS.md`](AGENTS.md) first.** Then your charter in `docs/agents/`, then your own handoff log in `docs/handoff/`.

Four engineers each run their own agent in a separate session. The agents can't see each other and don't share memory. Everything below exists to make that work.

---

## How four isolated agents collaborate

There are exactly four coordination mechanisms, all of them files, all enforced by CI.

**1. Frozen contracts.** `packages/wfeval-core/` (shared types) and `contracts/*.openapi.yaml` (service interfaces) are frozen after Day 2. They are the only things all four agents share. An agent that needs a change writes a decision record and stops — it does not edit.

**2. Golden examples.** `contracts/examples/` holds realistic, contract-valid payloads for every service boundary, committed by Day 2. This is what stops anyone waiting: P3 builds their entire execution loop against P2's example test cases on Day 3, six days before P2's generator works. Every service runs with `WFEVAL_STUB_DEPS=1` and serves these instead of calling dependencies.

The examples compose into one coherent story — the same invoice-approval workflow flows through all of them, using the same element ids from `contracts/examples/artifact.bpmn`.

**3. Decision records.** `docs/decisions/` — the only channel for anything affecting a shared contract or another agent. Numbered, append-only, human-mediated.

**4. Handoff logs.** `docs/handoff/P<N>.md` — an agent session ends and everything it learned evaporates. These files are its memory across sessions, and the humans' view at standup.

### Enforced mechanically

```bash
make check-ownership      # AGENT=P2 make check-ownership — did you stay in your lane?
make lint                 # includes import-linter: the anti-circularity guarantee
make contract             # every service satisfies its OpenAPI spec — green from D3
```

`scripts/check_ownership.py` fails if you edited files belonging to an agent who can't see your session. `CODEOWNERS` enforces the same at review.

---

## The Day 3 stub milestone

By end of Day 3, **every service returns contract-valid responses**, even if every value is hardcoded. The Gateway fan-out works end to end on fake data.

This is the most important date in the schedule. With four independently built services, integration failure discovered in week 2 is fatal. Prove the wiring first; spend the remaining seven days on real logic behind stable interfaces.

`make contract` must be green from Day 3 onward. If it goes red, that's a stop-work event for whoever broke it.

---

## Two rules that are load-bearing

**Test cases derive from the prompt alone — never from the generated workflow.** If testgen reads the artifact, it produces tests the artifact passes and the whole execution tier becomes a tautology. Enforced three ways: `POST /v1/testcases` has no `artifact` field, `.importlinter` blocks `intent.testgen` from importing the AST, and `tests/contract/test_anti_circularity.py` asserts both are still in place.

**Only the Sandbox service holds UiPath credentials.** The other three are pure functions over `(prompt, artifact)` and can run anywhere, including the generation team's own CI.

---

## Quick start

```bash
uv sync --all-extras
make dev            # all 5 services, dependencies stubbed — always works
curl localhost:8000/healthz

make dev-real       # real inter-service calls — expect breakage before D8
```

---

## Layout

```
AGENTS.md                  protocol every agent reads first
CODEOWNERS  .importlinter  ownership + import boundaries, enforced in CI

packages/
  wfeval-core/             FROZEN D2 — shared types, imports nothing
  wfeval-adapters/         BPMN/DMN -> canonical AST

services/
  validation/  :8001  P1   L1-L4 static ladder
  intent/      :8002  P2   spec extraction, alignment, test generation
  sandbox/     :8003  P3   deploy + execute; the only UiPath credentials
  cost/        :8004  P4   static cost analysis
  gateway/     :8000  P1   fan-out, short-circuit, aggregate (score.py/render.py: P4)

contracts/
  *.openapi.yaml           FROZEN D2
  examples/                golden payloads — how agents build against each other

docs/
  agents/                  one charter per engineer
  decisions/               cross-agent channel
  handoff/                 per-agent memory across sessions

datasets/corpus/           eval corpus (P2)
tests/contract/            the guarantees that must not regress
```

---

## Scoring

```
overall = 0 if any gate fails, else
    0.35 * structural_soundness  +  0.35 * intent_coverage  +  0.30 * execution_pass_rate
```

Gates (binary): `schema_validity`, `reference_integrity`, `platform_acceptance`.

**Cost is deliberately not in `overall`** — a cheap wrong workflow isn't better than an expensive correct one, and mixing them makes both numbers uninterpretable. Cost gates only when the prompt states a budget.

An unimplemented tier scores `null`, never a default that looks like a measurement.

---

## House rules

- Diagnostic codes are append-only and prefix-owned. You may only emit codes under your prefixes (`PREFIX_OWNER` in `diagnostics.py`).
- Every diagnostic carries a `suggested_fix` phrased as an imperative the generator can act on.
- Never ship a number without its confidence — cost estimates, intent scores, soundness results alike.
- New analysers ship at `warning` severity first. A false-positive hard-fail destroys the generation team's trust in the whole layer, and you don't get it back.
