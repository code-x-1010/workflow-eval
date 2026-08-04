"""POST /v1/spec in both modes.

Stubbed (the default, and what `make dev` runs) it serves the golden example so
nobody wiring against :8002 is blocked. `WFEVAL_STUB_DEPS=0` (`make dev-real`)
runs the real extractor through the disk cache.
"""
from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from services.intent.src import main

ROOT = Path(__file__).resolve().parents[3]
PROMPT = (ROOT / "contracts" / "examples" / "prompt.txt").read_text()

client = TestClient(main.app)


@pytest.fixture
def real_mode(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Real extraction, with the cache pointed somewhere disposable so a test
    run never writes into the repo or reads a previous run's entries."""
    monkeypatch.setenv("WFEVAL_STUB_DEPS", "0")
    monkeypatch.setattr(main.SPEC_CACHE, "root", tmp_path)
    monkeypatch.setattr(main.SPEC_CACHE, "stats", type(main.SPEC_CACHE.stats)())
    yield


def test_stubbed_by_default_returns_the_golden_example() -> None:
    body = client.post("/v1/spec", json={"prompt": PROMPT}).json()
    golden = json.loads((ROOT / "contracts" / "examples" / "spec.response.json").read_text())
    assert body["spec"] == golden["spec"]
    assert body["sufficiency_diagnostics"] == golden["sufficiency_diagnostics"]


def test_real_mode_extracts_from_the_prompt(real_mode: None) -> None:
    body = client.post("/v1/spec", json={"prompt": PROMPT}).json()
    spec = body["spec"]
    assert spec["trigger"] == "an invoice arrives by email"
    assert spec["budget_per_instance"] == 0.50
    assert spec["source"] == "extracted"
    assert body["sufficiency_diagnostics"] == [], "SPEC-* codes are D5, and an empty list says so honestly"


def test_real_mode_varies_with_the_prompt(real_mode: None) -> None:
    """The stub returns the same spec whatever you send it. The real path must
    not -- this is the test that would have caught a stub left wired in."""
    other = "Every night at 2am, archive last month's orders."
    first = client.post("/v1/spec", json={"prompt": PROMPT}).json()["spec"]
    second = client.post("/v1/spec", json={"prompt": other}).json()["spec"]
    assert first != second
    assert second["trigger"] == "Every night at 2am"


def test_the_same_prompt_twice_hits_the_cache(real_mode: None) -> None:
    """The charter's D3-D4 bar. With an LLM refiner wired at D4 this is the
    difference between a 40-minute corpus run and a 40-second one."""
    client.post("/v1/spec", json={"prompt": PROMPT})
    client.post("/v1/spec", json={"prompt": PROMPT})
    assert (main.SPEC_CACHE.stats.misses, main.SPEC_CACHE.stats.hits) == (1, 1)


def test_the_cached_response_is_identical(real_mode: None) -> None:
    first = client.post("/v1/spec", json={"prompt": PROMPT}).json()
    second = client.post("/v1/spec", json={"prompt": PROMPT}).json()
    assert first == second


def test_the_cache_key_is_the_prompt_not_the_whole_request(real_mode: None) -> None:
    """`platform` does not change what is extracted from the prompt today. If
    it ever does, this test fails and the key needs it."""
    client.post("/v1/spec", json={"prompt": PROMPT, "platform": "uipath_maestro"})
    client.post("/v1/spec", json={"prompt": PROMPT, "platform": "n8n"})
    assert main.SPEC_CACHE.stats.hits == 1
