"""Boundary values from the spec's numeric conditions. D8.

> *"Boundary cases come from the spec's numeric conditions, not from your
> imagination. If the spec says 'over 10000', generate 9999 / 10000 / 10001.
> That off-by-one at the branch condition is the single most common behavioural
> bug in generated workflows."* -- the charter

Three values per condition, always the same three: **just below, exactly at, and
just above** the stated threshold. The middle one is the one that finds bugs,
because `>` and `>=` differ only there and a generator picks between them by
guessing what "over" means.

## What "just" means

The step is derived from how the threshold was *written*, not from a constant.
`10000` steps by 1; `0.8` steps by 0.1; `10.25` steps by 0.01. Writing a
threshold to two decimal places is the user saying the second decimal matters, so
9.99/10.00/10.01 is the boundary they described. A fixed step of 1 around 0.8
would generate -0.2/0.8/1.8, which tests nothing about a fraction.

## What this module refuses to do

Nothing here invents a threshold. A qualitative condition ("big orders") produces
**no boundary cases at all** -- `SPEC-AMBIGUOUS-CONDITION` is raised instead, at
D5, and `0008` says why: a generator that invents 1000 and emits 999/1000/1001 is
testing its own guess while reporting confidence about it.

Owner: P2. Imports `wfeval.core.ir` only -- never the AST, never an adapter.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal

from wfeval.core.ir import BranchCondition

# "amount > 10000", "score >= 0.8". Produced by extract._branches(), which only
# ever emits this shape -- a variable, a comparator, a number.
_EXPRESSION_RE = re.compile(r"^\s*(?P<var>[a-z_][a-z0-9_]*)\s*(?P<op>>=|<=|>|<|==)\s*(?P<num>-?[\d.]+)\s*$")


@dataclass(frozen=True)
class Boundary:
    """One condition's three probe values, with the variable they belong to."""

    variable: str
    operator: str
    threshold: Decimal
    below: Decimal
    at: Decimal
    above: Decimal

    @property
    def probes(self) -> list[tuple[str, Decimal]]:
        """Labelled, because a case description that says which side of the
        threshold it is on is the difference between a readable failure and a
        number in a list."""
        return [("just below", self.below), ("exactly at", self.at), ("just above", self.above)]


def step_for(number: str) -> Decimal:
    """The smallest increment the threshold's own notation can express.

    `"10000"` -> 1, `"0.8"` -> 0.1, `"10.25"` -> 0.01. Reading the precision off
    the text rather than the value is deliberate: `Decimal("0.80")` and
    `Decimal("0.8")` are equal numbers written to different precision, and the
    user who typed the first one is telling you the hundredths place matters.
    """
    if "." not in number:
        return Decimal(1)
    places = len(number.split(".", 1)[1])
    return Decimal(1).scaleb(-places)


def boundaries_for(condition: BranchCondition) -> Boundary | None:
    """The three probes for one condition, or None if it has no number in it."""
    if not condition.expression_hint:
        return None
    match = _EXPRESSION_RE.match(condition.expression_hint)
    if not match:
        return None
    raw = match.group("num")
    try:
        threshold = Decimal(raw)
    except (ArithmeticError, ValueError):
        return None
    step = step_for(raw)
    return Boundary(
        variable=match.group("var"),
        operator=match.group("op"),
        threshold=threshold,
        below=threshold - step,
        at=threshold,
        above=threshold + step,
    )


def all_boundaries(conditions: list[BranchCondition]) -> list[Boundary]:
    """Every condition that carries a number, deduplicated by variable and
    threshold.

    Deduplication matters on real prompts: "claims from 100 up to 1000" and
    "anything above 1000" both mention 1000, and generating the same three probes
    twice inflates the case count without testing anything twice.
    """
    seen: set[tuple[str, str, Decimal]] = set()
    out = []
    for condition in conditions:
        boundary = boundaries_for(condition)
        if boundary is None:
            continue
        key = (boundary.variable, boundary.operator, boundary.threshold)
        if key in seen:
            continue
        seen.add(key)
        out.append(boundary)
    return out


def as_number(value: Decimal) -> float | int:
    """JSON-friendly. Integers stay integers so a case input reads `10000`, not
    `10000.0` -- P3 seeds these straight into a process variable, and a float
    where the workflow expects an integer is a type-confusion bug we introduced."""
    if value == value.to_integral_value():
        return int(value)
    return float(value)
