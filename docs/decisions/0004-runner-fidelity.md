# 0004 — `runner` / `fidelity` on `Trace` and `ExecutionReport`

**Author:** P3   **Date:** 2026-07-30   **Status:** proposed   **Affects:** P3, P4

## Context
Spiff becoming the primary runner (`0002`) means every execution result now
carries an implicit asterisk: it's evidence of what the workflow's *control
flow* does, not proof of what it does on the real platform (real connectors,
Orchestrator queueing, Action Center semantics). That distinction needs to be
explicit in the data, not left as tribal knowledge, or a calibration run or a
report six weeks from now silently treats a Spiff result as platform-equivalent.

## Decision
Add to `packages/wfeval-core/src/wfeval/core/trace.py`:

```python
class RunnerFidelity(str, Enum):
    PRODUCTION = "production"
    REDUCED = "reduced"
```

`Trace.runner: str` (e.g. `"spiff"` / `"uipath_maestro"`) and
`Trace.fidelity: RunnerFidelity` (default `REDUCED`).

Add to `packages/wfeval-core/src/wfeval/core/report.py`:
`ExecutionReport.runner`, `ExecutionReport.fidelity` (same shape), and
`ExecutionReport.confidence: Confidence` (default `MEDIUM`), with a
`model_validator` that **raises** if `confidence == HIGH` while
`fidelity != PRODUCTION`. This is enforced in code, not left as documentation
the way `assumptions`-when-`confidence`-is-`low` already is for Cost — the
same "never ship a number without its confidence" house rule, applied here as
"never ship high confidence from a substitute engine."

## Consequences
- `contracts/examples/execution.response.json` updated with `runner: "spiff"`,
  `fidelity: "reduced"`, `confidence: "medium"`.
- P4: calibration priors and MAPE computed from Spiff traces should be
  reported/labeled as such — `Trace.fidelity` is available per-trace for this.
  `robot_minutes`/`human_minutes` in `Actuals` have no real meaning without an
  RPA/orchestrator layer; expect `null` there under Spiff, not a fabricated
  value.
- Nothing here changes `Trace.path`/`events`/`final_variables`/`totals` — the
  existing P3->P4 `Actuals` handshake is unaffected in shape, only in what
  fidelity level it should be read at.
- Once `runners/uipath/` is real, its results carry `fidelity: "production"`
  and can legitimately reach `confidence: "high"`; Spiff results never can, by
  construction of the validator above.

## Sign-off
- [x] P3
- [ ] P4 — please confirm the `confidence` cap is what you want at the
      Gateway-aggregation layer too, or counter-propose in a superseding record
