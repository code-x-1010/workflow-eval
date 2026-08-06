# 0020 — `wfeval.adapters.parse()` rejects error boundary events, so 5 corpus artifacts cannot be evaluated

**Author:** P2   **Date:** 2026-08-05   **Status:** proposed   **Affects:** P1 (owner), P2, P3

## Context

D6 runs the deterministic intent differ over `datasets/corpus/`. Five of the 40
reference artifacts fail to parse:

```
c01_invoice_approval      <boundaryEvent id='Boundary_payment_failed'>
c10_refund_request        <boundaryEvent id='Boundary_refund_rejected'>
c15_loan_application      <boundaryEvent id='Boundary_bureau_down'>
c21_subscription_renewal  <boundaryEvent id='Boundary_card_declined'>
c25_server_patching       <boundaryEvent id='Boundary_patch_failed'>
```

each with:

> `only timerEventDefinition is supported today (no ElementKind exists yet for
> message/error/signal/escalation events)`

The message is accurate and the limitation is stated in the adapter, so this is a
known gap rather than a bug. What was not visible until something ran the corpus
through it is **which** cases it costs.

## Why these five and not any others

It is not a random 12.5%. `errorEventDefinition` on a boundary event is how BPMN
expresses "what happens when this task fails" — so the artifacts that cannot be
parsed are **exactly the ones whose prompts state failure behaviour**. c01 is the
corpus's negative control precisely because it states a failure path; c10, c15,
c21 and c25 are the four other cases that do.

The consequence is worse than losing 5 of 40. It biases what is left:

- Intent alignment is now measured only over prompts that *never say what happens
  on failure*. `INT-NO-ERROR-HANDLING` is unfireable on the cases that could
  legitimately raise it, and silent on the rest by design.
- The D10 baseline — "the generator's most common intent failures" — would be
  computed on a sample with error handling systematically removed, and would
  report error handling as a non-issue.
- P2's own negative control is among the missing, so the one case that proves the
  checker stays quiet on a complete prompt cannot be run end to end.

## Decision

Recording rather than fixing. `packages/wfeval-adapters/**` is P1's lane and the
fix is not cosmetic: `ElementKind` has no member for error, message, signal or
escalation events, and `ElementKind` is in `packages/wfeval-core`, **frozen after
D2**. So this needs P1 to decide between:

1. adding `ElementKind.BOUNDARY_ERROR` (or a general `BOUNDARY_EVENT` with the
   definition kind in `attributes`) — a frozen-type change, needing its own
   record;
2. parsing non-timer boundary events into an existing kind with the definition
   recorded in `Element.attributes`, which needs no type change and would be
   enough for every consumer I know of;
3. leaving it, and accepting that no tier can evaluate a workflow with an error
   path.

Option 2 is what I would pick, and it is the smallest change: P2 only needs to
know *that* a boundary error exists on a task and what it routes to, which
`attributes` carries fine. I am not making that call inside P1's lane.

## What P2 did instead

`services/intent/src/align.py` and the D10 runner skip unparseable artifacts and
**report them as skipped rather than as scored zero**. Counting a parse failure
as an alignment failure would attribute P1's adapter gap to the generation team's
output quality, which is precisely the kind of wrong-looking number the whole
`SPEC-*`/`INT-*` severity design exists to avoid. The D10 findings state the
denominator as 35, and say why.

## Consequences

- Until this lands, every intent-alignment number in this repo is measured over
  35 of 40 cases, and the missing 5 are the ones with failure paths. Any
  conclusion about error handling drawn from the D10 baseline is unsupported.
- P3 is likely affected too, though independently: Spiff has its own view of
  boundary events, and P2's D2 note already records `c15` failing to parse in
  base Spiff for an unrelated reason (`businessRuleTask`).

## Sign-off

- [x] P2
- [ ] P1 — owner of the adapter and of `ElementKind`; pick 1, 2 or 3
- [ ] P3 — awareness: same 5 artifacts, possibly the same class of problem in the runner
