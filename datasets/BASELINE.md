# P2 intent baseline — D10 findings

**Run:** `python datasets/run_alignment.py` (add `--json` for the raw numbers).
**Date:** 2026-08-05. **Corpus:** 40 `(prompt, artifact)` pairs, `datasets/corpus/`.

This is P2's contribution to the baseline writeup: what the intent tier measures
today, how much of it can be trusted, and the ranked list of what it finds.

---

## Read this before quoting any number here

**These figures measure P2's own analysers, not any generator's output quality.**

The corpus's reference artifacts are not generator output. Thirty of the forty
were built artifact-first from a process template and *then* described, so the
reference is what a perfect generator would have emitted for that prompt. When
the differ scores 0.762 against one, that is the differ failing to recognise a
correct workflow — not a workflow being wrong.

That makes this baseline useful for exactly one thing right now: **finding out
where P2's own tooling is weakest before it is pointed at real output.** Every
finding below is read that way.

---

## Headline numbers

| Measure | Value | Over |
|---|---|---|
| Sufficiency precision (`SPEC-*`) | **1.000** | 40/40 prompts |
| Sufficiency recall | **0.907** | 40/40 prompts |
| Sufficiency exact-set match | **34/40** | — |
| Alignment `intent_coverage`, ground-truth references | **0.762** mean, 0.750 median | 25 cases |
| Alignment `step_coverage`, same | **0.896** mean | 25 cases |
| Judge agreement | **0.407** | 54 calibration pairs |
| Cases generated | **94** (18 boundary) | 40 prompts |
| Artifacts skipped, unparseable | **5** | decision `0020` |

---

## Finding 1 — Branch-condition recall is the single biggest constraint on P2

**33% of the numeric thresholds in the corpus are extracted. That caps boundary
generation at 18 cases where 54 are available.**

| | |
|---|---|
| Numeric thresholds visible in the prose | ~18 |
| Branch conditions `extract.py` produces | 6 |
| Boundary cases generated (3 per condition) | 18 |
| Boundary cases if recall were complete | 54 |

The generator is not the bottleneck — `boundaries.py` reliably produces three
probes per condition it is given, and does so correctly. It is being starved.
Seven cases lose thresholds outright:

```
c02_expense_reimbursement   extracted 1, present ~3   "under 100" / "100 up to 1000" / "above 1000"
c16_insurance_claim         extracted 0, present ~3
c20_quote_approval          extracted 0, present ~3   "up to 10 percent" / "between 10 and 25" / "over 25"
c08_candidate_screening     extracted 0, present ~1
c11_order_fulfilment        extracted 1, present ~2
c13_inventory_replenishment extracted 0, present ~1
c01_invoice_approval        extracted 1, present ~2
```

The pattern is clear and it is not random: **`extract._branches()` handles a
single bare threshold well and misses banded ones.** "Over 10000" works.
"Claims from 100 up to 1000 go to the line manager; anything above 1000 goes to
the finance director" yields one condition or none — the rule reads one
comparator and one number, and a band is two of each. Percentages inside a band
("between 10 and 25 percent") miss for the same reason.

**This is the highest-leverage work available to P2.** Banded-threshold support
in one function roughly triples the test suite the whole execution tier runs on,
and the off-by-one at a branch condition is the charter's named commonest
behavioural bug in generated workflows. It should come before any further
alignment work.

It is worth being precise about *why* recall is this low: it was bought
deliberately. `extract.py`'s decline rules were tightened at D3 against exactly
these prompts because the loose version read "keep it under 50 cents per invoice"
as a branch on a variable called `it`. Six correct conditions beat eighteen
conditions of which some are fictional, because a fictional threshold produces
three fictional boundary cases that P3 then runs and P4 then prices. The fix is
not to loosen the rules — it is to add a band-shaped rule with its own decline
tests.

---

## Finding 2 — On the residue, lexical similarity points the wrong way

**Judge agreement is 0.407 on a balanced 54-pair set. That is worse than a coin
flip, and no threshold fixes it.**

| Calibration pairs | Mean lexical similarity |
|---|---|
| labelled `match` | 0.373 |
| labelled `no_match` | **0.448** |

The pairs a text comparison cannot settle are precisely the ones where shared
vocabulary misleads. "Revoke system access" and "grant system access" share every
content word and are opposite acts. "Extract the vendor and the amount" and
"Parse invoice fields" share none and are the same act. The signal is
anti-correlated with the truth, so tuning the threshold trades one kind of error
for the other and cannot beat chance.

This is the quantitative case for the charter's design — *do the structured work
first, reserve the judge for the residue* — and it is why
`INT-JUDGE-UNCALIBRATED` fires on every real `/v1/intent` response today.

**It does not mean matching is broken.** `align.py` runs the same lexical
comparison over *all* pairs, most of which are easy, and gets step coverage of
0.896 on ground-truth references. The 0.407 describes the hard tail only, which
is what a calibration figure is for.

