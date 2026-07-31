# P4 — Cost Service + Scoring + Report

> Read `AGENTS.md` first. Then `docs/handoff/P4.md` — that is your memory from previous sessions.

You answer "what will this cost per run?" without running anything, and you define what all the other numbers mean. You produce the artifact everyone actually looks at — the report — which means your presentation choices determine whether this project is trusted or dismissed.

---

## Ownership

**You may edit**

```
services/cost/**                            # :8004
services/gateway/src/weights.yaml           # versioned scoring config
services/gateway/src/score.py               # composite scoring
services/gateway/src/render.py              # HTML report
contracts/examples/cost.response.json
```

**You must never edit**

```
packages/**    services/validation/**   services/intent/**   services/sandbox/**
services/gateway/src/{main.py,orchestrate.py}     # P1's
```

You own three files inside P1's service directory. That's deliberate — the aggregator belongs with whoever defines what the numbers mean — but stay inside those three.

---

## Your contract — `:8004`

```
POST /v1/cost
  { platform, artifact, prompt?, overrides{ branch_probabilities, free_variables, budget_per_instance } }
  -> CostReport

POST /v1/calibrate    { traces: [Trace] }
  -> { mape: float, priors_updated: [...] }

GET  /v1/pricing      -> current price book + version
GET  /healthz
```

You take the **prompt as well as the artifact**. Budgets, branch probability hints ("about 10% need approval"), and volume statements ("up to 50 line items") all live in the natural-language request and nowhere else.

---

## What you consume

| From | What | Where to get it before it exists |
|---|---|---|
| P1 | `WorkflowAST` via `wfeval-adapters` | frozen D2 |
| **P3** | `Trace.Actuals` for calibration | **`contracts/examples/execution.response.json`** — available D2 |
| P1/P2/P3 | Report slices for scoring | `contracts/examples/*.response.json` |

## What others consume from you

| Who | What | Your obligation |
|---|---|---|
| P1 | `contracts/examples/cost.response.json` | **Committed by D2** |
| P1 | `score()` and `render()` in the Gateway | Stub returning valid shapes by D3 |
| **P3** | Sign-off on the `Actuals` shape | **By D2.** One of only two hard cross-team dependencies. |

---

## Core design: the output is a distribution, not a number

Cost depends on which path executes; a workflow with three exclusive gateways has eight cost profiles. Every report carries **min**, **expected**, **max**, and a **symbolic expression** where a term is genuinely unknown.

### Path costing — two algorithms

- **Min and max need no enumeration.** With element costs as edge weights, they're shortest and longest weighted path on a DAG — linear time. **Always computed, always available**, even when the workflow is too complex for anything else.
- **Expected cost needs enumeration**, exponential in the number of exclusive gateways. Cap at K paths (default 10,000), highest-probability first. Above K, report min/max only and set `confidence: low`.

### AND gateways do not multiply paths

All parallel branches always execute, so they collapse into a single summation. Only `GATEWAY_EXCLUSIVE` and `GATEWAY_INCLUSIVE` branch the cost space. **A naive implementation that treats every gateway as a branch blows up on the first real workflow it sees.** This is the single most common way this feature fails.

### Loops stay symbolic

Read `Element.loop` (`LoopSpec` in `ast.py`):

1. `max_iterations` set -> use it.
2. `cardinality_expr` set with `max_iterations` None -> **data-dependent. Stay symbolic:** `0.031 + N_line_items * 0.012`. Bind `N` from `Spec.inputs[].bound` if available, or from `overrides.free_variables`.
3. Neither -> emit `COST-UNBOUNDED-LOOP`, set `unbounded: true`.

Never invent an iteration count. A symbolic expression is more useful than a fabricated point estimate and it composes — the generation team substitutes their own volume assumptions.

### Agent token estimation

Statically measurable: system prompt length, tool schema bytes, input payload size from `Spec.inputs`. Not statically knowable: turn count and output length — those come from calibration priors keyed by task archetype.

```
tokens ≈ Σ(turn=1..T) [ fixed_context + accumulated_history(turn) ] + output
```

Note `accumulated_history`: agent context grows every turn, so **token cost is superlinear in turn count**. A task averaging 6 turns instead of 3 costs considerably more than double. This is the biggest source of cost surprise in agentic processes — surface it as `COST-LLM-IN-LOOP` rather than burying it in a total.

### Calibration

`static estimate -> actual run -> residual -> refit priors -> report MAPE`.

`confidence` is derived, never asserted: `low` until ≥30 calibration runs for the archetype, `medium` under 30% MAPE, `high` under 15%.

---

## Deliverables

### Week 1

