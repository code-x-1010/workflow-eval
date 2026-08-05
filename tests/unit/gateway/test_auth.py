"""D9 API-key auth. Tests both the bare dependency function and the wired-in
behavior through main.py's actual routes."""
from __future__ import annotations

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from services.gateway.src.auth import require_api_key
from services.gateway.src.main import app

client = TestClient(app)


def test_open_when_env_var_unset(monkeypatch):
    monkeypatch.delenv("GATEWAY_API_KEYS", raising=False)
    require_api_key(x_api_key=None)  # must not raise


def test_rejects_missing_key_when_configured(monkeypatch):
    monkeypatch.setenv("GATEWAY_API_KEYS", "key-a,key-b")
    with pytest.raises(HTTPException) as exc_info:
        require_api_key(x_api_key=None)
    assert exc_info.value.status_code == 401


def test_rejects_wrong_key_when_configured(monkeypatch):
    monkeypatch.setenv("GATEWAY_API_KEYS", "key-a,key-b")
    with pytest.raises(HTTPException) as exc_info:
        require_api_key(x_api_key="not-a-real-key")
    assert exc_info.value.status_code == 401


def test_accepts_any_configured_key(monkeypatch):
    monkeypatch.setenv("GATEWAY_API_KEYS", "key-a,key-b")
    require_api_key(x_api_key="key-a")  # must not raise
    require_api_key(x_api_key="key-b")  # must not raise


def test_healthz_never_requires_a_key(monkeypatch):
    monkeypatch.setenv("GATEWAY_API_KEYS", "key-a")
    resp = client.get("/healthz")
    assert resp.status_code == 200


def test_evaluations_get_rejects_without_key_when_configured(monkeypatch):
    monkeypatch.setenv("GATEWAY_API_KEYS", "key-a")
    resp = client.get("/v1/evaluations/ev_whatever")
    assert resp.status_code == 401


def test_evaluations_get_allows_with_correct_key(monkeypatch):
    monkeypatch.setenv("GATEWAY_API_KEYS", "key-a")
    resp = client.get("/v1/evaluations/ev_whatever", headers={"X-Api-Key": "key-a"})
    assert resp.status_code == 200  # falls back to the golden example, but that's main.py's job, not auth's


def test_evaluations_get_open_when_unset(monkeypatch):
    monkeypatch.delenv("GATEWAY_API_KEYS", raising=False)
    resp = client.get("/v1/evaluations/ev_whatever")
    assert resp.status_code == 200
