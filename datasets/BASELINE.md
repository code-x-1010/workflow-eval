# P2 intent baseline — D10 findings

**Run:** `python datasets/run_alignment.py` (add `--json` for the raw numbers).
**Date:** 2026-08-06 (first written 2026-08-05).
**Corpus:** 40 `(prompt, artifact)` pairs, `datasets/corpus/`.

> **Re-run 2026-08-06, after `0020`/`0021` landed.** All 40 artifacts parse now, up
> from 35, so every number below is computed over the whole corpus for the first
> time. Making those five visible immediately exposed two false positives in P2's
> own differ, both since fixed; Finding 3 records what that changed. The
> superseded 2026-08-05 figures are kept inline where the movement is the point.

This is P2's contribution to the baseline writeup: what the intent tier measures
today, how much of it can be trusted, and the ranked list of what it finds.

---

## Read this before quoting any number here

**These figures measure P2's own analysers, not any generator's output quality.**

The corpus's reference artifacts are not generator output. Thirty of the forty
were built artifact-first from a process template and *then* described, so the
reference is what a perfect generator would have emitted for that prompt. When
the differ scores 0.795 against one, that is the differ failing to recognise a
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
| Alignment `intent_coverage`, ground-truth references | **0.795** mean, 0.833 median | 30 cases |
| Alignment `step_coverage`, same | **0.913** mean | 30 cases |
| Alignment `intent_coverage`, under-specified | **0.800** mean, 1.000 median | 10 cases |
| Judge agreement | **0.407** | 54 calibration pairs |
| Cases generated | **94** (18 boundary, 19 mocks) | 40 prompts |
| Artifacts skipped, unparseable | **0** | was 5, `0020` |

`intent_coverage` on ground-truth references is not comparable to the
2026-08-05 figure of 0.762: that was 25 cases, this is those 25 plus the five
`0020` used to exclude. Measured over the same 30 cases, it moved 0.744 → 0.795
across this session's two fixes.

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
0.913 on ground-truth references. The 0.407 describes the hard tail only, which
is what a calibration figure is for.

**Caveat that must travel with this number:** all 54 labels were authored by P2.
The same party wrote the matcher, the judge prompt and the answer key, so this is
an upper bound. See `datasets/golden/README.md`.

---

## Finding 3 — RESOLVED, and unblocking it broke two things in P2's own differ

`0020` is fixed. P1 added `ElementKind.INTERMEDIATE_EVENT` (`0021`) rather than
reusing `TIMER`, and all 40 artifacts now parse. The five formerly-skipped cases
score 1.000, 1.000, 1.000, 0.833 and 0.833.

The prediction this finding made was wrong, and in the reassuring direction.
It warned that `INT-NO-ERROR-HANDLING` was under-counted because the five cases
best able to raise it could not run. They run now, and it still fires exactly
twice — on c08 and c12, neither of them one of the five. The reason is
straightforward in hindsight: those five artifacts were unparseable *because*
they carry error boundary events, which is to say they handle their errors
correctly. The rule was right to stay quiet.

**What did break was P2's own tooling, in two places, and neither was visible
while the five cases were skipped.** Both are the house error this baseline
already names in Finding 4 — reading a P2 blind spot as somebody else's defect:

1. **`INT-UNREACHABLE-INTENT` fired on 5 of 40 cases, all five of them these.**
   A boundary event has no incoming `sequenceFlow` — BPMN attaches it with
   `attachedToRef` — so `align._reachability()`, which walked flows only,
   stranded every error handler in the corpus and reported the *generator* as
   having left a step unwired. `_attachments()` now walks the attachment as the
   control-flow edge it is. Mean `intent_coverage` 0.744 → 0.787.
2. **`INT-INTEGRATION-MISSING` fired on c01, the negative control.**
   `_integrations_missing()` searched element names for literal tokens, so
   `payments_api` did not match an artifact naming its task "Auto-pay invoice"
   with a "Payment API failed" boundary event. It now matches against
   `extract.INTEGRATION_VOCABULARY` — the same curated table that decided the
   prompt named the integration in the first place, rather than a second set of
   token rules that would drift from it. 0.787 → 0.795, and c01 is silent again.

