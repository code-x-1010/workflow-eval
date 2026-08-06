# 0020 — `docs/integration-guide.md`, `docs/runbook.md`, `docs/examples/` had no owner

**Author:** P1   **Date:** 2026-08-06   **Status:** accepted   **Affects:** P1

## Context

Same shape of gap as decisions 0012 (`tests/unit/**`) and 0016
(`Dockerfile`), found the same way: writing the actual D10 deliverable and
checking `check-ownership` against it. The charter explicitly assigns
`docs/integration-guide.md` to P1 (D10: "Handoff: OpenAPI bundle,
`docs/integration-guide.md`, sample client, runbook"), but `scripts/check_ownership.py`'s
`LANES`/`SHARED` had no entry for any top-level `docs/*.md` outside
`docs/decisions/`, `docs/handoff/`, `docs/agents/` -- `allowed('P1',
'docs/integration-guide.md')` returned `False` before this fix.

Also worth recording precisely: `changed_files()` diffs `main...HEAD`, which
only sees **committed** history, not untracked working-tree files -- so this
gap was invisible when I ran `check-ownership` against the still-uncommitted
D10 files. It would have surfaced the moment I committed. Fixed before that
happened, but future sessions should know `check-ownership` run against
uncommitted new files can false-pass for this reason -- it's not a
guarantee until after `git add`/commit.

## Decision

Added `docs/integration-guide.md`, `docs/runbook.md`, `docs/examples/` to
P1's `LANES`. Not added to `SHARED` -- unlike `tests/fixtures/`/`contracts/`,
these aren't cross-agent-authored artifacts, they're a single charter-assigned
deliverable with one clear owner.

## Consequences

- `check-ownership` now actually covers every file this session created for
  D10.
- If a future session adds more top-level `docs/*.md` files with a
  different natural owner (e.g. a P2-specific guide), that file needs its
  own `LANES` entry too -- this fix is scoped to the three D10 paths, not a
  blanket `docs/` grant.

## Sign-off

- [x] P1
