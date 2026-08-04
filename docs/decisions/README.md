# Decision records

Four agents run in separate sessions and cannot see each other. This directory is
the only channel for anything that affects a shared contract or another agent.

**When to write one**
- You need a change to `packages/wfeval-core/**` or `contracts/*.openapi.yaml` (frozen after D2)
- You need something from another agent
- You made a non-obvious choice a future session would otherwise re-litigate
- You discovered something about an external system (UiPath API shape, platform limits)

**When NOT to write one:** anything entirely inside your own lane. Put that in your handoff file.

Numbered sequentially. Never edit someone else's — append a superseding record instead.
Before claiming `NNNN`, check the highest number across *all* branches, not just
what you have checked out (`git fetch --all --prune`, then find the max prefix
under `docs/decisions/` across every remote ref) — four agents on isolated
branches can each see a different "next free" number otherwise (see 0011).

## Template

```markdown
# NNNN — Short title

**Author:** P<N>   **Date:** YYYY-MM-DD   **Status:** proposed | accepted | superseded by NNNN
**Affects:** P1, P3

## Context
What forced this decision. Be concrete.

## Decision
What we are doing.

## Consequences
What gets harder, what gets easier, what the other agents must now do differently.

## Sign-off
- [ ] P3 — needs to change trace capture
```