| Day | Deliverable | Done when |
|---|---|---|
| D1 | OpenAPI for `:8004`; sign off P3's `Actuals` shape | Decision record closed |
| **D2** | `contracts/examples/cost.response.json` committed | P1 can build Gateway aggregation against it |
| D2–D3 | `pricing.yaml` price book; resource inventory walking the AST | Every `ElementKind` maps to a priced resource or an explicit zero |
| **D3** | **Stub service live** + `score()`/`render()` stubs in the Gateway | `make contract` green |
| D4–D5 | Path costing: AND-collapse, min/max via weighted DAG shortest/longest path, `CostExpression` type | Real BPMN returns real min/max; a 6-gateway fixture completes in <1s |
| D5 | Scoring skeleton + HTML report v1 | `make eval` produces a readable report from golden examples |

**Week 1 exit:** a real BPMN returns real min/max cost, rendered in the report.

### Week 2

| Day | Deliverable | Done when |
|---|---|---|
| D6 | Bounded enumeration for expected cost, K-cap with graceful degradation | A pathological 20-gateway fixture degrades to min/max instead of hanging |
| D6 | Loop handling: `LoopSpec` extraction, symbolic free variables, `COST-UNBOUNDED-LOOP` | Fixture with a data-dependent loop returns an expression, not a number |
| D7 | Static token counting (`tiktoken`) + archetype priors | System prompt and tool schema tokens counted exactly |
| D7 | `COST-*` hotspot advice | Fixtures for `COST-LLM-IN-LOOP`, `COST-AGENT-FOR-DETERMINISTIC-DECISION`, `COST-NO-EARLY-EXIT` |
| **D8** | **`assumptions` and `confidence` mandatory on every response** | A `CostReport` with `confidence: low` and empty `assumptions` fails validation |
| D8 | Budget gating from `Spec.budget_per_instance` -> `COST-BUDGET-EXCEEDED` | Only fires when a budget was actually stated |
| D9 | `POST /v1/calibrate` — refit from P3's traces, compute MAPE | Report MAPE even if it's embarrassing |
| D9 | Final scoring, verdict thresholds, `scoring_version` stamping | Re-scoring a stored run with new weights is an explicit action, not a side effect |
| D10 | Full corpus run -> baseline metrics writeup | Pass rate, score distribution, top diagnostic codes, cost distribution |

**Week 2 exit:** a baseline report ranking what the generator gets wrong most often and what it spends most on.

---

## Scoring

```
overall = 0 if any gate fails, else:
    0.35 * structural_soundness      (P1)
  + 0.35 * intent_coverage           (P2)
  + 0.30 * execution_pass_rate       (P3)
```

Gates (binary, hard fail): `schema_validity`, `reference_integrity`, `platform_acceptance`.

| Verdict | Condition |
|---|---|
| `fail` | any gate fails, or `overall < 0.60` |
| `pass_with_warnings` | all gates pass, `0.60 ≤ overall < 0.85`, or any `warning` |
| `pass` | all gates pass, `overall ≥ 0.85`, no errors |

**Cost is deliberately excluded from `overall`.** A cheap wrong workflow is not better than an expensive correct one; mixing them makes both numbers uninterpretable. Cost gates only when a budget was explicitly stated in the prompt or in a test-case assertion.

Weights live in `weights.yaml`, versioned. If a tier is unimplemented, its score is `null` — never a default number that looks like a measurement.

---

## Traps specific to your service

**The framing risk is bigger than the technical risk.** Someone will screenshot your dollar figure into a budget deck by Friday. Absolute cost prediction is genuinely hard; **relative ranking is much easier and more useful** — ranking N candidate workflows, or comparing generator version A against B, where systematic estimation error largely cancels. Lead every presentation of this feature with the comparative framing. Make the HTML report show `confidence` before it shows the number.

**`assumptions` is not optional metadata, it is the feature.** "Uniform branch probabilities, no execution history" and "agent turn prior = 3.2, uncalibrated" are what stop a low-confidence estimate being mistaken for a quote. Enforce non-empty `assumptions` whenever `confidence` is `low`, in code, as a validator.

**Unknown hosts are excluded and flagged, never priced at zero.** Silently pricing an unrecognised API at zero produces a confidently wrong total. Put it in `assumptions`.

**Never hardcode prices.** `pricing.yaml` is versioned and dated; every report stamps `pricing_version`. Vendor rates change, and a stale rate silently corrupts every historical comparison you'll want to make in month two.

**Get your real negotiated rates.** Public list prices are wrong for an enterprise UiPath tenant. Chase this by D6 — the price book is only as good as its inputs, and this is a question only a human can answer.

**Two `COST-*` codes are genuinely valuable advice, not warnings.** `COST-AGENT-FOR-DETERMINISTIC-DECISION` (an agent doing a job a DMN table would do for orders of magnitude less, deterministically) and `COST-NO-EARLY-EXIT` (an expensive task running before a cheap filter that could have short-circuited it). Both are statically detectable and both are usually pure wins. Prioritise them over refining the headline number.