The lesson is the corpus's, not the adapter's: **a case that cannot run cannot
falsify anything.** Five skipped cases hid two false-positive rules for a full
day, and one of them was hiding on the negative control — the single case whose
whole job is to prove this tier does not cry wolf.

---

## Finding 4 — The two most common findings are both matcher artefacts, not defects

`INT-EXTRA-SIDE-EFFECT` (13 occurrences, 10/40 cases) and `INT-MISSING-STEP`
(13 occurrences, 11/40 cases) top the ranked list, on artifacts that are correct
by construction. Both are the same underlying problem seen from two sides: **the
matcher cannot pair a step with an element whose name is a paraphrase** — which
is Finding 2 restated in the alignment tier.

This was much worse before D6 landed a prompt-support check: `INT-EXTRA-SIDE-EFFECT`
alone fired **83 times** across the 35 artifacts then parseable, because an unmatched
element was being read as "the generator invented this" when it actually meant
"`extract.py` produced no step for it". Consulting the prompt before accusing the
generator took it to 13 and moved mean `intent_coverage` from 0.306 to 0.773.

The residual 13 are the paraphrase tail. An LLM judge wired into `_match()` is
the fix, and Finding 2 is the evidence that nothing cheaper will do.

Both counts are unchanged by the 2026-08-06 re-run even though five more
artifacts entered it, which is its own small result: the five carry no unmatched
paraphrase, so the tail is a property of how a few specific references are worded
rather than something that scales with corpus size.

The `INT-INTEGRATION-MISSING` fix in Finding 3 is the same tail met in a place
where it *was* cheaply fixable — the vocabulary was already curated and simply
was not being consulted from both directions. That is the distinction worth
carrying into the `_match()` work: reach for the judge for genuine paraphrase,
not for a comparison that some existing table already answers.

---

## Ranked list — the D10 deliverable

Findings across all 40 cases, most frequent first:

| Occurrences | Cases hit | Code | Read as |
|---|---|---|---|
| 13 | 10/40 | `INT-EXTRA-SIDE-EFFECT` | mostly matcher paraphrase failure (Finding 4) |
| 13 | 11/40 | `INT-MISSING-STEP` | mostly matcher paraphrase failure (Finding 4) |
| 4 | 4/40 | `INT-CONDITION-NOT-EXPRESSED` | **genuine**: reference artifacts label flows without condition expressions |
| 2 | 2/40 | `INT-NO-ERROR-HANDLING` | genuine (c08, c12) — and no longer under-counted, see Finding 3 |
| 2 | 2/40 | `INT-TRIGGER-MISMATCH` | genuine |
| 1 | 1/40 | `INT-INTEGRATION-MISSING` | **the paraphrase tail again**: c10's "Process refund with provider" is the payments provider, but `provider` alone cannot join the vocabulary without matching a provider of anything |

`INT-UNREACHABLE-INTENT` appeared 6 times in the first run of the full corpus and
appears zero times now; it was entirely the Finding 3 defect.

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
   (Finding 1). Add the decline tests alongside, not after. Unchanged from the
   first writing, and now the only item on this list with nothing in front of it.
2. **An LLM judge in `_match()`** — the only fix for the paraphrase tail, and
   0.407 is the evidence (Findings 2 and 4). Note Finding 4's caveat first: check
   whether an existing table already answers the comparison, as it did for
   integrations, before paying for a model call.
3. **Independent labels for `datasets/golden/`** — until then `judge_agreement`
   is an upper bound and says so.
4. ~~Re-run this baseline once `0020` lands~~ — **done, 2026-08-06.** That is
   this run. See Finding 3 for what it found.

Item 1 and 2 are inside P2's lane. Item 3 is not.
