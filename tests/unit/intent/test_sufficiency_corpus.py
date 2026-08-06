"""The sufficiency checker, scored against all 40 corpus cases.

`datasets/corpus/manifest.json` records `expected_diagnostics` per case. Those
labels were written at D2, **before any of these rules existed**, so the rules
were tuned against ground truth they could not influence. That ordering is the
only reason these numbers mean anything.

This file pins the measured result. It is a regression test with a scorecard
attached: a rule that gets looser shows up as a precision drop rather than as a
green suite, and the per-code table below says which codes are deliberately
low-recall and why.

Run `pytest tests/unit/intent/test_sufficiency_corpus.py -s` to print the table.
"""
from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import pytest
from wfeval.core.diagnostics import Severity

from services.intent.src.extract import extract
from services.intent.src.sufficiency import diagnose

ROOT = Path(__file__).resolve().parents[3]
CORPUS = ROOT / "datasets" / "corpus"

# Measured on 2026-08-05 over all 40 cases. Precision is pinned at 1.0 and must
# stay there: a false SPEC-* tells the generation team to fix a prompt that was
# fine, and enough of those and the whole prefix gets ignored -- including the
# true ones. Recall is a floor, not a target.
MIN_PRECISION = 1.0
MIN_RECALL = 0.90

# The six known misses, each a deliberate choice rather than an oversight. Listed
# here so that fixing one is a visible change to this file and not a silent
# fluctuation in a ratio.
KNOWN_MISSES = {
    ("c09_support_ticket_triage", "SPEC-UNSTATED-SLA"),
    ("c23_incident_response", "SPEC-UNSTATED-SLA"),
    ("u02_big_orders", "SPEC-NO-ERROR-BEHAVIOUR"),
    ("u07_until_its_sorted", "SPEC-UNBOUNDED-INPUT"),
    ("u09_urgent_tickets", "SPEC-NO-ERROR-BEHAVIOUR"),
    ("u10_automate_onboarding", "SPEC-AMBIGUOUS-ACTOR"),
    ("u10_automate_onboarding", "SPEC-AMBIGUOUS-CONDITION"),
    ("u10_automate_onboarding", "SPEC-NO-ERROR-BEHAVIOUR"),
    ("u10_automate_onboarding", "SPEC-UNSPECIFIED-INTEGRATION"),
}


@dataclass
class Case:
    id: str
    prompt: str
    expected: set[str]
    actual: set[str]


@pytest.fixture(scope="module")
def scored() -> list[Case]:
    manifest = json.loads((CORPUS / "manifest.json").read_text())
    cases = []
    for entry in manifest["cases"]:
        prompt = (CORPUS / entry["prompt_path"]).read_text()
        actual = {d.code for d in diagnose(prompt, extract(prompt))}
        cases.append(Case(entry["id"], prompt, set(entry["expected_diagnostics"]), actual))
    return cases


def test_the_negative_control_stays_completely_quiet(scored: list[Case]) -> None:
    """**The bar that matters most.** c01 states its trigger, threshold, failure
    path and budget, so it earns nothing at all. A checker that cannot stay quiet
    on a complete prompt puts noise on every real prompt, and the noise hides the
    findings that mean something."""
    c01 = next(c for c in scored if c.id == "c01_invoice_approval")
    assert c01.expected == set(), "precondition: c01 is the corpus's negative control"
    assert c01.actual == set(), f"the negative control raised {sorted(c01.actual)}"


def test_no_false_positives_anywhere_in_the_corpus(scored: list[Case]) -> None:
    """Precision 1.0 across 40 prompts. Every rule declines rather than guess, and
    this is the test that says so."""
    offenders = {c.id: sorted(c.actual - c.expected) for c in scored if c.actual - c.expected}
    assert not offenders, f"false positives: {offenders}"


