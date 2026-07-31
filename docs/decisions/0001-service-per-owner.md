# 0001 — Four services, one owner each

**Author:** P1  **Date:** 2026-07-30  **Status:** accepted  **Affects:** P1, P2, P3, P4

## Context
Four engineers, each running their own coding agent in a separate session, two weeks.
A single shared pipeline service would mean four agents editing the same files with no
visibility into each other's work.

## Decision
Four independently deployable services (Validation :8001, Intent & Testgen :8002,
Sandbox :8003, Cost :8004) plus a thin Gateway :8000. One owner each. All four import a
shared `wfeval-core` for types and parsing, so the hard part is written once and cannot
drift, but everything else is behind an HTTP boundary.

Coordination lives in the filesystem: frozen contracts, golden examples, decision records,
handoff notes. Enforced by CI (`import-linter`, contract tests, `check_ownership.py`).

## Consequences
- Only two genuine cross-team dependencies remain: P2→P3 (`TestCase`) and P3→P4 (`Actuals`).
  Both must be agreed by D2.
- P1 is a week-1 bottleneck on `wfeval-core`. Mitigated by a hard D2 freeze.
- Every agent must commit golden examples by D2 so nobody waits for anybody's implementation.
- Integration risk moves to D3 (the stub milestone) instead of week 2, where it would be fatal.

## Sign-off
- [x] P1  - [x] P2  - [x] P3  - [x] P4
