# 0003 — `TaskStub`: a new P2 -> P3 contract type

**Author:** P3   **Date:** 2026-07-30   **Status:** proposed   **Affects:** P2, P3

## Context
Spiff (see `0002`) never runs a bare `<serviceTask>`/`<userTask>` to completion
on its own — verified by hand against SpiffWorkflow 3.1: with no embedded
script, `do_engine_steps()` leaves it at `TaskState.STARTED` forever. Real
UiPath-generated BPMN has no embedded script either (the activity is described
by extension attributes Spiff doesn't understand), so **every** automated task
in a real artifact needs an explicit resolution step, not just the ones a
test happens to care about.

`MockDefinition` doesn't cover this: it's for real outbound HTTP calls, and
Spiff never makes one (nothing in a bare serviceTask tells it to). We need a
second kind of stub, for the task/agent invocation itself.

## Decision
Add `TaskStub` to `packages/wfeval-core/src/wfeval/core/testcase.py`:

```python
class TaskStub(BaseModel):
    element_id: str | None = None
    asset_ref: str | None = None
    outputs: list[dict[str, Any]] = Field(default_factory=list)
```

keyed by `element_id` or `asset_ref` (`asset_ref` preferred when known — same
"survives the generator restructuring ids" reasoning as semantic path
assertions). `outputs[i]` is returned on the i-th invocation of that task
within one test case's instance; the counter resets per case, since Sandbox
starts a fresh instance per case. `TestCase.task_stubs: list[TaskStub]` is a
new field alongside the existing `human_task_outcomes` — same per-case
scoping, same reasoning.

`MockDefinition` is unchanged and stays scoped to real outbound HTTP calls
(meaningful once `runners/uipath/` is real; Spiff ignores it entirely).

## Consequences
- P2's `/v1/testcases` generates `task_stubs` alongside `assertions` and
  `mocks` — still derived from the prompt/spec alone, never the artifact
  (`task_stubs` describes what a stubbed agent/service *would* return given
  the case's `input`, which is exactly the kind of thing testgen already
  reasons about; it does not require reading the generated workflow).
- `contracts/examples/testcases.response.json` gets `task_stubs` added to at
  least one case, so P3's engine has a golden example to build against per the
  usual Day-2 protocol.
- No `.importlinter` change needed — this doesn't touch the anti-circularity
  boundary (`testgen/` still never imports `wfeval.core.ast`).

## Sign-off
- [x] P2 — shape accepted unchanged. See `0005` for the emission rules that
  follow from it (P2 emits `asset_ref`-keyed stubs only; `element_id` is
  unreachable from testgen without breaking anti-circularity).
- [x] P3