def test_recall_holds(scored: list[Case]) -> None:
    tp = sum(len(c.actual & c.expected) for c in scored)
    fn = sum(len(c.expected - c.actual) for c in scored)
    recall = tp / (tp + fn)
    assert recall >= MIN_RECALL, f"recall fell to {recall:.3f}"


def test_the_misses_are_the_known_ones(scored: list[Case]) -> None:
    """Recall as a ratio can stay flat while the *shape* of what is missed
    changes. This asserts the actual set, so a newly-broken rule cannot hide
    behind a newly-fixed one."""
    misses = {(c.id, code) for c in scored for code in c.expected - c.actual}
    assert misses == KNOWN_MISSES


def test_every_emitted_code_is_in_the_registry(scored: list[Case]) -> None:
    """`0008` makes the registry append-only because the generation team keys
    repair logic off these strings. A code emitted but never declared is a string
    nobody can act on.

    Checked against `datasets/tools/spec_codes.py`, the machine-readable copy the
    corpus `--check` already validates `expected_diagnostics` against -- so the
    registry, the corpus labels and the emitter are pinned to each other rather
    than to the prose in the decision record.
    """
    import sys

    datasets = str(ROOT / "datasets")
    if datasets not in sys.path:
        sys.path.insert(0, datasets)
    from tools.spec_codes import SPEC_CODES

    emitted = {code for c in scored for code in c.actual}
    assert emitted <= set(SPEC_CODES), f"undeclared: {sorted(emitted - set(SPEC_CODES))}"


def test_severities_match_the_registry(scored: list[Case]) -> None:
    """The registry declares a severity per code and the emitter has its own. Two
    copies of the same fact drift; this is what notices."""
    import sys

    datasets = str(ROOT / "datasets")
    if datasets not in sys.path:
        sys.path.insert(0, datasets)
    from tools.spec_codes import SPEC_CODES

    seen: dict[str, str] = {}
    for case in scored:
        for diagnostic in diagnose(case.prompt, extract(case.prompt)):
            seen[diagnostic.code] = diagnostic.severity.value
    for code, severity in seen.items():
        assert severity == SPEC_CODES[code][0], f"{code}: emitter says {severity}, registry says {SPEC_CODES[code][0]}"


def test_no_spec_code_ever_blocks_a_gate(scored: list[Case]) -> None:
    for case in scored:
        for diagnostic in diagnose(case.prompt, extract(case.prompt)):
            assert diagnostic.severity != Severity.ERROR, f"{case.id}: {diagnostic.code}"


def test_print_the_scorecard(scored: list[Case], capsys: pytest.CaptureFixture[str]) -> None:
    """Not an assertion -- the table itself, for the D10 writeup and for anyone
    changing a rule. `-s` to see it."""
    tp: Counter[str] = Counter()
    fp: Counter[str] = Counter()
    fn: Counter[str] = Counter()
    for case in scored:
        for code in case.actual & case.expected:
            tp[code] += 1
        for code in case.actual - case.expected:
            fp[code] += 1
        for code in case.expected - case.actual:
            fn[code] += 1

    with capsys.disabled():
        print(f"\n{'code':32} {'TP':>4}{'FP':>4}{'FN':>4}  {'prec':>6}{'rec':>7}")
        for code in sorted(set(tp) | set(fp) | set(fn)):
            precision = tp[code] / (tp[code] + fp[code]) if tp[code] + fp[code] else float("nan")
            recall = tp[code] / (tp[code] + fn[code]) if tp[code] + fn[code] else float("nan")
            print(f"{code:32} {tp[code]:4d}{fp[code]:4d}{fn[code]:4d}  {precision:6.2f}{recall:7.2f}")
        total_tp, total_fp, total_fn = sum(tp.values()), sum(fp.values()), sum(fn.values())
        exact = sum(1 for c in scored if c.actual == c.expected)
        print(
            f"\noverall precision {total_tp / (total_tp + total_fp):.3f}  "
            f"recall {total_tp / (total_tp + total_fn):.3f}  "
            f"exact-set match {exact}/{len(scored)}\n"
        )
