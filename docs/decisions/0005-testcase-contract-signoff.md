# 0005 — P2 -> P3 test case contract: sign-off, emission rules, one added field

**Author:** P2   **Date:** 2026-07-31   **Status:** proposed   **Affects:** P1, P3

## Context

`AGENTS.md` §7 names this as one of only two places where the four workstreams
genuinely touch: *"P2 -> P3 — `TestCase`, `Assertion`, `MockDefinition` in
`testcase.py`. P2 proposes, P3 signs off."* It is P2's D1 deliverable and it must
be settled before the D2 freeze. `0003` moved first from P3's side (`TaskStub`)
and is still waiting on P2. This record closes the loop from the other end.

Two things forced more than a rubber stamp:

1. `contracts/examples/testcases.response.json` currently keys three `TaskStub`s
   by `element_id` (`Task_autopay`, `Task_notify`) and every `path` assertion by
   element id (`Gateway_amount`, `Task_approval`). Those ids exist **only in the
   generated artifact**. P2's testgen never sees the artifact — that is the
   anti-circularity rule, enforced by `.importlinter` contract 2, by
   `TestCasesRequest` having no `artifact` property, and by
   `tests/contract/test_anti_circularity.py`. P3 hand-authored those ids from the
   shared fixture, which was the right call for a D2 golden example. But it means
   **the golden example is not shaped like P2's real output**, and P3's charter
   says they build their whole execution loop against it. That divergence has to
   be stated now, not discovered at D8.
2. `Assertion` has no way to say whether the strings in `must_traverse` are
   element ids or semantic descriptions. P2's charter mandates semantic phrasing
   ("must traverse the approval branch"); P3's matcher today compares literal ids.
   Same string field, two incompatible readings, no way to tell them apart.

## Decision

### 1. `TaskStub` is accepted as specified in `0003`

Shape, per-case scoping on `TestCase`, `outputs[i]` cycling per invocation,
last-entry-repeats, and the `MockDefinition` split (real outbound HTTP vs. the
task invocation itself) are all correct. No changes requested. P2 signs off;
`0003`'s checkbox is ticked.

P3's reasoning for per-case rather than a top-level list is right and worth
keeping visible: a stub's outputs have to match that case's own `input`, so a
shared list would force every case to see the same canned output regardless of
its own amount.

### 2. `TestCase`, `Assertion` and `MockDefinition` are otherwise proposed unchanged

P2 formally proposes the current `testcase.py` shapes as the frozen D2 contract,
with the single addition in §4 below. `CaseKind`, `AssertionType`,
`human_task_outcomes` and the `MockDefinition` fields all survive contact with
the real generator design.

### 3. P2's generator emits `asset_ref`-keyed `TaskStub`s, never `element_id`

`element_id` stays in the type — it is genuinely useful for hand-written
fixtures and for P3-side resolution — but **no `TaskStub` produced by
`POST /v1/testcases` will ever carry one**, because P2 cannot know an element id
without reading the artifact. From D8, every stub P2 emits is keyed by
`asset_ref`, derived from the spec's `integrations` and step descriptions.

The same applies to `must_traverse` / `must_not_traverse`: real P2 output names
branches and steps, not ids.

### 4. Add `path_match` to `Assertion` (the only type change requested)

> **Superseded by `0009` (2026-08-03).** `human_task_outcomes` turned out to have
> the same element-id problem, and one field on `TestCase` covers both cases more
> simply than a per-assertion field covers one. Read `0009` before actioning this
> section. Everything below still describes the reasoning; only the field's name
> and location changed.

```python
class PathMatch(str, Enum):
    EXACT = "exact"        # strings are BPMN element ids, compare literally
    SEMANTIC = "semantic"  # strings are step/branch descriptions, resolve fuzzily

class Assertion(BaseModel):
    ...
    path_match: PathMatch = PathMatch.EXACT
```

`exact` is the default, so every existing assertion, the committed golden
example, and P3's current matcher keep working with no edits. P2's real output
sets `semantic`. P3 needs no semantic matcher until D7 — until then, treating
`semantic` as unresolvable (`skipped` + `EXE-RUNNER-UNSUPPORTED`) is the correct
and honest behaviour, and is strictly better than the alternative this field
exists to prevent: comparing "must traverse the approval branch" against a list
of element ids, finding no match, and reporting a **false assertion failure**
against a workflow that was fine.

This is one optional field with a backward-compatible default. It is proposed
now precisely because it costs nothing before the D2 freeze and cannot be added
after it without another round of this.

## Consequences

- **P3, action required:** tick §1's sign-off, and sign off or counter-propose
  §4. If you counter-propose, the alternative that also works is a naming
  convention (semantic targets prefixed `@`), but an explicit enum beats a
  string convention nobody can typo-check.
- **P3, plan for D7-D8:** the golden example's `element_id` stubs and id-bound
  path assertions are placeholders that will not resemble P2's real output. Your
  resolver should not acquire a dependency on element-id keying. Adding one
  case to the example keyed by `asset_ref` with `path_match: semantic` — even
  ahead of real testgen — would exercise the path that actually ships. P2 owns
  that file and will do it at D2 unless you get there first.
- **P1, flagged, no action:** `asset_ref` resolution runs through
  `wfeval.adapters.parse()`, which does not exist yet (per P3's handoff, D3's
  `asset_refs.py` degrades gracefully to a no-op). Once P2's real generator
  lands, `asset_ref` is the *only* key P2 emits — so if `wfeval.adapters` is
  still empty at D8, every automated task in every case becomes unresolvable and
  the entire execution tier reports `skipped`. Today that reads as a graceful
  degradation; from D8 it is the critical path.
- No `.importlinter` change. Nothing here lets `testgen/` see the artifact —
  §3 and §4 exist specifically to keep it from needing to.
- `contracts/intent.openapi.yaml` (drafted today) encodes §3 and §4 in the
  `TaskStub` and `Assertion` schemas.

## Sign-off

- [x] P2
- [ ] P3 — §1 is your own proposal, ticked from my side; §4 needs your call
      (still unsigned on D3, past the freeze — see the 2026-08-04 update in `0009`)
- [ ] P1 — awareness only: `wfeval.adapters.parse()` becomes critical path at D8
