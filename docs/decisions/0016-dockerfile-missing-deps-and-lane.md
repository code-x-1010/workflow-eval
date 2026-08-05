# 0016 — `Dockerfile` had no owner and was missing dependencies (some since before this session)

**Author:** P1   **Date:** 2026-08-05   **Status:** accepted   **Affects:** P1, P2, P3, P4

## Context

Wiring L4 soundness into `services/validation/src/main.py` (decision-adjacent
work, see today's handoff entry) made that module import `l4_soundness.py`
unconditionally, which needs `pm4py`. That's when I noticed `Dockerfile`'s
install step is a hand-written flat list that had drifted out of sync with
`pyproject.toml`:

- Missing from the **base** list (not an extra -- these are unconditional
  dependencies): `lxml`, `xmlschema`, `networkx`, `arq`, `sqlalchemy`. `lxml`
  is what `wfeval-adapters` uses to parse BPMN at all, so `docker compose up`
  without `WFEVAL_STUB_DEPS=1` was likely already broken for Validation
  before this session, independent of anything I just added.
- Every optional extra (`validation`, `intent`, `sandbox`, `cost`) was
  entirely absent, so `pm4py`/`SpiffWorkflow`/`lark`/`hypothesis`/`tiktoken`
  were never installed in the container for any of the four services.

Separately, `scripts/check_ownership.py`'s `LANES` had no entry for
`Dockerfile` at all -- same shape of gap as decision 0012 (`tests/unit/**`),
just one file this time instead of a whole directory pattern.

## Decision

- Extended `Dockerfile`'s install line to match `pyproject.toml`'s base
  dependencies and all four extras. Kept the same flat-list style rather
  than switching to `uv pip install -r pyproject.toml` or similar, since
  there's no `[build-system]` section here (same reason decision 0007 ruled
  out a workspace install) and I can't test an actual Docker build in this
  environment to verify a syntax change works -- a mechanically-checkable
  list extension is the safe fix, not the elegant one.
- Added `Dockerfile` to P1's `LANES` in `check_ownership.py`, alongside
  `Makefile`/`pyproject.toml` which were already there for the same reason
  (project-wide build config, not any one service's).

## Consequences

- `docker compose up` (without `WFEVAL_STUB_DEPS=1`) should now actually
  have every package each service's code imports. **Not verified against a
  real Docker build** -- no `docker` binary in this environment. Whoever
  next runs `make dev-real` should treat this as the first real test of it.
- If any agent adds a new dependency to their extra in `pyproject.toml`,
  `Dockerfile`'s list needs a matching addition, or this will silently drift
  out of sync again exactly like this.

## Sign-off

- [x] P1
- [ ] P2 — awareness (your `hypothesis` extra is now in the image)
- [ ] P3 — awareness (your `SpiffWorkflow` extra is now in the image)
- [ ] P4 — awareness (your `tiktoken` extra is now in the image)
