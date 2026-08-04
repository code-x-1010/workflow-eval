"""Validation service HTTP layer tests."""
from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from services.validation.src.main import app

ROOT = Path(__file__).resolve().parents[3]
GOOD_BPMN = (ROOT / "tests/fixtures/spiff/executable_invoice.bpmn").read_text()
PLANTED_DEFECT_BPMN = (ROOT / "contracts/examples/artifact.bpmn").read_text()

client = TestClient(app)


def test_healthz():
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "service": "validation", "owner": "P1"}


def test_validate_clean_artifact_passes_l1_and_l3():
    resp = client.post("/v1/validate", json={
        "request_id": "r1", "platform": "uipath_maestro",
        "artifact": {"format": "bpmn", "content": GOOD_BPMN},
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["gates"]["schema_validity"] is True
    assert body["scores"]["structural_soundness"] == 1.0
    assert body["diagnostics"] == []
    assert set(body["tiers_run"]) == {"L1", "L3"}
    assert set(body["tiers_skipped"]) == {"L2", "L4"}
    assert body["ast_digest"].startswith("sha256:")


def test_validate_flags_the_planted_gateway_defect():
    resp = client.post("/v1/validate", json={
        "request_id": "r2", "platform": "uipath_maestro",
        "artifact": {"format": "bpmn", "content": PLANTED_DEFECT_BPMN},
    })
    body = resp.json()
    assert body["gates"]["schema_validity"] is True  # parses fine -- this is an L3 issue, not L1
    codes = [d["code"] for d in body["diagnostics"]]
    assert "STR-GATEWAY-NO-DEFAULT" in codes
    assert body["scores"]["structural_soundness"] < 1.0


def test_validate_malformed_xml_short_circuits_l2_l3_l4():
    resp = client.post("/v1/validate", json={
        "request_id": "r3", "platform": "uipath_maestro",
        "artifact": {"format": "bpmn", "content": "<not-bpmn>"},
    })
    body = resp.json()
    assert body["gates"]["schema_validity"] is False
    assert body["diagnostics"][0]["code"] == "SCH-PARSE-FAILED"
    assert body["tiers_run"] == ["L1"]
    assert set(body["tiers_skipped"]) == {"L2", "L3", "L4"}
    assert body["ast_digest"] is None


def test_validate_respects_requested_tiers():
    resp = client.post("/v1/validate", json={
        "request_id": "r4", "platform": "uipath_maestro",
        "artifact": {"format": "bpmn", "content": GOOD_BPMN},
        "options": {"tiers": ["L1"]},
    })
    body = resp.json()
    assert body["tiers_run"] == ["L1"]
    assert "structural_soundness" not in body["scores"]


def test_diagnostics_codes_endpoint():
    resp = client.get("/v1/diagnostics/codes")
    assert resp.status_code == 200
    assert resp.json()["prefixes"]["STR"] == "P1"
