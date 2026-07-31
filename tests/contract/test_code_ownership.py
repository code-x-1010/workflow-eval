"""An agent may only emit diagnostic codes under its own prefixes.

Codes are the layer's public interface -- the generation team keys repair logic
off these strings. Append-only; never rename or repurpose.
"""
from __future__ import annotations

import json
from pathlib import Path

from wfeval.core.diagnostics import PREFIX_OWNER

EXAMPLES = Path(__file__).resolve().parents[2] / "contracts" / "examples"

EXAMPLE_OWNER = {
    "validation.response.json": "P1",
    "spec.response.json": "P2",
    "intent.response.json": "P2",
    "execution.response.json": "P3",
    "cost.response.json": "P4",
}


def test_examples_only_emit_owned_codes() -> None:
    for filename, owner in EXAMPLE_OWNER.items():
        payload = json.loads((EXAMPLES / filename).read_text())
        for diag in _all_diagnostics(payload):
            prefix = diag["code"].split("-")[0]
            assert PREFIX_OWNER.get(prefix) == owner, (
                f"{filename} emits {diag['code']}, owned by {PREFIX_OWNER.get(prefix)}, not {owner}"
            )


def test_every_diagnostic_has_a_suggested_fix() -> None:
    """A diagnostic without an actionable fix cannot drive a repair loop."""
    for filename in EXAMPLE_OWNER:
        payload = json.loads((EXAMPLES / filename).read_text())
        for diag in _all_diagnostics(payload):
            assert diag.get("suggested_fix"), f"{filename}: {diag['code']} has no suggested_fix"


def test_low_confidence_cost_must_state_assumptions() -> None:
    """Never ship a bare number. Assumptions are what stop a low-confidence
    estimate being mistaken for a quote."""
    cost = json.loads((EXAMPLES / "cost.response.json").read_text())
    if cost["confidence"] == "low":
        assert cost["assumptions"], "confidence=low requires a non-empty assumptions list"


def _all_diagnostics(payload: dict) -> list[dict]:
    out = list(payload.get("diagnostics", []))
    out += payload.get("sufficiency_diagnostics", [])
    return out
