"""Validation service HTTP layer tests."""
from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from services.validation.src.main import app

ROOT = Path(__file__).resolve().parents[3]
GOOD_BPMN = (ROOT / "tests/fixtures/spiff/executable_invoice.bpmn").read_text()
PLANTED_DEFECT_BPMN = (ROOT / "contracts/examples/artifact.bpmn").read_text()
FULLY_CLEAN_BPMN = (ROOT / "tests/fixtures/bpmn/adapter_rich.bpmn").read_text()

client = TestClient(app)


def test_healthz():
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "service": "validation", "owner": "P1"}


def test_validate_clean_artifact_passes_l1_and_l3():
    resp = client.post("/v1/validate", json={
        "request_id": "r1", "platform": "uipath_maestro",
        "artifact": {"format": "bpmn", "content": GOOD_BPMN},
        "options": {"tiers": ["L1", "L3"]},
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["gates"]["schema_validity"] is True
    assert body["scores"]["structural_soundness"] == 1.0
    assert body["diagnostics"] == []
    assert set(body["tiers_run"]) == {"L1", "L3"}
    assert set(body["tiers_skipped"]) == {"L2", "L4"}
    assert body["ast_digest"].startswith("sha256:")


def test_validate_default_tiers_now_include_l4():
    """GOOD_BPMN (tests/fixtures/spiff/executable_invoice.bpmn) is clean for
    L1/L3, but it never declares a writer for 'amount' via <uipath:variables>
    -- so L4 dataflow correctly flags the read in Gateway_amount's condition.
    This is a real, honest finding given the adapter's documented limitation
    (see wfeval/adapters/bpmn.py), not a bug in the fixture or the check.
    It has no asset_ref anywhere, so L2 trivially passes rather than being
    skipped -- there's nothing in it to check against Sandbox's registry."""
    resp = client.post("/v1/validate", json={
        "request_id": "r1b", "platform": "uipath_maestro",
        "artifact": {"format": "bpmn", "content": GOOD_BPMN},
    })
    body = resp.json()
    assert set(body["tiers_run"]) == {"L1", "L2", "L3", "L4"}
    assert body["tiers_skipped"] == {}
    assert body["gates"]["reference_integrity"] is True
    codes = [d["code"] for d in body["diagnostics"]]
    assert codes == ["FLW-VARIABLE-NOT-ASSIGNED"]
    assert body["scores"]["process_soundness"] == 1.0
    assert body["scores"]["dataflow_correctness"] < 1.0


def test_validate_l2_degrades_gracefully_when_sandbox_is_unreachable():
    """adapter_rich.bpmn DOES reference real assets (ChargePayment,
    NotifyVendor), so this exercises the actual HTTP call to Sandbox's
    /v1/assets -- unreachable in the test environment (no such host), which
    is exactly the "kill the sandbox container" scenario the charter
    requires L2 to survive: still a 200, L2 just moves to tiers_skipped."""
    resp = client.post("/v1/validate", json={
        "request_id": "r1e", "platform": "uipath_maestro",
        "artifact": {"format": "bpmn", "content": FULLY_CLEAN_BPMN},
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["tiers_skipped"].get("L2") == "asset registry unavailable"
    assert "reference_integrity" not in body["gates"]
    assert "L2" not in body["tiers_run"]


def test_validate_fully_clean_artifact_has_no_l4_findings():
    """adapter_rich.bpmn declares every variable it reads, dominated by its
    writer -- confirms L4 doesn't false-positive on a well-formed artifact."""
    resp = client.post("/v1/validate", json={
        "request_id": "r1c", "platform": "uipath_maestro",
        "artifact": {"format": "bpmn", "content": FULLY_CLEAN_BPMN},
    })
    body = resp.json()
    assert body["diagnostics"] == []
    assert body["scores"]["process_soundness"] == 1.0
    assert body["scores"]["dataflow_correctness"] == 1.0


def test_validate_flags_a_deadlock():
    content = (ROOT / "tests/fixtures/bpmn/deadlock_xor_split_and_join.bpmn").read_text()
    resp = client.post("/v1/validate", json={
        "request_id": "r1d", "platform": "uipath_maestro",
        "artifact": {"format": "bpmn", "content": content},
    })
    body = resp.json()
    codes = [d["code"] for d in body["diagnostics"]]
    assert any(c in ("FLW-DEAD-TRANSITION", "FLW-NOT-SOUND") for c in codes)
    assert all(d["severity"] == "warning" for d in body["diagnostics"])  # L4 never blocks a gate
    assert body["scores"]["process_soundness"] < 1.0
    assert "process_soundness" not in body["gates"]  # L4 never adds a gate, only scores/diagnostics


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
