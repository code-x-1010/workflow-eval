# 0014 — `test_testgen_may_not_import_the_ast` hard-coded the same wrong path decision 0013 fixed

**Author:** P1   **Date:** 2026-08-05   **Status:** accepted   **Affects:** P1, P2

## Context

A teammate reported `make contract` failing. Reproduced: `tests/contract/test_anti_circularity.py::test_testgen_may_not_import_the_ast`
asserts the literal substring `"intent.testgen"` is present in `.importlinter`.

Decision 0013 (yesterday) found that path was never valid in this repo —
services import as `services.<name>.src.*`, not a bare top-level package —
and corrected it to `services.intent.src.testgen` when commenting out the
contract pending P2's D9 work. That correction silently broke this test's
string match, since `"services.intent.src.testgen"` doesn't contain
`"intent.testgen"` as a substring.

This wasn't caught yesterday because I verified `lint-imports` directly
after the 0013 fix but didn't rerun `pytest tests/contract` afterward — the
gap this decision closes.

## Decision

Updated the test to check for the corrected path (`services.intent.src.testgen`)
instead of the old broken one. `tests/contract/` is `SHARED` (decision 0012),
so this is in-lane; kept the fix minimal — same assertion shape, corrected
string, docstring explaining why.

## Consequences

- `make contract` is green again.
- No change to decision 0013's plan: P2 still uncomments `importlinter:contract:2`
  with the corrected path at D9. This test will keep passing whether the
  contract is commented out (as now) or active (once P2 builds the module),
  since it only checks the path text is present, not enforcement state.

## Sign-off

- [x] P1
- [ ] P2 — awareness
