# 0021 — `ElementKind.INTERMEDIATE_EVENT`, not a reused existing kind, for non-timer boundary/intermediate events

**Author:** P1   **Date:** 2026-08-06   **Status:** accepted   **Affects:** P1, P2, P3

## Context

`0020` (P2): the adapter rejected `errorEventDefinition`/`messageEventDefinition`/
`signalEventDefinition`/`escalationEventDefinition` on intermediate/boundary
events, costing 5 of 40 corpus artifacts — exactly the 5 whose prompts state
failure behaviour, biasing the D10 intent baseline against ever measuring
error handling.

`0020` proposed three options and recommended option 2 (map into an existing
`ElementKind`, definition kind recorded in `attributes`, no frozen-type
change) as the smallest fix.

## Why option 2, as literally proposed, doesn't work

The only existing non-task, non-gateway event kind is `TIMER`. Reusing it
collides with `l3_structure.py`'s `_timers()`, which keys **every** element of
kind `TIMER` into a check requiring a `timer_expression` attribute, at `error`
severity:

```
if el.kind != ElementKind.TIMER: continue
...
STR-TIMER-MISSING-VALUE, severity=ERROR   # if no timer_expression
```

Mapping `errorEventDefinition` to `TIMER` would trade one failure for a worse
one: instead of a loud, accurate `AdapterParseError` at the adapter boundary,
every boundary-error event would parse successfully and then fail L3 with a
misleading "timer has no duration" error. Verified before choosing — no other
existing kind is a safer target either (`align.py` special-cases `START_EVENT`
timers the same way at line 402).

## Decision

Added `ElementKind.INTERMEDIATE_EVENT` (option 1). One member for all four
non-timer definitions, not one member per definition — a consumer that only
needs "this is an event, not a task" (which is every consumer today; see
below) doesn't need four cases. The definition kind, and for a boundary event
what task it watches and whether it's interrupting, go in `Element.attributes`:

```
{"bpmn_tag": "boundaryEvent", "event_definition": "error",
 "attached_to_ref": "Task_autopay", "cancel_activity": "true"}
```

Same shape convention `TIMER`'s `timer_type`/`timer_expression` already uses.

**Checked every current consumer of `ElementKind` before adding the member**
(`l3_structure.py`, `l4_soundness.py`, `align.py`) — all are membership tests
against specific known kinds (`{START_EVENT, END_EVENT, ...}`), none do an
exhaustive match that a new enum value could break. `l4_soundness.py`'s Petri
net builder treats an unrecognised kind as an ordinary single-in/single-out
transition, which is the structurally correct behaviour for an event that
fires and continues.

## Consequences

- All 5 previously-failing corpus artifacts parse. Verified: 40/40 pass
  Validation's schema gate; `datasets/run_alignment.py`'s "5 skipped —
  decision 0020" line is now 0 skipped.
- `scripts/run_corpus.py` (docs/decisions/0018) exercises this directly —
  its corpus run is the regression test for this fix, not a new fixture.
- `tests/unit/adapters/test_bpmn.py`: replaced the (now-wrong)
  "message event raises" test with one asserting the mapping and attributes,
  and a new one confirming an event with *no* recognised definition
  (`compensateEventDefinition` — still unmapped) still raises.
- P3: same 5 artifacts may hit an equivalent gap in Spiff's own boundary
  event handling — independent of this fix, `0020` already flagged it as
  "possibly the same class of problem in the runner."
- `INTERMEDIATE_EVENT` carries no cost-model treatment yet (P4's lane) and no
  special L4 soundness/dataflow semantics beyond "a transition." A boundary
  error event's actual firing probability isn't 1, unlike a plain
  pass-through — if P4 or a future L4 rule wants that, `attributes` already
  carries `attached_to_ref`/`event_definition` to key off.

## Sign-off

- [x] P1 — executed
- [ ] P2 — the 5 corpus cases; re-run `python datasets/run_alignment.py` to confirm 0/40 skipped
- [ ] P3 — awareness, same 5 artifacts in the runner
