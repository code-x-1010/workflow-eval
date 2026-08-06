# 0019 — INT-* intent-alignment code registry

**Author:** P2   **Date:** 2026-08-05   **Status:** proposed
**Affects:** P1 (aggregates these into `EvaluationReport`), the generation team (keys repair logic off these strings)

## Context

`INT` is P2's second prefix in `PREFIX_OWNER`. Two codes already exist in
`contracts/examples/intent.response.json`, committed at D2 and validated against
the shared fixture element by element: `INT-CONDITION-NOT-EXPRESSED` and
`INT-NO-ERROR-HANDLING`. That file's own note says the registry lands at D6 with
the deterministic differ, the same way `SPEC-*` landed early in `0008`. This is
that registry.

Same rule as `0008`: **append-only**. The generation team keys repair logic off
these strings, so a code is never renamed or repurposed.

## Decision

Eight codes. Each names a specific, checkable disagreement between what the
prompt asked for and what the artifact does.

| Code | Sev | Raised when |
|---|---|---|
| `INT-MISSING-STEP` | warning | A step the prompt asked for has no element in the artifact. |
| `INT-EXTRA-SIDE-EFFECT` | warning | The artifact performs a side-effecting task the prompt never asked for. |
| `INT-ORDER-VIOLATION` | warning | Two steps run in an order the prompt contradicts. |
| `INT-CONDITION-NOT-EXPRESSED` | warning | A branch condition from the prompt is not expressed as a routable condition. |
| `INT-NO-ERROR-HANDLING` | warning | The prompt states failure behaviour; the artifact has no path implementing it. |
| `INT-TRIGGER-MISMATCH` | warning | The artifact's start event is a different *kind* of trigger than the prompt stated. |
| `INT-INTEGRATION-MISSING` | warning | An integration named in the prompt is invoked nowhere in the artifact. |
| `INT-UNREACHABLE-INTENT` | warning | A matched step exists but cannot be reached from the start event. |
| `INT-SPEC-DRIFT` | info | A caller-supplied `Spec` disagrees with the one P2 extracts from the same prompt. |
| `INT-JUDGE-UNCALIBRATED` | warning | The judge deciding the fuzzy residue scores below 0.8 on the calibration set. |

The last two are about the *evaluation*, not the artifact, and are the only two
here that can fire on a perfect workflow.

`INT-SPEC-DRIFT` is the charter's requirement that when the generation team
supplies their own `Spec`, P2 uses it **and additionally reports their intent
versus ours**. It is `info` because neither reading is authoritative — a
disagreement is a question for a human, not a defect.

`INT-JUDGE-UNCALIBRATED` is the charter's "if agreement is below ~0.8, say so
loudly rather than shipping a confident-looking number", made machine-readable.
`IntentReport` has nowhere to put prose, so the loudness has to be a diagnostic
or it does not travel with the score. **It currently fires on every real
response** — see the note below.

### Every INT code is a `warning`, and that is a limitation, not a choice

`diagnostics.py` defines `error` as "blocks a gate, or fails a test case", and
`IntentReport` has **no `gates` field**. No `INT-*` code can therefore block
anything, whatever it says. I first wrote `INT-CONDITION-NOT-EXPRESSED` as
`error` — the artifact's threshold existing only as a flow label means the
gateway cannot route at all — and downgraded it because the type system gives
the severity nowhere to act.

This is worth P1 knowing when aggregating: **a finding as serious as "the user's
stated threshold is implemented nowhere" arrives at the Gateway indistinguishable
in severity from "an integration is missing"**. It was raised in P2's D2 handoff
and is still true. Either `IntentReport` grows a `gates` field, or scoring has to
treat some INT codes as more than warnings by code rather than by severity. I am
not proposing the type change unilaterally — it is `packages/**`, and the freeze
holds.

### Why these eight and not more

Each one is decidable by a deterministic diff over `Spec` × `WorkflowAST`. That
is the charter's explicit trap for this service: *"the temptation is to hand the
prompt and the artifact to an LLM and ask 'does this match?'. That produces
unstable, unexplainable scores."* Anything needing paraphrase-level judgement is
left to the judge at D7 and is reported through `judge_agreement`, never as an
`INT-*` code — so a code in this registry always has a mechanical explanation and
a `suggested_fix` that names an element.

## Scores

`IntentReport.scores` carries three, all in 0..1 and all deterministic:

- `step_coverage` — matched spec steps / total spec steps.
- `order_fidelity` — ordered pairs the artifact honours / ordered pairs the spec states.
- `intent_coverage` — the headline. Step coverage penalised by unmatched
  side effects, unexpressed conditions and missing integrations.

The golden example reports `intent_coverage: 0.72` with all four steps matched,
which is only coherent if the headline number is *not* step coverage. It is not.

## `judge_agreement` today is 0.407, and that is the honest number

Measured over `datasets/golden/intent_judgements.jsonl` (54 pairs) against the
lexical matcher, which is what decides pairs when no LLM judge is configured —
the default, since this repo has no LLM client.

The breakdown is the interesting part, and it is a finding rather than a defect:

| calibration pairs | mean lexical similarity |
|---|---|
| labelled `match` | 0.373 |
| labelled `no_match` | **0.448** |

**On the residue, lexical similarity is anti-correlated with intent.** The pairs
a text comparison cannot settle are precisely the ones where shared vocabulary
misleads: "revoke access" / "grant access" share every content word and are
opposite acts, while "extract the vendor and the amount" / "parse invoice fields"
share none and are the same act. No threshold fixes a signal that points the
wrong way — 0.407 on a balanced set is worse than a coin flip.

This is the quantitative case for the charter's design: *do the structured work
first, reserve the judge for the residue*. The deterministic differ is right to
be deterministic, and the residue genuinely needs something else. Until an LLM
judge is wired, `INT-JUDGE-UNCALIBRATED` fires on every response and intent
scores should be read as indicative.

It also means the number is not "how good is P2's matching" — the matcher handles
the easy majority well (step coverage 1.0 on a faithful artifact). It is "how
much do you trust the calls that were genuinely hard", which is what a
calibration figure is for.

## Sign-off

- [x] P2
- [ ] P1 — awareness; and the `gates`/severity limitation above is worth a decision of its own
- [ ] P4 — awareness: `intent_coverage` is the number that reaches the scorecard
