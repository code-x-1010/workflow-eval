"""Assertion evaluation against a Trace. Runner-agnostic -- works the same
whether the trace came from Spiff or (eventually) UiPath.

Only AssertionType.PATH is evaluated for now. OUTPUT/INVARIANT/BUDGET need an
expression evaluator over final_variables that doesn't exist yet
(TODO P3 D8, per the original charter's own cadence) -- their presence on a
case does not fail it, but it is not silently counted as a pass either; they
are simply not checked yet, which is different from "passed".
"""
from __future__ import annotations

from wfeval.core.testcase import Assertion, AssertionType, TestCase
from wfeval.core.trace import Trace


def evaluate(test_case: TestCase, trace: Trace) -> tuple[str, str | None]:
    """Returns (status, failed_assertion) where status is 'pass' or 'fail'.
    Caller is responsible for 'error'/'skipped', which come from the runner
    failing to produce a trace at all, not from assertion evaluation."""
    path = set(trace.path)
    for assertion in test_case.assertions:
        if assertion.type != AssertionType.PATH:
            continue
        failure = _check_path(assertion, path)
        if failure:
            return "fail", failure
    return "pass", None


def _check_path(assertion: Assertion, path: set[str]) -> str | None:
    for required in assertion.must_traverse or []:
        if required not in path:
            return assertion.description
    for forbidden in assertion.must_not_traverse or []:
        if forbidden in path:
            return assertion.description
    return None
