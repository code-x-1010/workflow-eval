# 0009 — `human_task_outcomes` has the same element-id problem, and one field fixes both

**Author:** P2   **Date:** 2026-08-03   **Status:** proposed — UNANSWERED PAST THE FREEZE   **Affects:** P3, P1
**Extends:** `0005` §4 — read that first; this replaces the field it proposes with a
broader one.

## Context

Found while adding `tc_006` to `contracts/examples/testcases.response.json`
today — the case that shows P3 the shape P2 actually emits from D8.

`0005` §3 established that P2 cannot produce a BPMN element id, because testgen
never sees the artifact, and dealt with the two places that mattered:
`TaskStub` (keyed by `asset_ref` instead) and `Assertion.must_traverse` (§4's
`path_match`). It missed a third:

```python
class TestCase(BaseModel):
    human_task_outcomes: dict[str, str] = Field(
        default_factory=dict,
        description="element_id -> outcome. Lets Sandbox auto-resolve human tasks deterministically.",
    )
```

Same defect, same cause. A spec extracted from "route it to a manager for
approval" yields a step, not `Task_approval`. From D8, every key P2 puts in this
dict is a step description, and P3's resolver is documented to read them as
element ids.

The failure mode is quieter than the one §4 prevents, which is why it went
unnoticed: an unresolvable key does not produce a false assertion failure, it
produces a human task nobody answers — so the instance blocks, times out, and
reports `error`. On a corpus run that reads as "the generated workflow hangs",
which is a plausible-looking result and a completely wrong one. A false negative
that looks like a real finding is worse than a loud failure.

## Decision

Replace `0005` §4's `Assertion.path_match` with one field on `TestCase`:

```python
class TargetMatch(str, Enum):
    EXACT = "exact"        # strings are BPMN element ids, compare literally
    SEMANTIC = "semantic"  # strings are step/branch descriptions, resolve fuzzily

class TestCase(BaseModel):
    ...
    target_match: TargetMatch = TargetMatch.EXACT
```

It governs every artifact-facing string in the case: `must_traverse`,
`must_not_traverse`, and the keys of `human_task_outcomes`.

One field on the case rather than one per assertion, because a case is emitted
whole by one generator with one convention — P2 will never mix exact and
semantic targets inside a single case, and a per-assertion field would leave
`human_task_outcomes` (which is not an assertion) needing its own field anyway.
This is strictly simpler than what `0005` §4 proposed and covers strictly more.

Everything else from `0005` §4 stands unchanged:

- `exact` is the default, so `tc_001`..`tc_005`, P3's current matcher, and every
  hand-written fixture keep working with no edits.
- Until P3 builds semantic resolution (D7), treating `semantic` as unresolvable
  — `skipped` + `EXE-RUNNER-UNSUPPORTED` — is the correct and honest behaviour.
- P2's real output sets `semantic`. Nothing P2 emits before D8 sets it.

**If P3 would rather keep §4 as written**, the acceptable alternative is
`Assertion.path_match` *plus* a second enum for `human_task_outcomes`. P2 will
implement against either. What must not happen is the D2 freeze landing with the
gap unaddressed, because after the freeze the only remaining option is for P2 to
emit element ids it cannot know.

## Consequences

- **P3, action required, blocking at the freeze:** sign off `0005` §1-§3 and
  this record's single field, or counter-propose. `0005` has been open since
  D1 with no response and the freeze is today.
- **P1, action required if accepted:** one optional field with a
  backward-compatible default in `packages/wfeval-core/src/wfeval/core/testcase.py`.
  It has to land before the freeze or it never lands.
- **P2:** `contracts/intent.openapi.yaml` gets the field on `TestCase` the
  moment it is accepted, not before — the OpenAPI describes what the frozen
  types actually are, and encoding an unaccepted proposal in the contract is how
  the two drift apart. `tc_006` deliberately carries **no path assertions** for
  the same reason: with no match marker in the type today, a semantic
  `must_traverse` in the golden example would be compared literally against
  element ids and produce exactly the false failure this record exists to
  prevent. Its assertions are `output`, `invariant` and `budget`, which need no
  artifact vocabulary at all. Once this lands, `tc_006` gains a semantic path
  assertion and a `human_task_outcomes` entry keyed by step description.
- No `.importlinter` change. Nothing here lets `testgen/` see the artifact —
  this record exists precisely so it never needs to.

## Sign-off

- [x] P2
- [ ] P3 — your resolver; also still owe `0005` §1-§4
- [ ] P1 — the one-line type change, if accepted


## Update — 2026-08-04 (D3), P2

**The D2 freeze has passed and this is still unsigned. So is `0005`, open since
D1.** `packages/wfeval-core/src/wfeval/core/testcase.py` on `main` has no
`target_match` and no `path_match`, and P1's unmerged branch
(`p1/d2-contracts-and-ci-fix`) does not add one either — it touches
`wfeval-core` only to add a type annotation in `stubs.py`.

Recording what that means rather than working around it quietly, because the
workaround is invisible in the code:

- `contracts/examples/testcases.response.json` still cannot gain a semantic
  path assertion or a description-keyed `human_task_outcomes` entry. `tc_006`
  therefore still shows P3 only *half* the shape P2 emits at D8 — the
  `asset_ref` half. That was billed as a temporary gap on D2; on D3 it is still
  there, and P3 is building the resolver against it now.
- `contracts/intent.openapi.yaml` still describes the frozen type as it is, not
  as proposed. Unchanged reasoning: the OpenAPI must not encode an unaccepted
  proposal.
- From D8, P2's generator has two options and both are bad: emit element ids it
  cannot know (silently wrong test cases), or emit descriptions into fields
  documented as element ids (a human task nobody answers, so the instance
  blocks, times out, and reports `error` — which reads on a corpus run as "the
  generated workflow hangs"). The second is what this record exists to prevent.

**Escalated to my human at the D3 standup.** This is one of the two hard
cross-team dependencies `AGENTS.md` §7 names, and §7's own instruction for an
unresolved one on D3 is to escalate immediately. It needs a human to get P3 and
P1 in the same room; it cannot be resolved from inside P2's session.

Nothing here changes the proposal. One optional field, backward-compatible
default. It was a one-line change on D2 and it is a one-line change now.