**Caveat that must travel with this number:** all 54 labels were authored by P2.
The same party wrote the matcher, the judge prompt and the answer key, so this is
an upper bound. See `datasets/golden/README.md`.

---

## Finding 3 — The five artifacts we cannot parse are exactly the five that matter for error handling

`wfeval.adapters.parse()` rejects non-timer boundary events (`0020`), so c01,
c10, c15, c21 and c25 are skipped. That is 12.5% of the corpus, but it is not a
random 12.5%: `errorEventDefinition` on a boundary event is *how BPMN expresses
what happens when a task fails*, so the unparseable cases are precisely the ones
whose prompts state failure behaviour.

Consequences for anyone reading these numbers:

- `INT-NO-ERROR-HANDLING` fires twice in this run, and cannot fire on any of the
  five cases best able to raise it. **Do not conclude error handling is a minor
  issue from this baseline.**
- c01 is the corpus's negative control, so the one case that proves the pipeline
  stays quiet on a fully-specified prompt cannot be run end to end.
- Skipped cases are reported as skipped, never scored zero. Scoring them would
  attribute an adapter limitation to output quality.

---

## Finding 4 — The two most common findings are both matcher artefacts, not defects

`INT-EXTRA-SIDE-EFFECT` (13 occurrences, 10/35 cases) and `INT-MISSING-STEP`
(13 occurrences, 11/35 cases) top the ranked list, on artifacts that are correct
by construction. Both are the same underlying problem seen from two sides: **the
matcher cannot pair a step with an element whose name is a paraphrase** — which
is Finding 2 restated in the alignment tier.

This was much worse before D6 landed a prompt-support check: `INT-EXTRA-SIDE-EFFECT`
alone fired **83 times** across these same 35 artifacts, because an unmatched
element was being read as "the generator invented this" when it actually meant
"`extract.py` produced no step for it". Consulting the prompt before accusing the
generator took it to 13 and moved mean `intent_coverage` from 0.306 to 0.773.

The residual 13 are the paraphrase tail. An LLM judge wired into `_match()` is
the fix, and Finding 2 is the evidence that nothing cheaper will do.

---

## Ranked list — the D10 deliverable

Findings across 35 parseable cases, most frequent first:

| Occurrences | Cases hit | Code | Read as |
|---|---|---|---|
| 13 | 10/35 | `INT-EXTRA-SIDE-EFFECT` | mostly matcher paraphrase failure (Finding 4) |
| 13 | 11/35 | `INT-MISSING-STEP` | mostly matcher paraphrase failure (Finding 4) |
| 4 | 4/35 | `INT-CONDITION-NOT-EXPRESSED` | **genuine**: reference artifacts label flows without condition expressions |
| 2 | 2/35 | `INT-NO-ERROR-HANDLING` | genuine, but under-counted (Finding 3) |
| 1 | 1/35 | `INT-INTEGRATION-MISSING` | genuine |
| 1 | 1/35 | `INT-TRIGGER-MISMATCH` | genuine |

`INT-CONDITION-NOT-EXPRESSED` is the most interesting genuine finding. Four
reference artifacts carry an exclusive gateway whose outgoing flows are *labelled*
with the condition but carry no `conditionExpression` — the threshold exists as a
name and the gateway cannot route on it. The shared fixture
`contracts/examples/artifact.bpmn` has the same defect, which is why P3 could
never run it through Spiff. If real generator output shares this habit, it is a
class of bug that looks correct in a diagram and fails at execution.

---

## Sufficiency: what the six misses are

Precision is 1.000 — no false positive on any of the 40 prompts, and the negative
control stays silent. Recall is 0.907, and every miss is a recorded judgement
call rather than an oversight (`tests/unit/intent/test_sufficiency_corpus.py`
enumerates them so that fixing one is a visible change):

| Case | Missed | Why |
|---|---|---|
| c09, c23 | `SPEC-UNSTATED-SLA` | urgency implied by *paging an on-call*, not by an adverb. The wider rule fired on c30, which the corpus does not label — two findings for one false positive, not worth it at `info` |
| u02, u09 | `SPEC-NO-ERROR-BEHAVIOUR` | no side-effect verb in the prompt at all ("Big orders should go to a manager") |
| u07 | `SPEC-UNBOUNDED-INPUT` | an unbounded *loop*, not a collection. `SPEC-NO-TERMINAL-STATE` fires instead; reporting both double-counts one gap |
| u10 | four codes | "Automate our onboarding process." No rule can extract four distinct gaps from five words, and inventing them would break precision |

---

## What P2 should do next, in order

1. **Banded thresholds in `extract._branches()`** — triples the test suite
   (Finding 1). Add the decline tests alongside, not after.
2. **An LLM judge in `_match()`** — the only fix for the paraphrase tail, and
   0.407 is the evidence (Findings 2 and 4).
3. **Independent labels for `datasets/golden/`** — until then `judge_agreement`
   is an upper bound and says so.
4. Re-run this baseline once `0020` lands, so error handling can be measured on
   the five cases that state it.

Items 1 and 2 are both inside P2's lane. Items 3 and 4 are not.
