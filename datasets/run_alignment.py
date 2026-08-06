#!/usr/bin/env python3
"""Run P2's whole pipeline over the corpus and report what it finds. D10.

    python datasets/run_alignment.py            # summary to stdout
    python datasets/run_alignment.py --json     # machine-readable, for the scorecard
    python datasets/run_alignment.py --case c01_invoice_approval   # one case, verbose

Lives under `datasets/` rather than in `scripts/run_corpus.py` deliberately.
That script is referenced by the Makefile, the nightly CI job and
`datasets/README.md`, and **has never existed** (`docs/decisions/0018`) --
`scripts/` is P1's lane and a corpus harness is not a file to drop into someone
else's directory at my own guess of its shape. This is P2's half: the intent
tier, over P2's corpus, in P2's lane. When `scripts/run_corpus.py` lands it
should call this rather than reimplement it.

## Three things this is careful about

**Reference artifacts are not generator output.** The 30 reverse-generated cases
were built artifact-first, then described -- so the reference is what a *perfect*
generator would emit for that prompt. Alignment against it is therefore a
measure of **P2's own differ**, not of any generator's quality. Reading these
numbers as "the generator scores 0.77" would be exactly wrong, and the report
says so at the top rather than in a footnote.

**Under-specified prompts are scored separately.** The ten hand-written cases
carry `reference_is_ground_truth: false`: an ambiguous prompt has several
defensible expansions and scoring alignment strictly against one reading punishes
a generator for choosing differently. They are reported apart, and what they
actually measure is whether `/v1/spec` raises the right `SPEC-*` codes.

**Unparseable artifacts are skipped, not zeroed.** Five reference artifacts hit
`0020` (the adapter rejects error boundary events). Scoring them zero would
attribute P1's adapter gap to output quality -- the same class of wrong-looking
number the whole `SPEC-*`/`INT-*` severity design exists to avoid.

Owner: P2.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
for path in (ROOT, ROOT / "packages" / "wfeval-core" / "src", ROOT / "packages" / "wfeval-adapters" / "src"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from services.intent.src.align import align
from services.intent.src.extract import extract
from services.intent.src.judge import LexicalJudge, calibrate
from services.intent.src.sufficiency import diagnose
from services.intent.src.testgen import generate
from wfeval.adapters import AdapterParseError, parse

CORPUS = ROOT / "datasets" / "corpus"


@dataclass
class CaseResult:
    id: str
    under_specified: bool
    reference_is_ground_truth: bool
    skipped: str | None = None
    expected_diagnostics: list[str] = field(default_factory=list)
    actual_diagnostics: list[str] = field(default_factory=list)
    scores: dict[str, float] = field(default_factory=dict)
    int_codes: list[str] = field(default_factory=list)
    cases_generated: int = 0
    boundary_cases: int = 0
    mocks: int = 0


def run_case(entry: dict[str, Any]) -> CaseResult:
    prompt = (CORPUS / entry["prompt_path"]).read_text()
    result = CaseResult(
        id=entry["id"],
        under_specified=entry["under_specified"],
        reference_is_ground_truth=entry["reference_is_ground_truth"],
        expected_diagnostics=sorted(entry["expected_diagnostics"]),
    )

    spec = extract(prompt)
    result.actual_diagnostics = sorted(d.code for d in diagnose(prompt, spec))

    cases, mocks = generate(spec, prompt)
    result.cases_generated = len(cases)
    result.boundary_cases = sum(1 for c in cases if c.kind.value == "boundary")
    result.mocks = len(mocks)

    try:
        ast = parse((CORPUS / entry["reference_path"]).read_text())
    except AdapterParseError as exc:
        # docs/decisions/0020. Skipped, never scored zero.
        result.skipped = str(exc).split("(")[0].strip()
        return result

    alignment = align(spec, ast, prompt)
    result.scores = alignment.scores
    result.int_codes = sorted(d.code for d in alignment.diagnostics)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument("--case", help="run one case verbosely")
    args = parser.parse_args()

    manifest = json.loads((CORPUS / "manifest.json").read_text())
    entries = manifest["cases"]
    if args.case:
        entries = [e for e in entries if e["id"] == args.case]
        if not entries:
            print(f"no such case: {args.case}", file=sys.stderr)
            return 2

    results = [run_case(entry) for entry in entries]
    calibration = calibrate(LexicalJudge())

    if args.json:
        print(json.dumps({
            "results": [asdict(r) for r in results],
            "judge_agreement": calibration.agreement,
            "judge": calibration.judge,
        }, indent=2))
        return 0

    _report(results, calibration)
    return 0


def _report(results: list[CaseResult], calibration: Any) -> None:
    total = len(results)
    skipped = [r for r in results if r.skipped]
    scored = [r for r in results if not r.skipped]
    ground_truth = [r for r in scored if r.reference_is_ground_truth]
    ambiguous = [r for r in scored if not r.reference_is_ground_truth]

    print("=" * 78)
    print("P2 INTENT BASELINE — corpus run")
    print("=" * 78)
    print()
    print("READ THIS FIRST: the reference artifacts are what a *perfect* generator")
    print("would emit — 30 of 40 were built artifact-first, then described. These")
    print("numbers measure P2's differ, not any generator's quality.")
    print()

    # --- sufficiency ---
    tp = sum(len(set(r.actual_diagnostics) & set(r.expected_diagnostics)) for r in results)
    fp = sum(len(set(r.actual_diagnostics) - set(r.expected_diagnostics)) for r in results)
    fn = sum(len(set(r.expected_diagnostics) - set(r.actual_diagnostics)) for r in results)
    exact = sum(1 for r in results if set(r.actual_diagnostics) == set(r.expected_diagnostics))
    print("SUFFICIENCY (SPEC-*), against expected_diagnostics written at D2")
    print(f"  precision {tp / (tp + fp) if tp + fp else 1.0:.3f}   "
          f"recall {tp / (tp + fn) if tp + fn else 1.0:.3f}   "
          f"exact-set {exact}/{total}")
    print()

    # --- alignment ---
    print(f"ALIGNMENT (INT-*), {len(scored)}/{total} cases  "
          f"({len(skipped)} skipped: adapter cannot parse — decision 0020)")
    for label, group in (("reference is ground truth", ground_truth), ("under-specified", ambiguous)):
        if not group:
            continue
        coverage = [r.scores.get("intent_coverage", 0.0) for r in group]
        step = [r.scores.get("step_coverage", 0.0) for r in group]
        print(f"  {label:26} n={len(group):2}  "
              f"intent_coverage mean {statistics.mean(coverage):.3f} "
              f"median {statistics.median(coverage):.3f}   "
              f"step_coverage mean {statistics.mean(step):.3f}")
    print()

    # --- the ranked list the charter asks for ---
    print("MOST COMMON INTENT FINDINGS  (the D10 deliverable)")
    codes = Counter(code for r in scored for code in r.int_codes)
    for code, count in codes.most_common():
        cases_hit = sum(1 for r in scored if code in r.int_codes)
        print(f"  {count:4d} occurrences, {cases_hit:2d}/{len(scored)} cases   {code}")
    print()

    # --- generation ---
    print("TEST GENERATION")
    print(f"  {sum(r.cases_generated for r in results)} cases over {total} prompts "
          f"({sum(r.boundary_cases for r in results)} boundary, "
          f"{sum(r.mocks for r in results)} mocks)")
    silent = [r.id for r in results if r.cases_generated == 0]
    if silent:
        print(f"  {len(silent)} prompts yielded NO cases: {', '.join(silent)}")
    print()

    print("JUDGE")
    print(f"  {calibration.judge}: agreement {calibration.agreement:.3f} over {calibration.n} pairs")
    if not calibration.trustworthy:
        print(f"  NOT TRUSTWORTHY — {calibration.warning}")
    print()

    if skipped:
        print("SKIPPED")
        for result in skipped:
            print(f"  {result.id}: {result.skipped}")


if __name__ == "__main__":
    raise SystemExit(main())
