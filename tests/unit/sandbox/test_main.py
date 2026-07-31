from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from services.sandbox.src.main import app

FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "spiff" / "executable_invoice.bpmn"
client = TestClient(app)


def test_deploy_is_a_deferred_pass_through():
    resp = client.post("/v1/deploy", json={"platform": "uipath_maestro", "artifact": {}})
    body = resp.json()
    assert body["accepted"] is True
    assert body["diagnostics"][0]["code"] == "PLT-DEPLOY-DEFERRED"
    assert body["diagnostics"][0]["severity"] == "info"


def test_executions_roundtrip_reflects_runner_and_fidelity():
    request_body = {
        "artifact": {"content": FIXTURE.read_text()},
        "test_cases": [{
            "case_id": "tc_001", "kind": "happy", "description": "d", "input": {"amount": 250.0},
            "assertions": [{"type": "path", "description": "auto-pay",
                             "must_traverse": ["Task_autopay"], "must_not_traverse": ["Task_approval"]}],
            "task_stubs": [
                {"element_id": "Task_extract", "outputs": [{"vendor": "Acme", "amount": 250.0}]},
                {"element_id": "Task_autopay", "outputs": [{"status": "SETTLED"}]},
                {"element_id": "Task_notify", "outputs": [{}]},
            ],
        }],
        "mocks": [], "timeout_s": 10,
    }
    started = client.post("/v1/executions", json=request_body)
    assert started.status_code == 200
    execution_id = started.json()["execution_id"]

    report = client.get(f"/v1/executions/{execution_id}").json()
    assert report["runner"] == "spiff"
    assert report["fidelity"] == "reduced"
    assert report["confidence"] != "high"
    assert report["results"][0]["status"] == "pass"
    assert report["scores"]["execution_pass_rate"] == 1.0


def test_unknown_execution_id_returns_the_golden_example_not_a_hang():
    resp = client.get("/v1/executions/ex_never_seen")
    assert resp.status_code == 200
    assert "results" in resp.json()
