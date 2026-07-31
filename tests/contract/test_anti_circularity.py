"""The single most important correctness property in this project.

If test generation can see the generated workflow, it will produce tests the
workflow passes, and the execution tier becomes a tautology reporting 100%.

Belt and braces: .importlinter blocks the import, the API schema omits the field,
and this test asserts both.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_testcases_endpoint_rejects_artifact() -> None:
    src = (ROOT / "services/intent/src/main.py").read_text()
    assert 'assert "artifact" not in body' in src, (
        "POST /v1/testcases must reject an artifact field. See docs/agents/P2-intent-testgen.md."
    )


def test_testgen_may_not_import_the_ast() -> None:
    cfg = (ROOT / ".importlinter").read_text()
    assert "intent.testgen" in cfg and "wfeval.core.ast" in cfg, (
        "The import-linter contract forbidding testgen -> ast has been removed or weakened."
    )


def test_golden_testcases_carry_no_artifact() -> None:
    payload = json.loads((ROOT / "contracts/examples/testcases.response.json").read_text())
    assert "artifact" not in payload
    for case in payload["test_cases"]:
        assert "artifact" not in case
