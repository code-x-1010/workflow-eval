# P2 — Intent & Test Generation Service

> Read `AGENTS.md` first. Then `docs/handoff/P2.md` — that is your memory from previous sessions.

You own everything derived from the **user's prompt**. Two questions: *did the generator build what was asked for?* and *what would prove it works?*

You are also the guardian of the single most important correctness property in this project. See "The anti-circularity rule" below — read it before you write any code.

---

## Ownership

**You may edit**

```
services/intent/**               # :8002
datasets/corpus/**               # the eval corpus
datasets/golden/**
contracts/examples/testcases.response.json
contracts/examples/intent.response.json
```

**You must never edit**

```
packages/**    services/validation/**   services/sandbox/**
services/cost/**   services/gateway/**
```

---

## The anti-circularity rule

> **Test cases are derived from the prompt alone. Never from the generated workflow.**

If test generation reads the artifact, it will generate tests the artifact passes, and the whole execution tier becomes a tautology that reports 100% and means nothing.

This is enforced three ways, and you must not weaken any of them:

1. **`POST /v1/testcases` has no `artifact` field.** Do not add one. Not for "just peeking at the element ids", not for anything.
2. **`.importlinter` blocks `services/intent/src/testgen/**` from importing `wfeval.core.ast`** or any adapter. CI fails if you try.
3. **`Spec` is built from the prompt only.** `services/intent/src/extract.py` takes a string. Keep it that way.

Your `/v1/intent` endpoint *does* receive the artifact — that's alignment, a different job, and it lives in `align.py`, outside `testgen/`. Keep the two directories mentally separate. When you find yourself wanting element ids inside `testgen/`, that is the signal you've drifted: express the assertion semantically ("must traverse the approval branch") and let P3's trace matcher resolve it against real element ids at execution time.

---

## Your contract — `:8002`

```
POST /v1/spec        { prompt }
  -> { spec: Spec, sufficiency_diagnostics: [Diagnostic] }     # SPEC-* codes

POST /v1/intent      { prompt, spec?, artifact }
  -> IntentReport                                              # INT-* codes

POST /v1/testcases   { prompt, spec?, kinds[] }                # NO artifact field
  -> { test_cases: [TestCase], mocks: [MockDefinition] }

GET  /healthz
```

`spec` is optional everywhere. If supplied by the generation team, use it and additionally report **spec drift** — their intent versus yours. If absent, extract your own. This is deliberate: it removes the only external dependency from the project's critical path.

---

## What you consume

| From | What | Where to get it before it exists |
|---|---|---|
| P1 | `Spec`, `Diagnostic`, `TestCase` types | `packages/wfeval-core` — **frozen D2** |
| P1 | `WorkflowAST` for alignment only (never in `testgen/`) | `packages/wfeval-adapters` |

## What others consume from you — you are on the critical path

| Who | What | Your obligation |
|---|---|---|
| **P3** | `TestCase`, `Assertion`, `MockDefinition` schema | **Propose by D1, P3 signs off by D2.** This is one of only two hard cross-team dependencies. |
| **P3** | `contracts/examples/testcases.response.json` | **Committed by D2.** P3 builds their entire execution loop against this file on D3, six days before your generator works. |
| P1 | `contracts/examples/intent.response.json` | D2 |

**Make the golden example realistic.** Use real element ids from `contracts/examples/artifact.bpmn`. Include a happy case, a boundary case, an adversarial case, at least one mock, and at least one `human_task_outcomes` entry. If P3 builds against a toy example, their execution loop breaks the day your real output arrives.

---

## Deliverables

### Week 1

| Day | Deliverable | Done when |
|---|---|---|
| D1 | OpenAPI for `:8002` drafted; `TestCase` schema proposed to P3 | Decision record opened, P3 responded |
| **D2** | **`contracts/examples/testcases.response.json` + `intent.response.json` committed** | P3 confirms they can build against it |
| D2–D3 | Eval corpus: 30–50 `(prompt, artifact)` pairs in `datasets/corpus/` | Committed with a `manifest.json` describing provenance |
| **D3** | **Stub service live** — all three endpoints return contract-valid golden data | `make contract` green |
| D3–D4 | `POST /v1/spec` — real structured extraction, disk-cached by content hash | Same prompt twice = zero LLM calls the second time |
| D5 | Sufficiency diagnostics (`SPEC-*`) | Fixtures for missing trigger, undefined error behaviour, ambiguous condition |

**Week 1 exit:** a prompt produces a real `Spec` plus sufficiency warnings, over HTTP.

**Corpus bootstrap trick:** take existing BPMN templates, have an LLM describe each in natural language, use the description as the test prompt and the original as the reference artifact. Cheap, and it gives you ground truth. But reverse-generated prompts are unrealistically detailed — add ~10 deliberately under-specified prompts written by hand, because those are what real users send and they're where the generator actually breaks.

### Week 2

| Day | Deliverable | Done when |
|---|---|---|
| D6 | `POST /v1/intent` — deterministic `Spec` ↔ AST coverage diff -> `INT-*` | Fixtures for `INT-MISSING-STEP`, `INT-EXTRA-SIDE-EFFECT`, `INT-ORDER-VIOLATION` |
| D7 | LLM judge for the fuzzy residue only | Calibration set of ~50 human-labelled examples committed to `datasets/golden/` |
| **D7** | **`judge_agreement` populated on every `IntentReport`** | A score never ships without it |
| D8 | Test generation: happy path, boundary for every numeric condition in the spec, adversarial (null, empty, oversized, type-confused) | A spec with 3 numeric conditions yields ≥6 boundary cases |
| D8 | Invariant assertions | `terminal_events == 1`, `no task executes more than N times`, `no PII in outbound payloads` |
| D9 | `MockDefinition` per external integration in the spec | P3's WireMock seeds from your output without transformation |
| D10 | Corpus intent-alignment run; contribute findings to the baseline writeup | Ranked list of the generator's most common intent failures |

**Week 2 exit:** a prompt yields a full test suite with mocks; a `(prompt, artifact)` pair yields an intent score with published judge agreement.

---

## Traps specific to your service

**Alignment must be mostly deterministic.** The temptation is to hand the prompt and the artifact to an LLM and ask "does this match?". That produces unstable, unexplainable scores. Do the structured work first — `Spec` steps vs. AST elements, ordering constraints, side-effect detection — and reserve the judge for the residue that genuinely can't be checked structurally. Deterministic diffs also produce far better `suggested_fix` text.

**A judge score without an agreement rate is not usable.** Calibrate against ~50 human labels and publish the agreement number alongside every score. If agreement is below ~0.8, say so loudly rather than shipping a confident-looking number.

**Assertions should be semantic, not element-id-bound, wherever possible.** "Must traverse the approval branch" survives the generator restructuring its element ids; `must_traverse: ["Activity_1x2ab"]` does not. Where you must use ids, note it in the assertion description so P3 can resolve fuzzily.

**Boundary cases come from the spec's numeric conditions, not from your imagination.** If the spec says "over 10000", generate 9999 / 10000 / 10001. That off-by-one at the branch condition is the single most common behavioural bug in generated workflows.

**Cache aggressively.** You will re-run the corpus dozens of times. Content-hash every LLM call to disk on day one, not as a week-2 optimisation — it turns a 40-minute corpus run into 40 seconds and you'll iterate ten times more.
