"""Invariant assertions: what must hold for every input, on every case. D8.

The charter names three, and all three are here:

* `terminal_events == 1` -- the process ends, once. Catches the two commonest
  structural failures at execution time: a workflow that never terminates, and
  one that reaches two end events on a single run.
* no task executes more than N times -- catches the unbounded retry loop that
  `SPEC-NO-TERMINAL-STATE` warns about at D5. Where the prompt stated a cap, N is
  that cap; otherwise it is a generous ceiling that only a runaway trips.
* no PII in outbound payloads -- catches a workflow that pipes a whole customer
  record into a third-party call.

## Why these are worth more than the path assertions we cannot write

An invariant needs no element ids. It is a property of the *run*, so it survives
the generator restructuring everything, and it is the one kind of assertion this
module can emit at full strength while `0005`/`0009` remain unsigned. Every
generated case carries the invariant block, which means even a case whose branch
we cannot assert on still proves the workflow terminates cleanly for that input.

Owner: P2. Imports `wfeval.core` types only.
"""
from __future__ import annotations

import re

from wfeval.core.ir import Spec
from wfeval.core.testcase import Assertion, AssertionType

# The ceiling used when the prompt states no attempt cap. High enough that a
# correct workflow with a legitimate loop never trips it, low enough that a
# runaway is caught long before a test run times out -- a hang reports `error`,
# which reads on a corpus run as "the generated workflow hangs" and tells you
# nothing about which task ran away.
DEFAULT_MAX_TASK_EXECUTIONS = 50

# Field names that carry personal data. Matched against the *names* the spec
# uses, never against values -- P2 never sees real data, and a regex over values
# at generation time would be checking the example, not the run.
_PII_HINTS = (
    "email", "phone", "mobile", "ssn", "national_insurance", "nino", "dob",
    "date_of_birth", "address", "postcode", "zip", "passport", "iban", "account_number",
    "card", "pan", "cvv", "name", "surname", "salary", "medical", "diagnosis", "patient",
)

_CAP_RE = re.compile(
    r"\b(?:up\s+to|at\s+most|no\s+more\s+than|maximum\s+of|max)\s+(\d+)\s*(?:times|attempts|retries|tries)\b"
    r"|\b(\d+)\s*(?:times|attempts|retries|tries)\b",
    re.IGNORECASE,
)


def max_executions_from(prompt: str) -> int:
    """The attempt cap the prompt stated, or the default ceiling.

    Reads the prompt rather than the Spec because `Spec` has nowhere to put an
    attempt cap -- there is no field for it, and inventing one would be a frozen
    type change. The number is in the words or it is nowhere.
    """
    match = _CAP_RE.search(prompt)
    if not match:
        return DEFAULT_MAX_TASK_EXECUTIONS
    stated = match.group(1) or match.group(2)
    try:
        value = int(stated)
    except (TypeError, ValueError):
        return DEFAULT_MAX_TASK_EXECUTIONS
    return value if 0 < value <= DEFAULT_MAX_TASK_EXECUTIONS else DEFAULT_MAX_TASK_EXECUTIONS


def pii_fields(spec: Spec) -> list[str]:
    """Spec inputs whose *name* suggests personal data."""
    found = []
    for field in spec.inputs:
        lowered = field.name.lower()
        if any(hint in lowered for hint in _PII_HINTS):
            found.append(field.name)
    return sorted(found)


def invariants_for(spec: Spec, prompt: str) -> list[Assertion]:
    """The invariant block every generated case carries."""
    cap = max_executions_from(prompt)
    out = [
        Assertion(
            type=AssertionType.INVARIANT,
            description="The process reaches exactly one terminal event on this run.",
            expr="terminal_events == 1",
        ),
        Assertion(
            type=AssertionType.INVARIANT,
            description=(
                f"No task executes more than {cap} times"
                + (" (the cap the prompt states)." if cap != DEFAULT_MAX_TASK_EXECUTIONS
                   else ", the default ceiling for a runaway loop.")
            ),
            expr=f"max_task_executions <= {cap}",
        ),
    ]

    personal = pii_fields(spec)
    if personal:
        # Only when the spec actually carries such a field. An invariant that can
        # never fail is noise in every report that includes it, and P3 pays to
        # evaluate it on every case.
        out.append(Assertion(
            type=AssertionType.INVARIANT,
            description=(
                "No personal data leaves the process in an outbound payload. "
                f"Fields treated as personal here: {', '.join(personal)}."
            ),
            expr="no_pii_in_outbound_payloads(" + ", ".join(sorted(personal)) + ")",
        ))
    return out


def budget_assertion(spec: Spec) -> list[Assertion]:
    """A cost ceiling, only when the prompt stated one.

    `SPEC-NO-BUDGET` covers the case where it did not. Emitting a default ceiling
    here would give P4 a number to gate on that no user ever asked for, which is
    worse than having none.
    """
    if spec.budget_per_instance is None:
        return []
    return [Assertion(
        type=AssertionType.BUDGET,
        description=f"The run costs no more than the stated {spec.budget_per_instance} per instance.",
        max_cost=spec.budget_per_instance,
    )]
