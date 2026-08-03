"""Tests for the corpus emitter and, more importantly, for its validator.

`check()` is what guarantees the 40 reference artifacts are sound, and a
validator is only worth having if it has been shown to *catch* things. Every
test below feeds it a known-bad artifact derived from a real corpus case and
asserts it complains. Without these, `--check` passing on 40 hand-authored
inputs proves nothing about the checker.

Lives here rather than in `tests/unit/intent/` because `scripts/check_ownership.py`
puts only `services/intent/` and `datasets/` in P2's lane (see
docs/decisions/0006). `make test` runs `tests/unit`, so run these with:

    pytest datasets
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.bpmn import branch, check, derive_patterns, emit, end, goto, par, start, task, xor  # noqa: E402
from tools.cases import ALL_CASES  # noqa: E402

CORPUS = Path(__file__).resolve().parents[1] / "corpus"
GOOD = (CORPUS / "c01_invoice_approval" / "reference.bpmn").read_text()


def test_the_control_artifact_is_clean() -> None:
    assert check(GOOD) == []


@pytest.mark.parametrize(
    ("defect", "mutation", "expected"),
    [
        ("dangling flow target",
         lambda x: x.replace('targetRef="Task_extract"', 'targetRef="Task_nope"', 1),
         "does not resolve"),
        ("duplicate element id",
         lambda x: x.replace('id="Task_notify"', 'id="Task_extract"', 1),
         "duplicate ids"),
        ("unreachable element",
         lambda x: x.replace(
             '<sequenceFlow id="Flow_02" sourceRef="Task_extract" targetRef="Gateway_amount" />', ""),
         "unreachable"),
        ("exclusive split with no condition and no default",
         lambda x: x.replace(' default="Flow_04"', ""),
         "have no condition and are not the default"),
        ("two start events",
         lambda x: x.replace('<serviceTask id="Task_extract"',
                             '<startEvent id="StartEvent_2"/><serviceTask id="Task_extract"'),
         "expected exactly 1 start event"),
    ],
)
def test_check_catches(defect: str, mutation, expected: str) -> None:
    problems = check(mutation(GOOD))
    assert any(expected in p for p in problems), f"{defect} went undetected: {problems}"


def test_no_end_event_is_caught() -> None:
    # emit() refuses to build one at all, which is the earlier and better failure.
    with pytest.raises(ValueError, match="does not reach an end event"):
        emit("Process_x", [start("S", "s"), task("T", "t")])


def test_boundary_handler_must_terminate() -> None:
    with pytest.raises(ValueError, match="must reach an end event"):
        emit("Process_x", [
            start("S", "s"),
            task("T", "t", boundary_error={"id": "B", "name": "b", "nodes": [task("H", "h")]}),
            end("E", "e"),
        ])


def test_parallel_branch_may_not_carry_a_condition() -> None:
    with pytest.raises(ValueError, match="cannot carry a condition"):
        emit("Process_x", [
            start("S", "s"),
            par("G", "g", [branch("a", [task("A", "a")], condition="x > 1"),
                           branch("b", [task("B", "b")])]),
            end("E", "e"),
        ])


def test_branch_condition_survives_a_leading_goto() -> None:
    """Regression: a goto opening a branch dropped the branch's condition, which
    produced an unconditioned non-default flow out of an exclusive split."""
    xml = emit("Process_loop", [
        start("S", "start"),
        task("T", "work"),
        xor("G", "done?", [
            branch("not done", [goto("T")], condition="done == false"),
            branch("done", [], default=True),
        ]),
        end("E", "end"),
    ])
    assert check(xml) == []
    assert "done == false" in xml


def test_pass_through_branch_keeps_its_default_marking() -> None:
    """Regression: an empty (pass-through) branch lost `default`, so its flow out
    of the gateway had neither a condition nor default status."""
    xml = emit("Process_pt", [
        start("S", "start"),
        xor("G", "big?", [
            branch("big", [task("A", "review")], condition="big == true"),
            branch("small", [], default=True),
        ]),
        task("T", "process"),
        end("E", "end"),
    ])
    assert check(xml) == []


def test_no_degenerate_join_gateway() -> None:
    """A 1-in-1-out gateway is an element the prompt never asked for, and it
    shows up as noise in every alignment diff computed against the artifact."""
    xml = emit("Process_dg", [
        start("S", "start"),
        xor("G", "reject?", [
            branch("reject", [task("R", "reject"), end("E2", "rejected")], condition="ok == false"),
            branch("continue", [], default=True),
        ]),
        task("T", "carry on"),
        end("E", "done"),
    ])
    assert "G_join" not in xml
    assert check(xml) == []


def test_emit_is_deterministic() -> None:
    case = ALL_CASES[0]
    assert emit(case.process_id, case.nodes) == emit(case.process_id, case.nodes)


def test_derive_patterns_reads_real_structure() -> None:
    found = derive_patterns(GOOD)
    assert {"message_start", "numeric_threshold", "human_task", "boundary_error"} <= set(found)
    assert "linear" not in found  # it has a gateway
    assert "timer_start" not in found


def test_every_committed_artifact_is_structurally_sound() -> None:
    files = sorted(CORPUS.glob("*/reference.bpmn"))
    assert len(files) == len(ALL_CASES) == 40
    for f in files:
        assert check(f.read_text()) == [], f.parent.name
