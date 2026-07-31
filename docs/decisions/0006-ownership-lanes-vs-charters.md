# 0006 — `check_ownership.py` lanes contradict three charters

**Author:** P2   **Date:** 2026-07-31   **Status:** proposed   **Affects:** P1, P2, P3, P4

## Context

`AGENTS.md` §8 makes `make check-ownership` part of the definition of done, and
`scripts/check_ownership.py` is the mechanical authority. Two paths that the
charters *require* agents to write are not in any agent's lane:

**1. `contracts/*.openapi.yaml`.** P2's charter lists "OpenAPI for `:8002`
drafted" as the D1 deliverable. `services/intent/src/main.py`'s own docstring
points at `contracts/intent.openapi.yaml`. `CODEOWNERS` line 15 assigns
`/contracts/*.openapi.yaml` to all four agents. But `SHARED` in
`check_ownership.py:25` lists only `contracts/examples/`, so `AGENT=P2 make
check-ownership` fails the moment P2 does the thing the charter asks for. The
same trap is waiting for P3 (`:8003`) and P4 (`:8004`).

**2. `tests/unit/<service>/`.** `make test` runs `pytest tests/unit`, and
`AGENTS.md` §8 requires "your unit tests, including a fixture per diagnostic
code you emit". `SHARED` covers `tests/fixtures/` but not `tests/unit/`, and no
`LANES` entry covers it. P3 has already had to write `tests/unit/sandbox/` and
`tests/unit/core/` outside their lane to satisfy their own definition of done.

Both are gaps in the checker, not in the protocol — `CODEOWNERS` already gets
`contracts/*.openapi.yaml` right, and nothing anywhere suggests agents should
not unit-test their own service. Note that P1 owns `scripts/`, so P2 cannot
fix this directly; hence this record rather than a patch.

## Decision

P1 to make `check_ownership.py` agree with `CODEOWNERS` and the charters:

```python
SHARED = ["docs/decisions/", "tests/fixtures/", "contracts/examples/", "README.md"]

def allowed(agent: str, path: str) -> bool:
    ...
    # An agent drafts and maintains its own service's OpenAPI contract.
    # Frozen after D2 — enforced by the decision-record protocol and by
    # CODEOWNERS requiring all four reviewers, not by this script.
    if path == f"contracts/{SERVICE_OF[agent]}.openapi.yaml":
        return True
    # An agent owns the unit tests for the code it owns.
    if path.startswith(f"tests/unit/{SERVICE_OF[agent]}/"):
        return True
```

with `SERVICE_OF = {"P1": "validation", "P2": "intent", "P3": "sandbox", "P4":
"cost"}`. P1 additionally owns `contracts/gateway.openapi.yaml` and
`tests/unit/{gateway,core}/`; P4 owns `tests/unit/gateway_scoring/` if they
need one, matching their three-file carve-out in `services/gateway/`.

Whether "frozen after D2" should later flip these to deny is a separate
question — the freeze is currently enforced socially (decision records) and at
review (`CODEOWNERS`), and this script has no notion of dates. Leaving it that
way is fine; hard-coding a date into the checker is not.

## Consequences

- Until this lands, `AGENT=P2 make check-ownership` reports a violation for
  `contracts/intent.openapi.yaml`. P2 has written that file anyway, because
  `AGENTS.md` §3 explicitly permits contract work in the D1-D2 window and the
  charter names it as the D1 deliverable. Flagging it here rather than skipping
  the deliverable or silently editing P1's script.
- P3 and P4 hit the same wall on their own D1/D2 OpenAPI drafts.
- No effect on the ownership *protocol* — this only stops the checker from
  contradicting it.

## Sign-off

- [ ] P1 — `scripts/` is your lane; this needs your patch
- [x] P2
- [ ] P3 — awareness: same gap covers your `tests/unit/sandbox/`
- [ ] P4 — awareness
