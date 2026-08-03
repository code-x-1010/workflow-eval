"""The `SPEC-*` sufficiency code registry.

`SPEC` is P2's prefix (`PREFIX_OWNER` in `wfeval.core.diagnostics`). Codes are
**append-only** — the generation team keys repair logic off these strings, so a
code is never renamed or repurposed. See
`docs/decisions/0008-spec-sufficiency-code-registry.md`.

Declared here at D2, ahead of the D5 implementation, because the corpus's
`expected_diagnostics` are ground truth and ground truth cannot reference codes
that do not exist yet.

Severity rule for this prefix: a sufficiency gap is a `warning` when a
downstream tier will silently produce a wrong-looking number because of it, and
`info` when it only costs advice quality. Nothing here is an `error` — an
under-specified prompt is a normal thing for a user to send, not a failure.
"""
from __future__ import annotations

SPEC_CODES: dict[str, tuple[str, str]] = {
    "SPEC-NO-TRIGGER": (
        "warning",
        "The prompt never says what starts the process. Any start event in the artifact "
        "is the generator's invention and intent alignment cannot check it.",
    ),
    "SPEC-NO-ERROR-BEHAVIOUR": (
        "warning",
        "A side-effecting step has no stated failure behaviour: no retry, escalation or "
        "compensation. Robustness testing has nothing to assert against.",
    ),
    "SPEC-AMBIGUOUS-CONDITION": (
        "warning",
        "A branch condition is qualitative ('big', 'urgent', 'high value') with no "
        "threshold. Boundary test generation would have to invent the number, and would "
        "then be testing its own guess.",
    ),
    "SPEC-UNBOUNDED-INPUT": (
        "warning",
        "A collection input or a loop has no volume bound, so per-instance cost is "
        "unbounded and Cost cannot gate on it.",
    ),
    "SPEC-NO-TERMINAL-STATE": (
        "warning",
        "A loop or wait has no exit condition, attempt cap or timeout, so no terminal "
        "state is guaranteed.",
    ),
    "SPEC-UNSPECIFIED-INTEGRATION": (
        "warning",
        "An external system is referred to but not named ('the system', 'our CRM'), so "
        "no asset reference and no mock can be derived for it.",
    ),
    "SPEC-AMBIGUOUS-ACTOR": (
        "warning",
        "A human step names no role ('someone approves'), so the task cannot be assigned "
        "and any rejection path is unspecified.",
    ),
    "SPEC-CONTRADICTORY-REQUIREMENT": (
        "warning",
        "Two statements in the prompt cannot both be satisfied. Any artifact silently "
        "picks one reading; the conflict must surface instead.",
    ),
    "SPEC-UNSTATED-SLA": (
        "info",
        "A timing expectation is implied ('quickly', 'immediately', 'within the "
        "deadline') without a duration, so it cannot be asserted on.",
    ),
    "SPEC-NO-BUDGET": (
        "info",
        "No per-instance cost ceiling was stated, so Cost reports a number with nothing "
        "to gate it against.",
    ),
}


def unknown(codes: object) -> list[str]:
    """Return any codes not in the registry. Used by the corpus --check."""
    return [c for c in codes if c not in SPEC_CODES]  # type: ignore[union-attr]
