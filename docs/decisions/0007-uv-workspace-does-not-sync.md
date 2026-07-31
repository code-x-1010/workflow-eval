# 0007 — `uv sync --all-extras` fails; no workspace member has a manifest

**Author:** P2   **Date:** 2026-07-31   **Status:** proposed   **Affects:** P1, P2, P3, P4

## Context

The README quick start and every agent's local loop start with
`uv sync --all-extras`. It fails immediately:

```
error: Workspace member `/…/packages/wfeval-core` is missing a `pyproject.toml`
        (matches: `packages/*`)
```

`pyproject.toml` declares `[tool.uv.workspace] members = ["packages/*",
"services/*"]`, but none of those six directories has a `pyproject.toml` — they
are `src/`-only. So the workspace cannot resolve and no environment gets built.
`make test`, `make contract` and `make lint` are all unrunnable from a clean
checkout.

`docker compose` is unaffected: the `Dockerfile` bypasses the workspace
entirely with `uv pip install --system <explicit list>` plus a `PYTHONPATH`
that points at the `src/` trees. So `make dev` works while local testing does
not, which is why this can sit undetected.

Workaround, verified today (26 tests pass):

```bash
uv venv .venv -p 3.11
uv pip install fastapi 'pydantic>=2.9' httpx pyyaml pytest SpiffWorkflow lxml
PYTHONPATH=packages/wfeval-core/src:packages/wfeval-adapters/src:. \
  .venv/bin/python -m pytest tests/contract tests/unit -q
```

## Decision

P1 to make the documented setup work, either by adding a minimal
`pyproject.toml` to each of the six workspace members (each declaring its own
`[project]` name plus a hatchling/setuptools src layout), or — if per-member
packaging is more ceremony than a two-week project wants — by dropping
`[tool.uv.workspace]` and having the root `pyproject.toml` expose the `src/`
trees directly, e.g.

```toml
[tool.pytest.ini_options]
pythonpath = ["packages/wfeval-core/src", "packages/wfeval-adapters/src", "."]
```

The second is closer to "prefer boring" and matches what the `Dockerfile`
already does in practice. Either way `make lint` needs the same treatment —
`mypy --strict packages services` and `lint-imports` both need the packages
importable, and `.importlinter`'s `root_packages = wfeval` will not resolve
otherwise, which means **the anti-circularity import contract is currently not
being enforced by anything runnable**. That is the part of this worth caring
about.

## Consequences

- Until fixed, "`make test` passes" in `AGENTS.md` §8's definition of done is
  not literally checkable by a new session; agents will each improvise a
  different local setup, as P3 and P2 already have.
- `.importlinter` contract 2 (testgen may not import the AST) is one of the
  three enforcement legs of the anti-circularity rule. The other two —
  the schema having no `artifact` field, and
  `tests/contract/test_anti_circularity.py` — do run today, so the property is
  still guarded; but the leg that would catch an actual bad *import* is dark.
- P1 is the only agent who can fix this: `pyproject.toml`, `Makefile` and
  `packages/` are all in their lane.

## Sign-off

- [ ] P1 — your lane
- [x] P2
- [ ] P3 — awareness (you hit this too; your handoff implies a manual setup)
- [ ] P4 — awareness
