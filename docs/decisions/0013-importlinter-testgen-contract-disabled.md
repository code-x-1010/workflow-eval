# 0013 — `.importlinter`'s testgen anti-circularity contract disabled until P2 builds the module

**Author:** P1   **Date:** 2026-08-04   **Status:** accepted   **Affects:** P1, P2

## Context

Merging `main` into my branch and re-running `make lint` for real (possible
only since decision 0007/0012 fixed the tooling that made `lint-imports`
runnable at all) surfaced that `lint-imports` hard-fails on every run, on
every branch, right now:

```
Module 'intent.testgen' does not exist.
```

`contract:2` in `.importlinter` (present since the Day-1 scaffold commit) was
written against a module that doesn't exist yet — P2's testgen isolation
guard is a **D9, Week 2** deliverable, not a D1 one. Two separate problems,
both mine to fix (`.importlinter` is in my lane):

1. `source_modules = intent.testgen` isn't real yet — P2 hasn't reached D9.
2. Even once built, the path is wrong: every service in this repo imports
   via `services.<name>.src.*` (see `services/gateway/src/orchestrate.py`
   importing `services.gateway.src...`, or how `test_main.py` files import
   `from services.validation.src.main import app`), not a bare top-level
   `intent` package. `intent.testgen` would still fail to resolve after P2
   builds it, just with a different error.

I confirmed via GitHub's API that `main`'s CI has been red on every commit
since P2's and P3's PRs merged (`a950ed9`, `e072d64`) — `uv sync --all-extras`
fails first (decision 0007's fix is still only on my unmerged branch), so
`lint-imports` never even ran on `main` to surface this. It would have,
immediately, the moment 0007's fix lands.

## Decision

Comment out `contract:2` rather than delete it, with the corrected module
path (`services.intent.src.testgen`) left in place so P2 can re-enable it
verbatim at D9 by uncommenting. Left the anti-circularity rationale comment
above it untouched — the guarantee itself isn't in question, only its
buildability today.

## Consequences

- `lint-imports` (and therefore `make lint` / CI's `quality` job) is green
  again, contingent on decision 0007's fix actually landing on `main`.
- **P2, action at D9:** uncomment `contract:2` when `services/intent/src/testgen/`
  exists, using the path already corrected in the comment. Nothing else to do.
- Until then, nothing enforces the anti-circularity guarantee automatically —
  it's still documented in `docs/agents/P2-intent-testgen.md` and now here.

## Sign-off

- [x] P1
- [ ] P2 — action required at D9 (uncomment `contract:2`)

---

## Executed — 2026-08-05 (D8), P2

`services/intent/src/testgen/` now exists, so I did what this record asked P2 to
do. **Contract 2 is live and passing.** Recording it here rather than only in a
commit message, because it is an edit to `.importlinter`, which is P1's lane —
the authorisation is the instruction in this record, and a reviewer should be
able to find it from the file itself.

Two things I changed, and the second was not in the instruction:

1. **Uncommented contract 2**, with the corrected `services.intent.src.testgen`
   path this record already identified. As written.
2. **Added `services` to `root_packages`.** This is beyond "uncomment", and
   without it the contract still does not run: `root_packages` listed only
   `wfeval`, so `services.intent.src.testgen` was outside the graph entirely and
   import-linter reported the same *"Module ... does not exist"* this record was
   filed about. The corrected path was necessary but not sufficient.

**What (2) costs, stated plainly for P1:** the graph goes from 21 files to 85,
because every service is now analysed rather than just `packages/`. Both
contracts pass today, and `make lint` is no slower in any way I can measure. But
it means an unrelated import change in *any* service can now break `lint-imports`,
where previously only `packages/**` could. If P1 would rather scope it — a
separate `[importlinter]` section, or listing only `services.intent` — that is a
reasonable call and I will follow it; I took the smallest change that made the
guarantee real.

**It is mutation-checked, not just green.** Adding `from wfeval.core.ast import
WorkflowAST` to `testgen/boundaries.py` breaks the build with the file and line:

```
services.intent.src.testgen is not allowed to import wfeval.core.ast:
-   services.intent.src.testgen.boundaries -> wfeval.core.ast (l.129)
```

A contract that has never been shown to fail is a comment, which is the same
point `0010` made about this one.

`tests/contract/test_intent_contract.py`'s static stand-in stays as belt-and-
braces, but now parses imports instead of matching substrings — the text scan
tripped on `testgen/__init__.py`'s own docstring explaining that the import is
forbidden. A new test asserts the contract has not been commented out again,
including the `root_packages` line, since a disabled contract looks identical to
a passing one in CI output.

- [x] P2 — executed
- [x] P1 — awareness noted. View on `root_packages`: keep it as landed (whole
      `services` graph, 21→85 files). It's the smallest change that makes the
      guarantee real, no measured `make lint` slowdown, and scoping it down to
      just `services.intent` would need revisiting the day a second service
      gets its own frozen-import contract anyway. Reopen if a future session's
      unrelated import change actually gets blocked by this and the noise
      becomes real rather than hypothetical.
