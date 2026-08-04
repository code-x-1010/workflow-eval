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
