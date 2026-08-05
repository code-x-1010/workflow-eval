"""Structural validation: schema, references, structure, soundness, dataflow.

Service: validation  |  Port: 8001  |  Owner: P1
Charter: docs/agents/P1-*.md      Contract: contracts/validation.openapi.yaml

L1, L3 and L4 are real (see l1_schema.py, l3_structure.py, l4_soundness.py,
l4_dataflow.py). L2 needs Sandbox's asset registry (D8) and still reports via
tiers_skipped rather than pretending to run. L4 ships at `warning` severity
only -- see l4_soundness.py's module docstring for why -- so it never sets a
`gates` entry, only `scores`/`diagnostics`, same as L3.
Do not change the response SHAPES without a decision record.
"""
from typing import Any

from fastapi import FastAPI
from wfeval.core.diagnostics import PREFIX_OWNER

from . import l1_schema, l3_structure, l4_dataflow, l4_soundness

app = FastAPI(title="wfeval-validation", version="0.1.0")

SERVICE = "validation"
OWNER = "P1"


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok", "service": SERVICE, "owner": OWNER}


@app.post("/v1/validate")
def validate(body: dict[str, Any]) -> dict[str, Any]:
    artifact = body.get("artifact") or {}
    content: str = artifact.get("content", "")
    platform: str = body.get("platform", "uipath_maestro")
    requested_tiers: list[str] = (body.get("options") or {}).get("tiers") or ["L1", "L2", "L3", "L4"]

    diagnostics: list[dict[str, Any]] = []
    gates: dict[str, bool] = {}
    scores: dict[str, float] = {}
    tiers_run: list[str] = []
    tiers_skipped: dict[str, str] = {}

    # Parsing is a prerequisite for every other tier, not an optional one --
    # it always runs even if the caller didn't ask to see L1's own result.
    ast, l1_diagnostics, schema_validity = l1_schema.check(content, platform=platform)
    diagnostics.extend(d.model_dump(mode="json") for d in l1_diagnostics)
    if "L1" in requested_tiers:
        tiers_run.append("L1")
        gates["schema_validity"] = schema_validity
    else:
        tiers_skipped["L1"] = "not requested"

    if ast is None:
        # Short-circuit: L2-L4 have nothing to run against without an AST.
        for tier in ("L2", "L3", "L4"):
            tiers_skipped.setdefault(tier, "not run: L1 failed to parse the artifact")
        return _report(gates, scores, diagnostics, ast_digest=None,
                        tiers_run=tiers_run, tiers_skipped=tiers_skipped)

    tiers_skipped["L2"] = "not implemented until D8 (needs Sandbox's asset registry)"

    if "L3" in requested_tiers:
        l3_diagnostics = l3_structure.check(ast)
        diagnostics.extend(d.model_dump(mode="json") for d in l3_diagnostics)
        scores["structural_soundness"] = l3_structure.score(l3_diagnostics, len(ast.elements))
        tiers_run.append("L3")
    else:
        tiers_skipped["L3"] = "not requested"

    if "L4" in requested_tiers:
        l4_soundness_diagnostics = l4_soundness.check(ast)
        l4_dataflow_diagnostics = l4_dataflow.check(ast)
        diagnostics.extend(d.model_dump(mode="json") for d in l4_soundness_diagnostics)
        diagnostics.extend(d.model_dump(mode="json") for d in l4_dataflow_diagnostics)
        scores["process_soundness"] = l4_soundness.score(l4_soundness_diagnostics)
        scores["dataflow_correctness"] = l4_dataflow.score(l4_dataflow_diagnostics)
        tiers_run.append("L4")
    else:
        tiers_skipped["L4"] = "not requested"

    return _report(gates, scores, diagnostics, ast_digest=ast.digest,
                    tiers_run=tiers_run, tiers_skipped=tiers_skipped)


def _report(
    gates: dict[str, bool], scores: dict[str, float], diagnostics: list[dict[str, Any]],
    *, ast_digest: str | None, tiers_run: list[str], tiers_skipped: dict[str, str],
) -> dict[str, Any]:
    return {
        "gates": gates,
        "scores": scores,
        "diagnostics": diagnostics,
        "ast_digest": ast_digest,
        "tiers_run": tiers_run,
        "tiers_skipped": tiers_skipped,
    }


@app.get("/v1/diagnostics/codes")
def codes() -> dict[str, Any]:
    return {"prefixes": PREFIX_OWNER, "codes": []}
