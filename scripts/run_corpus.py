#!/usr/bin/env python3
"""Nightly corpus regression: Validation's four tiers + P2's intent alignment,
over every (prompt, reference artifact) pair in datasets/corpus/.

    python scripts/run_corpus.py --corpus datasets/corpus
    python scripts/run_corpus.py --corpus datasets/corpus --out reports/
    python scripts/run_corpus.py --corpus datasets/corpus --case c01_invoice_approval

Referenced by the Makefile's `eval` target and the nightly `corpus` CI job
since the scaffold, but never actually built -- see docs/decisions/0018.

Two tiers, two owners, one report:

- Validation (L1-L4, this file, P1's own service) runs in-process against
  every reference.bpmn -- these artifacts are exactly what Validation exists
  to check.
- Intent alignment is `datasets/run_alignment.run_case` (P2's D10 script) --
  called, not reimplemented, per that module's own docstring: "When
  scripts/run_corpus.py lands it should call this rather than reimplement
  it." Reference artifacts are what a *perfect* generator would emit for the
  prompt, so the intent numbers measure P2's differ, not any generator's
  quality -- see run_alignment.py for the full caveat, and run it directly
  for the complete intent breakdown; this script only summarises it.

This is a regression report, not a merge gate: a corpus case failing a
Validation gate is itself a finding (a "perfect" reference artifact failing
schema/reference/structure checks means either the fixture or the checker is
wrong), so the script always exits 0 and leaves reading the report to a
human -- consistent with the nightly job already being schedule-only, not
required-on-push.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
for path in (ROOT, ROOT / "packages" / "wfeval-core" / "src", ROOT / "packages" / "wfeval-adapters" / "src"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from datasets.run_alignment import run_case as run_alignment_case
from services.validation.src.main import validate


def run_validation(corpus: Path, entry: dict[str, Any]) -> dict[str, Any]:
    content = (corpus / entry["reference_path"]).read_text()
    body = {"artifact": {"format": "bpmn", "content": content}, "platform": "uipath_maestro"}
    report = validate(body)
    return {
        "gates": report["gates"],
        "scores": report["scores"],
        "diagnostic_codes": sorted(d["code"] for d in report["diagnostics"]),
        "tiers_run": report["tiers_run"],
        "tiers_skipped": report["tiers_skipped"],
    }


def run_all(corpus: Path, entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    results = []
    for entry in entries:
        alignment = run_alignment_case(entry)
        results.append({
            "id": entry["id"],
            "validation": run_validation(corpus, entry),
            "alignment": {
                "skipped": alignment.skipped,
                "scores": alignment.scores,
                "int_codes": alignment.int_codes,
            },
        })
    return results


def _report(results: list[dict[str, Any]]) -> None:
    total = len(results)
    print("=" * 78)
    print("CORPUS REGRESSION -- Validation (L1-L4) + intent alignment summary")
    print("=" * 78)
    print()

    gate_fail = [r for r in results if not all(r["validation"]["gates"].values())]
    print(f"VALIDATION  {total - len(gate_fail)}/{total} reference artifacts pass every gate")
    if gate_fail:
        print("  gate failures (a reference artifact failing Validation is itself a finding):")
        for r in gate_fail:
            failed = [g for g, ok in r["validation"]["gates"].items() if not ok]
            print(f"    {r['id']}: {', '.join(failed)}")
    codes = Counter(c for r in results for c in r["validation"]["diagnostic_codes"])
    if codes:
        print("  most common Validation diagnostic codes:")
        for code, count in codes.most_common(10):
            print(f"    {count:4d}  {code}")
    print()

    skipped = [r["id"] for r in results if r["alignment"]["skipped"]]
    print(f"INTENT ALIGNMENT  {total - len(skipped)}/{total} cases scored "
          f"({len(skipped)} skipped -- adapter cannot parse, docs/decisions/0020)")
    print("  Run `python datasets/run_alignment.py` for the full breakdown (P2's D10 report).")
    print()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--corpus", default="datasets/corpus", help="corpus directory (default: datasets/corpus)")
    parser.add_argument("--out", help="directory to write corpus_run.json into")
    parser.add_argument("--case", help="run one case only")
    args = parser.parse_args()

    corpus = Path(args.corpus)
    manifest = json.loads((corpus / "manifest.json").read_text())
    entries = manifest["cases"]
    if args.case:
        entries = [e for e in entries if e["id"] == args.case]
        if not entries:
            print(f"no such case: {args.case}", file=sys.stderr)
            return 2

    results = run_all(corpus, entries)
    _report(results)

    if args.out:
        out_dir = Path(args.out)
        out_dir.mkdir(parents=True, exist_ok=True)
        out_file = out_dir / "corpus_run.json"
        out_file.write_text(json.dumps(results, indent=2))
        print(f"wrote {out_file}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
