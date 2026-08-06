# 0018 — `scripts/run_corpus.py` is referenced in three places and has never existed

**Author:** P2   **Date:** 2026-08-05   **Status:** proposed   **Affects:** P1, P2, P4

## Context

`make eval` fails immediately:

```
python: can't open file 'scripts/run_corpus.py': [Errno 2] No such file or directory
```

`git log --all -- scripts/run_corpus.py` is empty: the file has never existed on
any branch, and `scripts/` contains only `check_ownership.py`. Three things
already reference it as though it does:

- `Makefile:42` — the `eval` target.
- `.github/workflows/ci.yml:39` — the **nightly `corpus` job**. It is gated on
  `if: github.event_name == 'schedule'`, so it does not run on push and nobody
  has seen it fail. It has presumably been failing every night since the
  scaffold.
- `datasets/README.md:4` — which I wrote at D2, describing the corpus layout as
  "what `scripts/run_corpus.py --corpus datasets/corpus` expects". That was me
  writing to an interface that was specified but unbuilt; the layout does match
  the documented invocation, but the reader has no way to tell the script is
  missing until they run it.

I found this while verifying D4 — `make eval` was simply the next command after
`make test` / `make contract` / `check-ownership`, all of which are green.

## Decision

Recording it rather than writing the script. `scripts/` is not in P2's lane
(`check_ownership.py`'s `LANES` gives P2 `services/intent/`, `datasets/` and
`tests/unit/intent/`), and a corpus harness is not a five-minute file — it has
to drive `/v1/spec`, `/v1/intent` and `/v1/testcases`, decide what a run
*reports*, and agree with P4 on what feeds the scorecard. Writing it into
someone else's lane at my own guess of that shape is exactly the drift
`AGENTS.md` §2 exists to prevent.

## Why it matters before D10

P2's D10 deliverable is "corpus intent-alignment run; contribute findings to the
baseline writeup", and the corpus (40 pairs, `manifest.json`, `expected_diagnostics`
per case) has been sitting ready since D2. That deliverable is the harness plus
P2's half of the analysis. If the harness is still missing when D10 arrives, it
becomes P2's critical path on a day with no slack in it.

It also blocks the honest version of D5: `expected_diagnostics` is ground truth
for the `SPEC-*` codes, and scoring against it by hand across 40 cases is how you
end up not doing it.

## Proposed

1. **Someone owns `scripts/run_corpus.py`.** My read is P1, who owns `scripts/`,
   `Makefile` and CI today — but I would rather it be assigned deliberately than
   assumed.
2. **Until it exists, drop the nightly `corpus` job or mark it `continue-on-error`**,
   so the schedule is not permanently red. A job that always fails is a job
   nobody reads, and it will be masking a real regression by the time it matters.
3. If the answer is that P2 should write it after all, say so and I will — the
   corpus, the manifest and the `SPEC-*` registry are already mine, so it is a
   short step. It needs to be an explicit reassignment of `scripts/`, not me
   quietly committing into P1's lane.

I have left `datasets/README.md`'s reference in place: the documented invocation
is the right one, and rewording it to hide a missing script helps nobody.

## Addendum, 2026-08-06 (P1)

Wrote `scripts/run_corpus.py`. Kept ownership rather than reassigning — the
CLI shape the Makefile/CI already commit to (`--corpus`, `--out`) plus
Validation being P1's own service made this a natural fit once it was clear
what it should actually do.

Split exactly along the line `datasets/run_alignment.py`'s own docstring
already proposed: this script runs Validation's L1-L4 in-process against
every `reference.bpmn` (P1's tier), and **calls** `run_alignment.run_case`
for the intent numbers rather than reimplementing P2's differ/sufficiency/
testgen pipeline. Writes one `corpus_run.json` per run when `--out` is given,
prints a short summary either way, and always exits 0 — this is a regression
report, not a merge gate, matching the job already being `schedule`-only.

Verified live against the real corpus: 40/40 pass every Validation gate,
0/40 skipped on the intent side (`0021` fixed the 5 that used to skip on
`0020`). No `Makefile`/CI change needed — both already invoke exactly the
CLI this script implements.

## Sign-off

- [x] P2
- [x] P1 — wrote `scripts/run_corpus.py`, calling `run_alignment.run_case` per its own docstring
- [ ] P4 — awareness: `corpus_run.json`'s `validation`/`alignment` shape is what would feed a scorecard
