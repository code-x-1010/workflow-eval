# 0011 — Two records claim `0008`; how to stop four isolated agents colliding on numbers

**Author:** P2   **Date:** 2026-08-04   **Status:** proposed   **Affects:** P1 (rename), P2, P3, P4

## Context

There are two `0008` records:

| File | Author | Where |
|---|---|---|
| `0008-spec-sufficiency-code-registry.md` | P2 | merged to `main` (PR #3, `6fb802c`) |
| `0008-check-ownership-missing-lanes.md` | P1 | unmerged, `p1/d2-contracts-and-ci-fix` |

Neither agent did anything wrong. P1 branched from `7aa2204`, which is before
P2's D2 work merged, so `0008` was genuinely free when P1 claimed it. This is
structural: `docs/decisions/README.md` says "numbered sequentially", and four
agents who cannot see each other each pick the next number from whatever they
can see. Sequential numbering assumes a single writer.

It matters because the numbers are load-bearing as cross-references, not just
labels. `0008` (P2's) is cited from `datasets/corpus/manifest.json`
(`spec_code_registry`), `datasets/README.md`, `services/intent/src/main.py`, and
the merge commit message. `0008` (P1's) is cited from P1's handoff and from
their commit `a795de3` ("decision 0008"). After both land, every one of those
references is ambiguous.

## Decision

**This instance:** P2's `0008` stays (it is on `main` and has live references
from committed data files). **P1's record becomes `0012`** — the next free
number after this one — and its two in-repo references (`docs/handoff/P1.md` and
the commit body, which can be left as-is with a note) point at `0012`. P2 is not
renaming P1's file: it is on P1's branch and P1 cannot see this session.

`0010` and `0011` are P2's, filed today. So the next free number for anyone is
**`0012`**, which is the one P1 should take.

**Going forward:** before claiming `NNNN`, take the number from *all* branches,
not just from what is checked out:

```bash
git fetch --all --prune
git ls-tree -r --name-only $(git for-each-ref --format='%(refname)' refs/remotes) -- docs/decisions/ \
  | sed 's#.*/##' | cut -d- -f1 | sort -u | tail -1
```

That is a two-second command and it would have caught this. Deliberately *not*
proposing per-agent number blocks (P1 = 01xx, P2 = 02xx, …): it solves the
collision but makes the sequence unreadable, and `0001`–`0011` are already
mixed-author, so we would be maintaining two schemes forever.

The rule belongs in `docs/decisions/README.md` next to "Numbered sequentially",
which is everyone's lane to edit but nobody's to own — P2 has not added it
there, to avoid a fifth thing to reconcile at merge time. Whoever merges next
should add it.

## Consequences

- **P1, action required, before your branch merges:** `git mv
  docs/decisions/0008-check-ownership-missing-lanes.md
  docs/decisions/0012-check-ownership-missing-lanes.md`, update the heading, and
  update the reference in `docs/handoff/P1.md`. Nothing else in the repo cites
  it. Your `scripts/check_ownership.py` fix itself is unaffected and already
  verified from P2's side — `AGENT=P2 python scripts/check_ownership.py` passes
  on this session's branch with your version of the script and fails with
  `main`'s, exactly as your record predicts.
- Git will not warn about this: the filenames differ, so it merges clean and
  the duplicate only shows up when a human reads the directory.
- No effect on any code or contract.

## Sign-off

- [ ] P1 — the rename is yours; your record's content is not in dispute
- [x] P2
- [ ] P3 — awareness: check all branches before you claim a number
- [ ] P4 — awareness
