"""L2: reference integrity against a (mocked) asset registry.

l2_references.check() makes a real HTTP call (httpx.get) -- same convention
as services/gateway/src/orchestrate.py's tests, mock the transport, not the
business logic. contracts/examples/assets.response.json is used as the
"real registry" payload where a test wants a realistic shape rather than a
hand-built minimal one.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import Mock, patch

import httpx
from wfeval.adapters.bpmn import parse
from wfeval.core.ast import Element, ElementKind, WorkflowAST

from services.validation.src import l2_references

ROOT = Path(__file__).resolve().parents[3]
ASSETS_URL = "http://sandbox:8003/v1/assets"


def _el(id_: str, **kw: object) -> Element:
    return Element(id=id_, kind=ElementKind.SERVICE_TASK, locator=f"/definitions/process/x[@id='{id_}']", **kw)  # type: ignore[arg-type]


def _ast(elements: list[Element]) -> WorkflowAST:
    return WorkflowAST(platform="uipath_maestro", process_id="p", elements=elements, flows=[])


def _fake_response(payload: object, status: int = 200) -> Mock:
    resp = Mock()
    resp.json.return_value = payload
    if status >= 400:
        resp.raise_for_status.side_effect = httpx.HTTPStatusError("error", request=Mock(), response=resp)
    else:
        resp.raise_for_status.return_value = None
    return resp


def test_no_asset_refs_trivially_passes_without_calling_out():
    ast = _ast([_el("t")])
    with patch("services.validation.src.l2_references.httpx.get") as mock_get:
        diagnostics, gate = l2_references.check(ast, assets_url=ASSETS_URL)
    mock_get.assert_not_called()
    assert diagnostics == []
    assert gate is True


def test_unreachable_registry_returns_none_not_false():
    ast = _ast([_el("t", asset_ref="ChargePayment")])
    with patch("services.validation.src.l2_references.httpx.get", side_effect=httpx.ConnectError("refused")):
        diagnostics, gate = l2_references.check(ast, assets_url=ASSETS_URL)
    assert diagnostics == []
    assert gate is None  # distinct from False -- caller must NOT treat this as a failed gate


def test_asset_found_and_deployed_is_clean():
    ast = _ast([_el("t", asset_ref="ChargePayment")])
    registry = {"folder": "sandbox-eval", "assets": [{"name": "ChargePayment", "type": "process", "deployed": True}]}
    with patch("services.validation.src.l2_references.httpx.get", return_value=_fake_response(registry)):
        diagnostics, gate = l2_references.check(ast, assets_url=ASSETS_URL)
    assert diagnostics == []
    assert gate is True


def test_asset_not_in_registry_is_flagged():
    ast = _ast([_el("t", asset_ref="DoesNotExist")])
    registry = {"folder": "sandbox-eval", "assets": [{"name": "ChargePayment", "type": "process", "deployed": True}]}
    with patch("services.validation.src.l2_references.httpx.get", return_value=_fake_response(registry)):
        diagnostics, gate = l2_references.check(ast, assets_url=ASSETS_URL)
    assert len(diagnostics) == 1
    assert diagnostics[0].code == "REF-ASSET-NOT-FOUND"
    assert diagnostics[0].severity.value == "error"
    assert diagnostics[0].element_id == "t"
    assert gate is False


def test_asset_in_registry_but_not_deployed_is_flagged():
    ast = _ast([_el("t", asset_ref="ChargePayment")])
    registry = {"folder": "sandbox-eval", "assets": [{"name": "ChargePayment", "type": "process", "deployed": False}]}
    with patch("services.validation.src.l2_references.httpx.get", return_value=_fake_response(registry)):
        diagnostics, gate = l2_references.check(ast, assets_url=ASSETS_URL)
    assert len(diagnostics) == 1
    assert diagnostics[0].code == "REF-ASSET-NOT-DEPLOYED"
    assert gate is False


def test_same_missing_asset_referenced_twice_flags_both_elements():
    ast = _ast([_el("a", asset_ref="Ghost"), _el("b", asset_ref="Ghost")])
    registry = {"folder": "sandbox-eval", "assets": []}
    with patch("services.validation.src.l2_references.httpx.get", return_value=_fake_response(registry)):
        diagnostics, gate = l2_references.check(ast, assets_url=ASSETS_URL)
    assert {d.element_id for d in diagnostics} == {"a", "b"}
    assert gate is False


def test_real_fixture_resolves_against_the_real_golden_registry():
    """adapter_rich.bpmn references ChargePayment and NotifyVendor; the
    shared golden assets.response.json has both, deployed."""
    ast = parse((ROOT / "tests/fixtures/bpmn/adapter_rich.bpmn").read_text(), platform="uipath_maestro")
    registry = json.loads((ROOT / "contracts/examples/assets.response.json").read_text())
    with patch("services.validation.src.l2_references.httpx.get", return_value=_fake_response(registry)):
        diagnostics, gate = l2_references.check(ast, assets_url=ASSETS_URL)
    assert diagnostics == []
    assert gate is True
