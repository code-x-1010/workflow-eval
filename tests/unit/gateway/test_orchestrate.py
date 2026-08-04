"""Gateway orchestration tests. Mocks the HTTP layer (httpx.AsyncClient) --
orchestrate.py always makes real HTTP calls (see its module docstring), so
tests fake the transport rather than the dependency-stub logic, which lives
in each downstream service instead.
"""
from __future__ import annotations

from typing import Any, Self
from unittest.mock import patch

import pytest
from wfeval.core.report import ValidationReport
from wfeval.core.stubs import golden

from services.gateway.src import orchestrate
from services.gateway.src.orchestrate import DependencyUnavailable

DEPLOY_ACCEPTED = {"accepted": True, "diagnostics": []}
DEPLOY_REJECTED = {"accepted": False, "diagnostics": []}

ALL_GATES_OK_ROUTES: dict[str, Any] = {
    "http://validation:8001/v1/validate": golden("validation.response.json"),
    "http://cost:8004/v1/cost": golden("cost.response.json"),
    "http://intent:8002/v1/intent": golden("intent.response.json"),
    "http://intent:8002/v1/testcases": golden("testcases.response.json"),
    "http://sandbox:8003/v1/deploy": DEPLOY_ACCEPTED,
    "http://sandbox:8003/v1/executions": golden("execution.response.json"),
}

FAILING_VALIDATION = {**golden("validation.response.json"), "gates": {"schema_validity": False, "reference_integrity": True}}


class _FakeResponse:
    def __init__(self, payload: Any) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        pass

    def json(self) -> Any:
        return self._payload


def _fake_client(routes: dict[str, Any], calls: list[str]) -> type:
    class _FakeAsyncClient:
        def __init__(self, *a: Any, **kw: Any) -> None:
            pass

        async def __aenter__(self) -> Self:
            return self

        async def __aexit__(self, *a: object) -> bool:
            return False

        async def request(self, method: str, url: str, json: Any = None) -> _FakeResponse:
            calls.append(url)
            if url not in routes:
                raise AssertionError(f"unexpected call to {url} -- short-circuit should have prevented this")
            return _FakeResponse(routes[url])

    return _FakeAsyncClient


REQUEST = {"request_id": "req_test", "platform": "uipath_maestro", "format": "bpmn", "content": "<definitions/>", "prompt": "do the thing"}


@pytest.mark.asyncio
async def test_predeploy_validate_happy_path():
    calls: list[str] = []
    with patch("services.gateway.src.orchestrate.httpx.AsyncClient", _fake_client(ALL_GATES_OK_ROUTES, calls)):
        report = await orchestrate.run_predeploy_validate(REQUEST)
    assert report.short_circuited_at is None
    assert report.validation is not None
    assert report.cost is not None
    assert report.intent is None
    assert report.execution is None
    assert "http://validation:8001/v1/validate" in calls
    assert "http://cost:8004/v1/cost" in calls


@pytest.mark.asyncio
async def test_predeploy_validate_short_circuits_on_gate_failure():
    routes = {**ALL_GATES_OK_ROUTES, "http://validation:8001/v1/validate": FAILING_VALIDATION}
    calls: list[str] = []
    with patch("services.gateway.src.orchestrate.httpx.AsyncClient", _fake_client(routes, calls)):
        report = await orchestrate.run_predeploy_validate(REQUEST)
    assert report.short_circuited_at == "validation"
    assert report.verdict == "fail"
    assert report.overall == 0.0
    assert report.cost is None
    assert "http://cost:8004/v1/cost" not in calls  # short-circuit means Cost is never called


@pytest.mark.asyncio
async def test_full_pipeline_happy_path():
    calls: list[str] = []
    with patch("services.gateway.src.orchestrate.httpx.AsyncClient", _fake_client(ALL_GATES_OK_ROUTES, calls)):
        evaluation_id = await orchestrate.run_full_evaluation(REQUEST)
    stored = orchestrate.get_evaluation(evaluation_id)
    assert stored is not None
    assert stored["short_circuited_at"] is None
    assert stored["validation"] is not None
    assert stored["intent"] is not None
    assert stored["execution"] is not None
    assert stored["cost"] is not None
    assert all(u in calls for u in ALL_GATES_OK_ROUTES)


@pytest.mark.asyncio
async def test_full_pipeline_short_circuits_on_validation_failure():
    routes = {**ALL_GATES_OK_ROUTES, "http://validation:8001/v1/validate": FAILING_VALIDATION}
    calls: list[str] = []
    with patch("services.gateway.src.orchestrate.httpx.AsyncClient", _fake_client(routes, calls)):
        evaluation_id = await orchestrate.run_full_evaluation(REQUEST)
    stored = orchestrate.get_evaluation(evaluation_id)
    assert stored is not None
    assert stored["short_circuited_at"] == "validation"
    assert "http://intent:8002/v1/intent" not in calls
    assert "http://sandbox:8003/v1/deploy" not in calls


@pytest.mark.asyncio
async def test_full_pipeline_short_circuits_on_deploy_rejection():
    routes = {**ALL_GATES_OK_ROUTES, "http://sandbox:8003/v1/deploy": DEPLOY_REJECTED}
    calls: list[str] = []
    with patch("services.gateway.src.orchestrate.httpx.AsyncClient", _fake_client(routes, calls)):
        evaluation_id = await orchestrate.run_full_evaluation(REQUEST)
    stored = orchestrate.get_evaluation(evaluation_id)
    assert stored is not None
    assert stored["short_circuited_at"] == "deploy"
    assert stored["execution"] is None
    assert "http://sandbox:8003/v1/executions" not in calls  # step 3 never runs


@pytest.mark.asyncio
async def test_dependency_unavailable_raises_a_typed_error():
    import httpx

    class _RefusingClient:
        def __init__(self, *a: Any, **kw: Any) -> None:
            pass

        async def __aenter__(self) -> Self:
            return self

        async def __aexit__(self, *a: object) -> bool:
            return False

        async def request(self, *a: Any, **kw: Any) -> Any:
            raise httpx.ConnectError("connection refused")

    with (
        patch("services.gateway.src.orchestrate.httpx.AsyncClient", _RefusingClient),
        pytest.raises(DependencyUnavailable),
    ):
        await orchestrate.run_predeploy_validate(REQUEST)


def test_get_evaluation_unknown_id_returns_none():
    assert orchestrate.get_evaluation("ev_does_not_exist") is None


def test_stopgap_score_zero_when_gate_fails():
    validation = ValidationReport.model_validate(FAILING_VALIDATION)
    overall, verdict = orchestrate._stopgap_score(validation=validation, intent=None, execution=None)
    assert overall == 0.0
    assert verdict == "fail"


def test_stopgap_score_weights_only_present_dimensions():
    validation = ValidationReport(gates={"schema_validity": True}, scores={"structural_soundness": 1.0})
    overall, verdict = orchestrate._stopgap_score(validation=validation, intent=None, execution=None)
    # Only structural_soundness present -> its weighted average IS the score, not diluted by absent dimensions.
    assert overall == 1.0
    assert verdict == "pass"


def test_stopgap_score_thresholds():
    validation = ValidationReport(gates={"schema_validity": True}, scores={"structural_soundness": 0.5})
    overall, verdict = orchestrate._stopgap_score(validation=validation, intent=None, execution=None)
    assert overall == 0.5
    assert verdict == "fail"  # below weights.yaml's fail_below: 0.60
