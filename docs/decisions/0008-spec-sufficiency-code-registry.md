# 0008 — SPEC-* sufficiency code registry

**Author:** P2   **Date:** 2026-08-03   **Status:** proposed
**Affects:** P1 (awareness), the generation team (keys repair logic off these strings)

## Context

`SPEC` is P2's prefix in `PREFIX_OWNER` (`wfeval.core.diagnostics`), and that
file states the rule the registry has to live by: *"the generation team keys
their repair logic off these strings, so codes are append-only. Never rename or
repurpose an existing code."*

Exactly one `SPEC-*` code exists in the repo today —
`SPEC-NO-ERROR-BEHAVIOUR`, in `contracts/examples/spec.response.json`. The
implementation that emits these is D5.

D2 forced the issue earlier than D5. The corpus that landed today records, per
case, the codes `/v1/spec` is expected to raise for that prompt — that is the
ground truth the D5 work will be scored against, and 39 of the 40 cases carry
at least one. Ground truth cannot reference codes that do not exist, and
inventing them case-by-case while writing D5 would produce a registry shaped by
whatever order the fixtures happened to be written in.

## Decision

Ten codes, declared now, in `datasets/tools/spec_codes.py` (the corpus
`--check` verifies every `expected_diagnostics` entry against it, so the two
cannot drift):

| Code | Sev | Raised when |
|---|---|---|
| `SPEC-NO-TRIGGER` | warning | The prompt never says what starts the process. |
| `SPEC-NO-ERROR-BEHAVIOUR` | warning | A side-effecting step has no stated failure behaviour. |
| `SPEC-AMBIGUOUS-CONDITION` | warning | A branch condition is qualitative with no threshold. |
| `SPEC-UNBOUNDED-INPUT` | warning | A collection or loop has no volume bound. |
| `SPEC-NO-TERMINAL-STATE` | warning | A loop or wait has no exit condition, cap or timeout. |
| `SPEC-UNSPECIFIED-INTEGRATION` | warning | An external system is referred to but not named. |
| `SPEC-AMBIGUOUS-ACTOR` | warning | A human step names no role. |
| `SPEC-CONTRADICTORY-REQUIREMENT` | warning | Two statements cannot both be satisfied. |
| `SPEC-UNSTATED-SLA` | info | A timing expectation is implied without a duration. |
| `SPEC-NO-BUDGET` | info | No per-instance cost ceiling was stated. |

**Severity rule for this prefix.** `warning` when a downstream tier will
silently produce a wrong-looking number because of the gap; `info` when it only
costs advice quality. **Nothing in this prefix is ever an `error`** — an
under-specified prompt is a normal thing for a user to send. It is not a
validation failure and must not block a gate. The severity ladder here describes
*our* inability to evaluate confidently, not the user's inability to write.

Two of these earn their place by protecting a specific downstream tier:

- `SPEC-AMBIGUOUS-CONDITION` is what stands between D8 and a tautology. The
  charter is explicit that boundary cases come from the spec's numeric
  conditions, not from imagination. Given "big orders go to a manager" there is
  no number to work from, and a generator that invents 1000 then emits
  999/1000/1001 is testing its own guess and reporting confidence about it.
  Raise the diagnostic, generate no boundary cases.
- `SPEC-UNSPECIFIED-INTEGRATION` blocks D9. "Put it in the system" yields no
  asset reference, so no `MockDefinition` and no `asset_ref`-keyed `TaskStub`
  can be derived, and P3's WireMock has nothing to seed.

## Consequences

- **Append-only from here.** A future session that wants a finer distinction
  adds a code; it does not re-cut this list. Two codes that overlap slightly are
  cheaper than one renamed code silently breaking someone's repair logic.
- **P2, D5:** these are the codes to implement, and
  `datasets/corpus/manifest.json` already says which prompts should raise which.
  A code with no corpus case is a code with no test.
- **P1, awareness only, no action:** `SPEC-*` severities are all
  warning/info by construction, so nothing here can block a Gateway gate. If
  gate logic ever assumes a prefix can produce `error`, `SPEC` is not one.
- **Generation team:** these strings are stable and safe to key repair logic
  off. The `info` two are advisory — a prompt with no stated budget is fine,
  it just means Cost has nothing to gate against.
- The registry currently lives in `datasets/tools/spec_codes.py` because that
  is inside P2's lane and the corpus needs it today. When `/v1/spec` is
  implemented at D5 it moves to `services/intent/src/`, still P2's lane, and
  the corpus imports it from there. No `packages/**` change is requested — this
  is not a frozen-contract change, and `wfeval.core.diagnostics` deliberately
  keeps `code` a free string with ownership enforced by prefix.

## Sign-off

- [x] P2
- [ ] P1 — awareness only; confirm no gate logic expects `SPEC-*` to reach `error`
