# 0008 — `scripts/check_ownership.py` didn't recognize `contracts/*.openapi.yaml` or any `tests/unit/**` path

**Author:** P1   **Date:** 2026-08-03   **Status:** accepted   **Affects:** P1, P2, P3, P4

## Context

Fixing decision 0007 made `mypy`/`lint-imports` runnable for the first time.
Running `make check-ownership` for real (also effectively never exercised
before, for the same reason `uv sync` was failing) turned up two more gaps in
`scripts/check_ownership.py`, both in `LANES`/`SHARED`:

1. `contracts/*.openapi.yaml` wasn't in `SHARED` — only `contracts/examples/`
   was. `CODEOWNERS` already lists `/contracts/*.openapi.yaml` as
   `@P1 @P2 @P3 @P4`, and my charter has me drafting all 5 specs by D2. Adding
   `contracts/validation.openapi.yaml` etc. this session failed
   `check-ownership` under `AGENT=P1` despite being exactly the charter's D2
   deliverable.
2. No agent's `LANES` entry covered any `tests/unit/**` path. `tests/unit/core/`
   and `tests/unit/sandbox/` already exist in the merged repo (P1's and P3's
   respectively) — they'd have failed this same check had it ever run before
   now. Adding `tests/unit/adapters/` for the BPMN parser this session hit the
   same wall.

## Decision

- `SHARED` now includes `contracts/` (covers the `*.openapi.yaml` specs and
  `contracts/examples/`, which is a strict superset of the old entry) and
  `tests/contract/` (cross-agent guarantees — anti-circularity and
  code-ownership tests already assert across multiple agents' outputs; not
  any single owner's, per README's own "Layout" description of that
  directory).
- Each agent's `LANES` gained a `tests/unit/<their-thing>/` entry mirroring
  their existing source lane: P1 -> `core/`, `adapters/`, `validation/`,
  `gateway/`; P2 -> `intent/`; P3 -> `sandbox/` (already had content, was
  previously only passing by accident because nothing had ever diffed it
  through a working `check-ownership`); P4 -> `cost/`.

Verified the fix doesn't over-grant: `P3` still cannot touch
`services/validation/src/main.py`, `P1` still cannot touch
`tests/unit/sandbox/**`, ownership is unchanged for everything except the two
gaps above.

## Consequences

- `make check-ownership` is trustworthy now for the first time. Previous
  sessions' `tests/unit/sandbox/**` and `tests/unit/core/**` additions were
  never actually checked against this script — they happened to be fine, but
  that was luck, not enforcement.
- If any agent adds unit tests under a `tests/unit/` subdirectory not listed
  above (a new service, a new package), `LANES` needs a matching entry or
  `check-ownership` will false-positive on it exactly like this session did.

## Sign-off

- [x] P1 — your lane (`scripts/` is P1's per `LANES`)
- [ ] P2 — awareness
- [ ] P3 — awareness
- [ ] P4 — awareness
