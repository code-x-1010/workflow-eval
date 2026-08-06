"""POST /v1/spec in both modes.

Stubbed (the default, and what `make dev` runs) it serves the golden example so
nobody wiring against :8002 is blocked. `WFEVAL_STUB_DEPS=0` (`make dev-real`)
runs the real extractor, then the refiner if one is wired, through the disk
cache. The last test in this file is the charter's D3-D4 bar and the reason the
cache exists: the same prompt twice costs zero model calls the second time.
"""
from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from services.intent.src import main
from services.intent.src.extract import EXTRACTOR_VERSION
from services.intent.src.refine import LLMRefiner, cache_version

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


def test_real_mode_returns_sufficiency_diagnostics(real_mode: None) -> None:
    """D5 over the wire. The golden prompt states its trigger, its threshold and
    its budget, and it pays a real invoice -- but it never says what happens when
    paying one fails. That is the single code it earns, and it is the right one."""
    body = client.post("/v1/spec", json={"prompt": PROMPT}).json()
    codes = [d["code"] for d in body["sufficiency_diagnostics"]]
    assert codes == ["SPEC-NO-ERROR-BEHAVIOUR"], codes
    assert all(d["severity"] in {"warning", "info"} for d in body["sufficiency_diagnostics"])


def test_an_under_specified_prompt_earns_several(real_mode: None) -> None:
    body = client.post("/v1/spec", json={"prompt": "Process refunds and update the ledger."}).json()
    codes = {d["code"] for d in body["sufficiency_diagnostics"]}
    assert {"SPEC-NO-TRIGGER", "SPEC-NO-ERROR-BEHAVIOUR", "SPEC-NO-BUDGET"} <= codes


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


# ---------- the refiner, wired the way `make dev-real` wires it ----------


class CountingTransport:
    """Stands in for the model call. Counting is the whole point of the tests
    below -- "zero LLM calls the second time" is not observable without something
    that knows how many calls it took."""

    name = "counting"

    def __init__(self) -> None:
        self.calls = 0

    def complete(self, system: str, user: str, schema: dict[str, object]) -> str:
        self.calls += 1
        return json.dumps({
            "trigger": None,
            "error_behaviour": None,
            # Quoted from contracts/examples/prompt.txt, where the words are split
            # across a line break -- which the grounding check tolerates and this
            # fixture therefore also proves.
            "outputs": [{"name": "paid_invoice", "type": "string",
                         "evidence": "otherwise pay it automatically"}],
            "input_bounds": [],
            "branch_probabilities": [],
            "steps": [],
            "step_dependencies": [],
        })


@pytest.fixture
def refined_mode(real_mode: None, monkeypatch: pytest.MonkeyPatch) -> Iterator[CountingTransport]:
    """Real mode with a refiner wired. The cache version moves with the refiner
    exactly as it does in production -- a fixture that had to hand-hold the key
    would be hiding the bug it is here to catch."""
    transport = CountingTransport()
    refiner = LLMRefiner(transport)
    monkeypatch.setattr(main, "REFINER", refiner)
    monkeypatch.setattr(main.SPEC_CACHE, "version", cache_version(EXTRACTOR_VERSION, refiner))
    yield transport


def test_the_same_prompt_twice_is_zero_model_calls_the_second_time(
    refined_mode: CountingTransport,
) -> None:
    """**The charter's D3-D4 bar, in its own words.** This is what turns a
    40-minute corpus run into a 40-second one, and it is the only test that would
    catch a refiner wired in front of the cache instead of behind it."""
    first = client.post("/v1/spec", json={"prompt": PROMPT}).json()
    assert refined_mode.calls == 1

    second = client.post("/v1/spec", json={"prompt": PROMPT}).json()
    assert refined_mode.calls == 1, "the second request must not reach the model"
    assert second == first, "and it must still get the same answer"


def test_a_different_prompt_does_reach_the_model(refined_mode: CountingTransport) -> None:
    """The other half of the property. A cache that never misses is a cache
    serving one prompt's spec for every prompt."""
    client.post("/v1/spec", json={"prompt": PROMPT})
    client.post("/v1/spec", json={"prompt": "Every night at 2am, archive last month's orders."})
    assert refined_mode.calls == 2


def test_the_refiner_output_reaches_the_response(refined_mode: CountingTransport) -> None:
    """End to end: a grounded proposal survives the merge, the cache and the
    serialiser. `outputs` is residue the extractor always leaves empty, so its
    presence can only have come from the refiner."""
    spec = client.post("/v1/spec", json={"prompt": PROMPT}).json()["spec"]
    assert [f["name"] for f in spec["outputs"]] == ["paid_invoice"]
    assert spec["source"] == "merged"


def test_turning_the_refiner_on_does_not_serve_specs_extracted_without_it(
    real_mode: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The cache-key version earning its keep. Extract once with no refiner, then
    wire one: the second request must recompute, not hand back the thinner spec
    the first one cached."""
    unrefined = client.post("/v1/spec", json={"prompt": PROMPT}).json()["spec"]
    assert unrefined["outputs"] == []

    transport = CountingTransport()
    refiner = LLMRefiner(transport)
    monkeypatch.setattr(main, "REFINER", refiner)
    monkeypatch.setattr(main.SPEC_CACHE, "version", cache_version(EXTRACTOR_VERSION, refiner))

    refined = client.post("/v1/spec", json={"prompt": PROMPT}).json()["spec"]
    assert transport.calls == 1, "a stale entry was served from before the refiner existed"
    assert [f["name"] for f in refined["outputs"]] == ["paid_invoice"]
