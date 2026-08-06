"""Gateway orchestration tests. Mocks the HTTP layer (httpx.AsyncClient) --
orchestrate.py always makes real HTTP calls (see its module docstring), so
tests fake the transport rather than the dependency-stub logic, which lives
in each downstream service instead.
"""
from __future__ import annotations

from typing import Any, Self
from unittest.mock import AsyncMock, patch

import pytest
from wfeval.core.report import ValidationReport
from wfeval.core.stubs import golden

from services.gateway.src import orchestrate
from services.gateway.src.orchestrate import DependencyUnavailable

DEPLOY_ACCEPTED = {"accepted": True, "diagnostics": []}
DEPLOY_REJECTED = {"accepted": False, "diagnostics": []}


@pytest.fixture(autouse=True)
def _reset_gateway_state():
    """D9 idempotency (decision 0018) keys off request_id in a module-level
    dict, and most tests here reuse the same REQUEST fixture's request_id --
    without this, the second+ test to call run_full_evaluation(REQUEST)
    would just get the first test's cached result back, which is correct
    idempotency behavior but wrong test isolation."""
    orchestrate._EVALUATIONS.clear()
    orchestrate._REQUEST_ID_INDEX.clear()
    yield
    orchestrate._EVALUATIONS.clear()
    orchestrate._REQUEST_ID_INDEX.clear()


# /v1/executions is 202-shaped: POST returns {execution_id, poll_url}, the
# real ExecutionReport lives behind the GET -- see orchestrate.py's stage-3
# comment for why this is two routes, not one.
ALL_GATES_OK_ROUTES: dict[str, Any] = {
    "http://validation:8001/v1/validate": golden("validation.response.json"),
    "http://cost:8004/v1/cost": golden("cost.response.json"),
    "http://intent:8002/v1/intent": golden("intent.response.json"),
    "http://intent:8002/v1/testcases": golden("testcases.response.json"),
    "http://sandbox:8003/v1/deploy": DEPLOY_ACCEPTED,
    "http://sandbox:8003/v1/executions": {"execution_id": "ex_test", "poll_url": "/v1/executions/ex_test"},
    "http://sandbox:8003/v1/executions/ex_test": golden("execution.response.json"),
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


REQUEST = {
    "request_id": "req_test", "platform": "uipath_maestro",
    "artifact": {"format": "bpmn", "content": "<definitions/>"}, "prompt": "do the thing",
}


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
async def test_replaying_request_id_is_idempotent():
    """D9 (decision 0018): a second call with the same request_id must not
    re-run the pipeline -- verified by asserting the fake transport is only
    ever hit once, not just that the returned id matches."""
    calls: list[str] = []
    with patch("services.gateway.src.orchestrate.httpx.AsyncClient", _fake_client(ALL_GATES_OK_ROUTES, calls)):
        first_id = await orchestrate.run_full_evaluation(REQUEST)
        calls_after_first = len(calls)
        second_id = await orchestrate.run_full_evaluation(REQUEST)

    assert second_id == first_id
    assert len(calls) == calls_after_first  # no new HTTP calls on the replay


@pytest.mark.asyncio
async def test_different_request_ids_both_run():
    calls: list[str] = []
    other_request = {**REQUEST, "request_id": "req_other"}
    with patch("services.gateway.src.orchestrate.httpx.AsyncClient", _fake_client(ALL_GATES_OK_ROUTES, calls)):
        first_id = await orchestrate.run_full_evaluation(REQUEST)
        second_id = await orchestrate.run_full_evaluation(other_request)
    assert first_id != second_id


@pytest.mark.asyncio
async def test_callback_url_triggers_webhook_delivery(monkeypatch):
    monkeypatch.setenv("GATEWAY_WEBHOOK_SECRET", "shh")
    request_with_callback = {**REQUEST, "callback_url": "https://example.com/hook"}
    calls: list[str] = []
    with (
        patch("services.gateway.src.orchestrate.httpx.AsyncClient", _fake_client(ALL_GATES_OK_ROUTES, calls)),
        patch("services.gateway.src.orchestrate.webhook.deliver", new=AsyncMock(return_value=True)) as mock_deliver,
    ):
        await orchestrate.run_full_evaluation(request_with_callback)
    mock_deliver.assert_awaited_once()
    assert mock_deliver.await_args.args[0] == "https://example.com/hook"


@pytest.mark.asyncio
async def test_no_callback_url_never_calls_webhook():
    calls: list[str] = []
    with (
        patch("services.gateway.src.orchestrate.httpx.AsyncClient", _fake_client(ALL_GATES_OK_ROUTES, calls)),
        patch("services.gateway.src.orchestrate.webhook.deliver", new=AsyncMock()) as mock_deliver,
    ):
        await orchestrate.run_full_evaluation(REQUEST)
    mock_deliver.assert_not_awaited()


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


def test_artifact_body_reads_the_nested_contract_shape():
    """Regression test: _artifact_body used to read format/content as flat
    top-level request fields, contradicting contracts/gateway.openapi.yaml's
    ArtifactSubmission (artifact: {format, content}, nested) -- every real
    client following the published contract got a 500. Found while writing
    the D10 integration guide's sample client against a live server. See
    docs/handoff/P1.md, 2026-08-06 entry."""
    body = orchestrate._artifact_body({"artifact": {"format": "dmn", "content": "<definitions/>"}})
    assert body == {"format": "dmn", "content": "<definitions/>"}


def test_artifact_body_defaults_format_to_bpmn():
    body = orchestrate._artifact_body({"artifact": {"content": "<definitions/>"}})
    assert body["format"] == "bpmn"


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
