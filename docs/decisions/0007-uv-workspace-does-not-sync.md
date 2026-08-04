# 0007 — `uv sync --all-extras` fails; no workspace member has a manifest

**Author:** P2   **Date:** 2026-07-31   **Status:** accepted   **Affects:** P1, P2, P3, P4

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

## Resolution (P1, 2026-07-31)

Took the second option: dropped `[tool.uv.workspace]` entirely, added
`pythonpath = [...]` under `[tool.pytest.ini_options]` in `pyproject.toml`, and
exported the same `PYTHONPATH` (`packages/wfeval-core/src:packages/wfeval-adapters/src:.`,
matching the `Dockerfile`) at the top of the `Makefile` so `mypy`/`lint-imports`
see it too — those don't go through pytest's ini machinery. `.github/workflows/ci.yml`
got the same `PYTHONPATH` as a job-level `env:` since it calls `uv run mypy` /
`uv run lint-imports` directly rather than through `make`.

**This was the first time `mypy --strict packages services` and `lint-imports`
had ever actually executed in this repo** — previously they died immediately on
unrelated errors before reaching real content. Fixing that surfaced three more
pre-existing bugs, all now fixed in this session:

1. `mypy --strict` collided on `services/*/src/main.py` all resolving to the
   same top-level module name `main` (no `__init__.py` anywhere under
   `services/`). Fixed with `explicit_package_bases = true` +
   `namespace_packages = true` in `[tool.mypy]`.
2. `[tool.mypy]` had no `plugins = ["pydantic.mypy"]`. Without it, mypy
   mis-read `Diagnostic`'s defaulted fields as required constructor args —
   false positives on any `Diagnostic(...)` call that relied on a default.
3. `.importlinter`'s `root_packages = wfeval` was a bare single-line value;
   import-linter needs the list form (`root_packages =\n    wfeval`) or it
   iterates the string character-by-character and fails looking for a package
   named `w`. Fixed.

Once mypy could actually run, it found **23 real strict-mode violations**,
all in code I don't own and won't touch: `services/sandbox/**` (P3, mostly
`list`/`dict`/`set` missing type args, one missing return annotation),
`services/intent/src/main.py` (P2), `services/cost/src/main.py` (P4). I fixed
the equivalent findings in my own files (`wfeval.core.stubs.golden`,
`services/validation/src/main.py`, `services/gateway/src/main.py`) plus two
ruff `PLW1510` findings and an import-order issue in `scripts/check_ownership.py`.
`make lint` will stay red until P2/P3/P4 each clean up their own files —
flagging this to each of you rather than filing per-agent decision records for
what is, in every case, a one-line strict-mode fix.

Separately: `lint-imports` now runs but still fails on contract 2 —
`Module 'intent.testgen' does not exist` — because `services/intent/src/testgen/`
hasn't been created yet. That's expected pre-D2/3 and not a bug; it'll clear
itself once P2 scaffolds that package. Not fixing it here since `services/intent/`
is outside my lane.

Verified locally with a plain venv, since `uv` isn't installed in this
environment: `python3 -m venv .venv && .venv/bin/pip install fastapi pydantic
httpx pyyaml pytest ruff mypy import-linter lxml xmlschema networkx
SpiffWorkflow pytest-asyncio`, then `pytest tests/unit tests/contract` (26
passed) and the `mypy`/`ruff`/`lint-imports` commands above.

## Sign-off

- [x] P1 — fixed, see Resolution above
- [x] P2
- [ ] P3 — awareness: `services/sandbox/**` now has 20 real mypy --strict findings blocking `make lint`, see Resolution above
- [ ] P4 — awareness: `services/cost/src/main.py` (3 findings) and `services/intent/src/main.py` (3 findings, that one's P2) block `make lint` too
