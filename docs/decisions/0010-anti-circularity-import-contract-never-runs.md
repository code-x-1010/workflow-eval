# 0010 — The anti-circularity import contract has never run, and `make lint` is red for everyone

**Author:** P2   **Date:** 2026-08-04   **Status:** proposed   **Affects:** P1 (owner of the fix), P2, P3, P4

## Context

`AGENTS.md` and my charter both describe the anti-circularity guarantee as
three-legged: the schema omits `artifact`, a contract test asserts it, and
`.importlinter` blocks `services/intent/src/testgen/**` from importing
`wfeval.core.ast` or any adapter — *"CI fails if you try."*

It does not. Running `lint-imports` for the first time this session (P1's
decision `0007` fix is what made it runnable at all):

```
$ lint-imports            # on main
Could not find package 'w' in your Python path.      # exit 1

$ lint-imports            # with P1's .importlinter reformat, branch p1/d2-contracts-and-ci-fix
Module 'intent.testgen' does not exist.              # exit 1
```

Two separate faults:

1. **On `main`, `root_packages = wfeval` is parsed as a character list** — hence
   "package 'w'". P1's branch already fixes this by moving the value onto its
   own indented line. Until that branch merges, `make lint` is red on `main` for
   all four of us, and every agent's definition of done (`AGENTS.md` §8) includes
   `make lint`.
2. **Even with that fixed, contract 2 does not run.** It declares
   `source_modules = intent.testgen`, but there is no importable top-level
   `intent` package — the service is `services.intent.src` (no `__init__.py`
   anywhere under `services/`, and the Dockerfile puts the repo root on
   `PYTHONPATH`). import-linter cannot resolve the module, so it errors out
   instead of checking anything. The contract has never passed *or* failed; it
   has never executed.

The result is that the leg of the guarantee described as the mechanical one is
the only leg not actually holding anything up. `tests/contract/test_anti_circularity.py`
greps `.importlinter` for the strings `intent.testgen` and `wfeval.core.ast`,
so it reports green on a contract that is inert.

## Decision

P1 to make contract 2 name a module that exists. Verified working — I applied
this in a scratch worktree, planted `services/intent/src/testgen/probe.py`
containing `from wfeval.core.ast import WorkflowAST`, and it failed correctly:

```ini
[importlinter]
root_packages =
    wfeval
    services          # <- added
...
[importlinter:contract:2]
name = Testgen may not see the workflow
type = forbidden
source_modules = services.intent.src.testgen     # <- was intent.testgen
forbidden_modules =
    wfeval.core.ast
    wfeval.adapters
```

```
Contracts: 1 kept, 1 broken.
services.intent.src.testgen is not allowed to import wfeval.core.ast:
-   services.intent.src.testgen.probe -> wfeval.core.ast (l.1)
```

No `__init__.py` files are needed; grimp resolves the namespace packages once
`services` is a declared root package. Contract 1 (`Core depends on nothing`)
is unaffected and still passes.

Two things P2 is *not* doing, deliberately:

- Not patching `.importlinter` — it is P1's lane (`LANES["P1"]`), and an edit
  P1 cannot see is exactly what this protocol exists to prevent.
- Not weakening `tests/contract/test_anti_circularity.py`'s string check. It is
  a coarse test but it is not wrong; it just cannot tell inert from enforced.

**P2 has added a stopgap in its own lane** (`tests/contract/test_intent_contract.py`,
`test_nothing_prompt_derived_imports_the_artifact_side`): a static scan of
`services/intent/src/{testgen/**,extract.py,cache.py}` for references to
`wfeval.core.ast`, `wfeval.adapters` and `wfeval.core.trace`. It runs today and
under `make contract`. It does **not** follow transitive imports, so it is a
stopgap and not a substitute — delete it if you would rather, once contract 2
is real, but do not delete it before.

## Consequences

- **P1, action required:** the three-line change above. Please keep it in the
  same PR as the `root_packages` reformat, since fault 1 without fault 2 fixed
  still leaves `lint-imports` exiting 1.
- **Everyone:** `make lint` is currently red on `main` regardless of what you
  changed. It is not your diff. It goes green when P1's branch lands *with* the
  fix above.
- Once contract 2 runs, `services/intent/src/testgen/` gains a real guard for
  the first time — relevant from D8, when that directory finally gets code in
  it. Today it is an empty directory, which is why nobody noticed.
- The wider lesson for the other two "enforced by CI" claims in `AGENTS.md`:
  a check that has never been executed is a comment. Worth someone confirming
  `make check-ownership` and `make contract` actually fail when they should —
  P1's `0008` found the same class of problem in `check_ownership.py`.

## Sign-off

- [ ] P1 — `.importlinter` is your lane; this needs your patch
- [x] P2 — reported, stopgap landed in `tests/contract/`
- [ ] P3 — awareness: `make lint` red on `main` is not your diff either
- [ ] P4 — awareness
