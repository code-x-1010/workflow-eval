# 0015 — `pm4py` (used for L4 soundness) is AGPL v3 licensed

**Author:** P1   **Date:** 2026-08-05   **Status:** proposed   **Affects:** whoever owns this project commercially

## Context

L4 soundness (`services/validation/src/l4_soundness.py`) converts a workflow
into a Petri net and runs `pm4py.check_soundness` (WOFLAN) to catch
deadlocks and dead activities. `pm4py` was already listed in `pyproject.toml`'s
`validation` extra before this session — it's the charter's own spec
("BPMN -> workflow net -> WOFLAN") and the only real Python implementation
of WOFLAN, so using it wasn't a new choice, just the first time anyone
actually installed and ran it.

It prints this on every import:

```
Welcome to PM4Py — Community Version
License: AGPL v3 — Commercial use requires open-sourcing your application.
Business use without open-sourcing? A commercial license is available.
```

`services/validation` is an HTTP service — exactly what AGPL v3's
network-use clause targets (unlike GPL, AGPL's copyleft triggers on serving
the software over a network, not just distributing it). Nobody has evaluated
this consequence for the project.

## Decision

Not mine to make. This is a legal/business call, not an engineering one —
flagging it here and in the handoff log rather than silently shipping it or
unilaterally ripping out the charter's specified approach. Left `pm4py` in
place because L4 soundness is real, tested, and useful today; a licensing
decision shouldn't block that from existing, but it should be made
consciously before this goes anywhere near production traffic.

## Consequences

- If AGPL is unacceptable: either purchase pm4py's commercial license, or
  replace `l4_soundness.py`'s Petri-net-and-WOFLAN approach with a
  hand-rolled soundness checker (state-space/marking exploration over the
  same Petri net this module already builds — the hard part, the BPMN to
  Petri net translation, doesn't change; only the soundness-checking
  algorithm at the end would need reimplementing).
- If AGPL is acceptable for this project's context: no action needed beyond
  this record existing, so the choice is documented as deliberate.

## Sign-off

- [ ] Project owner — decide and update Status above
- [x] P1 — flagged
