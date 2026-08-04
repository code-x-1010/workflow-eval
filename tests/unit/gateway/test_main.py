"""Gateway HTTP layer tests. Mocks orchestrate.py's functions directly (the
orchestration logic itself is covered by test_orchestrate.py) -- this file
only checks main.py's job: request/response wiring and the
DependencyUnavailable -> 502 translation.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
from wfeval.core.report import EvaluationReport, Verdict

from services.gateway.src.main import app
from services.gateway.src.orchestrate import DependencyUnavailable

client = TestClient(app)

REQUEST = {"request_id": "req_test", "platform": "uipath_maestro", "format": "bpmn", "content": "<definitions/>", "prompt": "do the thing"}

_REPORT = EvaluationReport(
    evaluation_id="ev_test", request_id="req_test", platform="uipath_maestro",
    verdict=Verdict.PASS, scoring_version="0.1.0", overall=0.9,
)


def test_healthz():
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "service": "gateway", "owner": "P1"}


def test_predeploy_validate_returns_the_report():
    with patch("services.gateway.src.main.orchestrate.run_predeploy_validate", new=AsyncMock(return_value=_REPORT)):
        resp = client.post("/v1/validate", json=REQUEST)
    assert resp.status_code == 200
    assert resp.json()["evaluation_id"] == "ev_test"


def test_predeploy_validate_502s_on_dependency_unavailable():
    unavailable = AsyncMock(side_effect=DependencyUnavailable("validation", "connection refused"))
    with patch("services.gateway.src.main.orchestrate.run_predeploy_validate", new=unavailable):
        resp = client.post("/v1/validate", json=REQUEST)
    assert resp.status_code == 502
    assert "validation" in resp.json()["detail"]


def test_create_evaluation_returns_202_with_poll_url():
    with patch("services.gateway.src.main.orchestrate.run_full_evaluation", new=AsyncMock(return_value="ev_test")):
        resp = client.post("/v1/evaluations", json=REQUEST)
    assert resp.status_code == 202
    body = resp.json()
    assert body["evaluation_id"] == "ev_test"
    assert body["poll_url"] == "/v1/evaluations/ev_test"


def test_create_evaluation_502s_on_dependency_unavailable():
    unavailable = AsyncMock(side_effect=DependencyUnavailable("sandbox", "timeout"))
    with patch("services.gateway.src.main.orchestrate.run_full_evaluation", new=unavailable):
        resp = client.post("/v1/evaluations", json=REQUEST)
    assert resp.status_code == 502


def test_get_evaluation_returns_stored_report():
    with patch("services.gateway.src.main.orchestrate.get_evaluation", return_value={"evaluation_id": "ev_test"}):
        resp = client.get("/v1/evaluations/ev_test")
    assert resp.status_code == 200
    assert resp.json()["evaluation_id"] == "ev_test"


def test_get_evaluation_unknown_id_falls_back_to_golden():
    with patch("services.gateway.src.main.orchestrate.get_evaluation", return_value=None):
        resp = client.get("/v1/evaluations/ev_unknown")
    assert resp.status_code == 200
    assert resp.json()["evaluation_id"] == "ev_stub_0001"  # the golden example's own id
