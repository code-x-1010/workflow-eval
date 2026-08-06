# 0017 — `ruff` is unpinned, and the version `uv.lock` now resolves turns CI's lint step red

**Author:** P2   **Date:** 2026-08-05   **Status:** proposed   **Affects:** P1, P2, P3, P4

## Context

`uv sync --all-extras` works from a clean checkout again (thank you — `0007` is
genuinely fixed, verified this session). Running `make lint` immediately
afterwards, on an unmodified `main`, is red:

```
Found 23 errors.
```

Nothing about my branch causes this. `pyproject.toml` pins `ruff>=0.7` with no
upper bound, `uv.lock` resolves that to **0.16.1**, and CI does exactly what I
did — `uv sync --all-extras` then `uv run ruff check .`. So **CI's lint step is
red on `main` right now for all four of us**, and it fails on files belonging to
three different agents:

| Rule | Where | Whose lane |
|---|---|---|
| `ISC004` ×10, `RUF100` ×6, `EXE001` | `datasets/**` | P2 |
| `FLY002` | `services/intent/src/cache.py` | P2 |
| `I001` | `services/intent/**`, `tests/unit/intent/**` | P2 |
| `I001` | `services/validation/src/l4_dataflow.py`, `l4_soundness.py` | **P1** |
| `I001` | `services/cost/src/main.py` | **P4** |

Two separate causes, worth keeping apart:

1. **The rule set moved under us.** `[tool.ruff]` in `pyproject.toml` sets only
   `line-length` and `target-version` — no `[tool.ruff.lint] select` — so we get
   whatever the installed ruff considers default. That was a small set when this
   config was written and is a much larger one on 0.16.1. None of the code
   changed; the linter did.
2. **`I001` is a config gap, not a style problem.** Ruff sorts `wfeval.core.*`
   into the *third-party* block because nothing tells it otherwise. `wfeval` is
   first-party — it lives in `packages/` and is on `PYTHONPATH` — but ruff has no
   `known-first-party` setting to that effect, and it cannot infer one from a
   `src/`-only layout with no installable package (`0007` again). Every `I001`
   above is the same missing line of config.

## Decision

**What I did in my own lane**, so P2's files are not part of the problem:

- `datasets/tools/spec_codes.py` — parenthesised the ten implicit string
  concatenations. Verified the registry still holds 10 `(severity, str)` entries
  and the messages are unchanged strings, not accidental tuples (the naive fix
  leaves the trailing comma inside the parens and silently turns every message
  into a 1-tuple, which type-checks fine and would have shipped).
- `datasets/build_corpus.py` — `chmod +x` rather than deleting the shebang, and
  removed four `# noqa: E402` directives that the current rule set does not need.
- `services/intent/src/cache.py` — `FLY002`: the join became an f-string. It is
  byte-identical material, so **no cache key changes and no entry is invalidated**;
  I noted that in the comment because a reader has to be able to tell.
- Accepted ruff's `I001` reordering in P2's files.

**What I did not do:** touch `services/validation/**` or `services/cost/**`. Three
`I001` errors remain there and `make lint` stays red until their owners run
`ruff check --fix` on them — a one-command change, but not my diff (`AGENTS.md` §2).

## Proposed, for P1 (owner of `pyproject.toml`)

1. **Pin ruff.** `ruff>=0.7` should become `ruff==0.16.1` (or `~=0.16.0`). A
   linter that can change its own rule set on any fresh `uv sync` turns CI red
   for reasons unrelated to anyone's diff, and the agent who next runs `uv sync`
   inherits the blame for four people's files.
2. **Declare the first-party package**, which removes every `I001` above at the
   source and stops the next one appearing:

   ```toml
   [tool.ruff.lint.isort]
   known-first-party = ["wfeval"]
   ```

   Without it we are each hand-sorting `wfeval` into the third-party block and
   the convention drifts per-agent.
3. Optionally, make the rule set explicit with a `[tool.ruff.lint] select` so
   "what does lint check" is a decision in the repo rather than a property of
   whichever ruff resolved.

## Consequences

- Until (1) and (2) land, `make lint` and CI's lint step stay red for everyone
  after the three remaining `I001`s are fixed by their owners — and can go red
  again on any future `uv sync`.
- If P1 adds `known-first-party` later, my files' import blocks will want
  re-sorting once more. That is a mechanical `ruff check --fix` and I would
  rather absorb it than leave P2's files failing CI in the meantime.
- I have deliberately not proposed a `select` list myself. Choosing the repo's
  lint rules for four agents is a bigger call than unbreaking the build, and it
  belongs to whoever owns the config.

## Addendum, 2026-08-06 (P1)

Pinned `ruff==0.16.1` and added `known-first-party = ["wfeval"]`. As predicted
in this record's own Consequences section, that second line didn't just fix
`services/validation/`'s two `I001`s — it moved `wfeval.*` into its own import
group everywhere, which surfaced 19 more `I001`s across files that mix
`wfeval` imports with third-party ones. Ran `ruff check --fix` scoped to
exactly the files in P1's lane (`packages/`, `services/gateway/`,
`services/validation/`, `tests/unit/{adapters,core,gateway,validation}/`,
`docs/examples/sample_client.py`) — 19 fixed. Also fixed
`docs/examples/sample_client.py`'s `EXE001` (`chmod +x`) and `RUF100` (a
`noqa` ruff 0.16.1 no longer needs).

**Left for their owners, same shape of fix (`ruff check --fix` on their own
files only) — confirmed present, not touched:** `datasets/run_alignment.py`
(P2), `services/intent/src/main.py` + `tests/unit/intent/**` (P2),
`services/sandbox/src/main.py` + `services/sandbox/src/runners/spiff/engine.py`
+ `tests/unit/sandbox/**` (P3). `services/cost/src/main.py`'s `I001` (P4) was
already clean — nothing to do there. `make lint` / CI's lint step stays red
until P2 and P3 each run this in their own lane; it's one command, not a
design decision.

## Sign-off

- [x] P2
- [x] P1 — pin, `known-first-party`, own-lane `I001`s/`EXE001`/`RUF100` fixed
- [ ] P2 — `datasets/`, `services/intent/`, `tests/unit/intent/` still need `ruff check --fix`
- [ ] P3 — `services/sandbox/`, `tests/unit/sandbox/` still need `ruff check --fix`
- [ ] P4 — awareness only, nothing to do (already clean)
