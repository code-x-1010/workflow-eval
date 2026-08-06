"""D9 webhook delivery: HMAC signing + retry. Mocks httpx.AsyncClient, same
convention as test_orchestrate.py -- fakes the transport, not the logic."""
from __future__ import annotations

import hashlib
import hmac
from typing import Any, Self
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from services.gateway.src import webhook
from wfeval.core.report import EvaluationReport, Verdict

_REPORT = EvaluationReport(
    evaluation_id="ev_test", request_id="req_test", platform="uipath_maestro",
    verdict=Verdict.PASS, scoring_version="0.1.0", overall=0.9,
)


def test_sign_is_deterministic_hmac_sha256():
    body = b'{"a": 1}'
    sig = webhook.sign("secret", body)
    expected = "sha256=" + hmac.new(b"secret", body, hashlib.sha256).hexdigest()
    assert sig == expected


@pytest.mark.asyncio
async def test_unsupported_scheme_is_rejected(monkeypatch):
    monkeypatch.setenv("GATEWAY_WEBHOOK_SECRET", "shh")
    with patch("services.gateway.src.webhook.httpx.AsyncClient") as mock_client:
        result = await webhook.deliver("ftp://evil.example/hook", _REPORT)
    assert result is False
    mock_client.assert_not_called()


@pytest.mark.asyncio
async def test_missing_secret_skips_delivery_without_raising(monkeypatch):
    monkeypatch.delenv("GATEWAY_WEBHOOK_SECRET", raising=False)
    with patch("services.gateway.src.webhook.httpx.AsyncClient") as mock_client:
        result = await webhook.deliver("https://example.com/hook", _REPORT)
    assert result is False
    mock_client.assert_not_called()


@pytest.mark.asyncio
async def test_successful_delivery_signs_the_exact_body_sent(monkeypatch):
    monkeypatch.setenv("GATEWAY_WEBHOOK_SECRET", "shh")
    sent: dict[str, Any] = {}

    class _FakeResponse:
        def raise_for_status(self) -> None:
            pass

    class _FakeAsyncClient:
        def __init__(self, *a: Any, **kw: Any) -> None:
            pass

        async def __aenter__(self) -> Self:
            return self

        async def __aexit__(self, *a: object) -> bool:
            return False

        async def post(self, url: str, *, content: bytes, headers: dict[str, str]) -> _FakeResponse:
            sent["url"] = url
            sent["content"] = content
            sent["headers"] = headers
            return _FakeResponse()

    with patch("services.gateway.src.webhook.httpx.AsyncClient", _FakeAsyncClient):
        result = await webhook.deliver("https://example.com/hook", _REPORT)

    assert result is True
    assert sent["url"] == "https://example.com/hook"
    expected_sig = webhook.sign("shh", sent["content"])
    assert sent["headers"]["X-Wfeval-Signature"] == expected_sig
    assert sent["content"] == _REPORT.model_dump_json().encode("utf-8")


@pytest.mark.asyncio
async def test_retries_on_failure_then_succeeds(monkeypatch):
    monkeypatch.setenv("GATEWAY_WEBHOOK_SECRET", "shh")
    attempts = {"n": 0}

    class _FakeResponse:
        def raise_for_status(self) -> None:
            pass

    class _FlakyClient:
        def __init__(self, *a: Any, **kw: Any) -> None:
            pass

        async def __aenter__(self) -> Self:
            return self

        async def __aexit__(self, *a: object) -> bool:
            return False

        async def post(self, *a: Any, **kw: Any) -> _FakeResponse:
            attempts["n"] += 1
            if attempts["n"] < 3:
                raise httpx.ConnectError("refused")
            return _FakeResponse()

    with (
        patch("services.gateway.src.webhook.httpx.AsyncClient", _FlakyClient),
        patch("services.gateway.src.webhook.asyncio.sleep", new=AsyncMock()),
    ):
        result = await webhook.deliver("https://example.com/hook", _REPORT)

    assert result is True
    assert attempts["n"] == 3


@pytest.mark.asyncio
async def test_gives_up_after_max_attempts(monkeypatch):
    monkeypatch.setenv("GATEWAY_WEBHOOK_SECRET", "shh")
    attempts = {"n": 0}

    class _AlwaysFailsClient:
        def __init__(self, *a: Any, **kw: Any) -> None:
            pass

        async def __aenter__(self) -> Self:
            return self

        async def __aexit__(self, *a: object) -> bool:
            return False

        async def post(self, *a: Any, **kw: Any) -> Any:
            attempts["n"] += 1
            raise httpx.ConnectError("refused")

    with (
        patch("services.gateway.src.webhook.httpx.AsyncClient", _AlwaysFailsClient),
        patch("services.gateway.src.webhook.asyncio.sleep", new=AsyncMock()),
    ):
        result = await webhook.deliver("https://example.com/hook", _REPORT)

    assert result is False
    assert attempts["n"] == webhook._MAX_ATTEMPTS
