"""The judge, the calibration, and the house rule that a score ships with its confidence.

The most important test in this file is `test_the_lexical_judge_is_worse_than_a_coin_flip`.
It asserts a *bad* result on purpose: on the residue, lexical similarity is
anti-correlated with intent, and pinning that keeps the number honest. If someone
later tunes a threshold until this test goes green without changing what decides
pairs, they have tuned the answer key rather than the judge.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from services.intent.src import main
from services.intent.src.judge import (
    MIN_TRUSTWORTHY_AGREEMENT,
    Calibration,
    LabelledPair,
    LexicalJudge,
    LLMJudge,
    Verdict,
    calibrate,
    judge_from_env,
    load_calibration_set,
)
from wfeval.core.ir import Spec, Step

ROOT = Path(__file__).resolve().parents[3]


# ---------- the calibration set itself ----------


def test_the_calibration_set_is_committed_and_balanced() -> None:
    """An unbalanced key lets a judge that always answers one way look calibrated."""
    pairs = load_calibration_set()
    assert len(pairs) >= 50, "the charter asks for ~50"
    labels = [p.label for p in pairs]
    assert set(labels) == {"match", "no_match"}
    assert abs(labels.count("match") - labels.count("no_match")) <= 2


def test_every_pair_records_why_and_where_it_came_from() -> None:
    """Provenance is a field so a later human-labelled pass can be mixed in and
    told apart -- see datasets/golden/README.md on why that matters here."""
    for pair in load_calibration_set():
        assert pair.why, f"{pair.id} has no rationale"
        assert pair.provenance


def test_the_set_is_actually_hard_for_a_lexical_matcher() -> None:
    """If the key were easy, agreement on it would measure nothing: `align.py`'s
    matcher already settles easy pairs, and the judge only ever sees the rest."""
    from services.intent.src.align import _similarity

    pairs = load_calibration_set()
    match_sim = [_similarity(p.step, p.element) for p in pairs if p.label == "match"]
    no_match_sim = [_similarity(p.step, p.element) for p in pairs if p.label == "no_match"]
    mean_match = sum(match_sim) / len(match_sim)
    mean_no_match = sum(no_match_sim) / len(no_match_sim)
    assert mean_no_match > mean_match, (
        "the calibration set has stopped being adversarial: lexical similarity now "
        "separates the labels, so it no longer measures the residue"
    )


# ---------- the measured result ----------


def test_the_lexical_judge_is_worse_than_a_coin_flip() -> None:
    """**Asserted deliberately.** 0.407 on a balanced set is worse than chance,
    because on the pairs a text comparison cannot settle, shared vocabulary
    points the wrong way: "revoke access"/"grant access" share every word and are
    opposite acts. No threshold fixes an anti-correlated signal.

    This is the quantitative case for the charter's "reserve the judge for the
    residue", and it is why INT-JUDGE-UNCALIBRATED fires on every real response
    today."""
    result = calibrate(LexicalJudge())
    assert result.agreement < 0.5
    assert not result.trustworthy


def test_a_low_agreement_says_so_loudly() -> None:
    result = calibrate(LexicalJudge())
    assert result.warning is not None
    assert str(MIN_TRUSTWORTHY_AGREEMENT) in result.warning
    assert "upper bound" in result.warning, "the authored-labels caveat must travel with the number"


def test_unsure_counts_against_the_judge() -> None:
    """The most flattering lie a calibration number can tell is to drop the cases
    the judge refused. A judge that abstains on everything must score 0, not 1."""

    class Abstainer:
        name = "abstainer"
        version = "test"

        def judge(self, step: str, element: str) -> Verdict:
            return Verdict.UNSURE

    result = calibrate(Abstainer())
    assert result.agreement == 0.0
    assert result.unsure == result.n


def test_a_perfect_judge_scores_one() -> None:
    pairs = load_calibration_set()
    key = {(p.step, p.element): p.label for p in pairs}

    class Oracle:
        name = "oracle"
        version = "test"

        def judge(self, step: str, element: str) -> Verdict:
            return Verdict(key[(step, element)])

    result = calibrate(Oracle())
    assert result.agreement == 1.0
    assert result.trustworthy
    # Still warns: the labels are P2's own, and that caveat is independent of score.
    assert result.warning is not None and "upper bound" in result.warning


def test_an_empty_calibration_set_is_not_silently_perfect() -> None:
    result = calibrate(LexicalJudge(), pairs=[])
    assert result.agreement == 0.0
    assert result.warning is not None and "not measurable" in result.warning


# ---------- the LLM judge seam ----------


class FakeTransport:
    name = "fake"

    def __init__(self, verdict: str = "match") -> None:
        self.verdict = verdict
        self.calls = 0
        self.last_user = ""

    def complete(self, system: str, user: str, schema: dict[str, object]) -> str:
        self.calls += 1
        self.last_user = user
        return json.dumps({"verdict": self.verdict, "reason": "because"})


def test_the_llm_judge_reads_a_structured_verdict() -> None:
    transport = FakeTransport("no_match")
    assert LLMJudge(transport).judge("Grant access", "Revoke access") == Verdict.NO_MATCH
    assert transport.calls == 1


def test_an_unavailable_judge_returns_unsure_rather_than_guessing() -> None:
    """An unavailable judge that answers MATCH inflates coverage on exactly the
    pairs nobody could settle."""

    class Broken:
        name = "broken"

        def complete(self, system: str, user: str, schema: dict[str, object]) -> str:
            raise RuntimeError("no API key")

    assert LLMJudge(Broken()).judge("a", "b") == Verdict.UNSURE


def test_the_judge_sees_two_strings_and_nothing_else() -> None:
    """The judge is confined to one binary comparison. It never gets the artifact,
    the whole spec, or a score to produce -- that confinement is what makes it
    calibratable at all."""
    transport = FakeTransport()
    LLMJudge(transport).judge("Pay it automatically", "Automatic payment")
    assert "Pay it automatically" in transport.last_user
    assert "Automatic payment" in transport.last_user
    assert "bpmn" not in transport.last_user.lower()


def test_the_default_judge_is_lexical_and_there_is_always_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Never None: something always decides the residue, and whatever it is has to
    be the thing calibrated. A None judge leaves judge_agreement describing a
    component that is not running."""
    monkeypatch.delenv("WFEVAL_INTENT_JUDGE", raising=False)
    assert isinstance(judge_from_env(), LexicalJudge)
    monkeypatch.setenv("WFEVAL_INTENT_JUDGE", "nonsense")
    assert isinstance(judge_from_env(), LexicalJudge)


# ---------- the house rule, over the wire ----------


client = TestClient(main.app)

ARTIFACT = (ROOT / "contracts" / "examples" / "artifact.bpmn").read_text()
PROMPT = (ROOT / "contracts" / "examples" / "prompt.txt").read_text()


@pytest.fixture
def real_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WFEVAL_STUB_DEPS", "0")


def test_a_score_never_ships_without_its_agreement(real_mode: None) -> None:
    """The house rule, and the contract's `if/then`. Checked here as well as in
    the contract suite because this is the endpoint that could break it."""
    simple = _simple_artifact()
    response = client.post("/v1/intent", json={"prompt": PROMPT, "artifact": simple})
    assert response.status_code == 200, response.text
    body = response.json()
    if body["scores"]:
        assert body["judge_agreement"] is not None
        assert 0.0 <= body["judge_agreement"] <= 1.0


def test_an_untrustworthy_judge_is_reported_in_the_diagnostics(real_mode: None) -> None:
    """"Say so loudly" has to mean something a consumer can read. IntentReport has
    nowhere to put prose, so the caveat is a diagnostic or it does not travel."""
    body = client.post("/v1/intent", json={"prompt": PROMPT, "artifact": _simple_artifact()}).json()
    codes = [d["code"] for d in body["diagnostics"]]
    assert "INT-JUDGE-UNCALIBRATED" in codes
    warning = next(d for d in body["diagnostics"] if d["code"] == "INT-JUDGE-UNCALIBRATED")
    assert "%" in warning["message"]


def test_an_unparseable_artifact_is_422_not_a_zero_score(real_mode: None) -> None:
    """Scoring an unparseable artifact as badly-aligned would attribute an adapter
    limitation to the generator's output quality -- `0020`, where five corpus
    artifacts hit exactly this."""
    response = client.post("/v1/intent", json={"prompt": PROMPT, "artifact": "<not-bpmn/>"})
    assert response.status_code == 422
    assert "could not be parsed" in response.json()["detail"]


def test_a_dmn_decision_model_is_422_not_an_empty_alignment(real_mode: None) -> None:
    """A decision table has no steps, no trigger and no ordering, so aligning a
    spec against one would report every step missing and score ~0 -- attributing
    an adapter behaviour to output quality, as above.

    It is rejected at the parser rather than by a kind check: `IntentRequest.artifact`
    is a bare string, and the dispatching `parse()` only returns a `DecisionModel`
    for a dict. Pinned because the safety here is a *consequence* of two other
    choices rather than a check anyone wrote, and either could move."""
    dmn = (Path(__file__).resolve().parents[2] / "fixtures/dmn/approval_decision.dmn").read_text()
    response = client.post("/v1/intent", json={"prompt": PROMPT, "artifact": dmn})
    assert response.status_code == 422
    assert "could not be parsed" in response.json()["detail"]


def test_a_supplied_spec_is_used_and_its_drift_reported(real_mode: None) -> None:
    """The charter: use theirs, and additionally report theirs versus ours."""
    theirs = Spec(
        trigger="a human uploads a PDF",
        steps=[Step(id="s1", description="Do the thing", kind_hint="service",
                    depends_on=[], is_deterministic=True, side_effecting=True)],
        source="upstream",
    )
    body = client.post("/v1/intent", json={
        "prompt": PROMPT, "artifact": _simple_artifact(), "spec": theirs.model_dump(),
    }).json()
    assert body["spec_source"] == "upstream"
    drift = [d for d in body["diagnostics"] if d["code"] == "INT-SPEC-DRIFT"]
    assert drift, [d["code"] for d in body["diagnostics"]]
    assert drift[0]["severity"] == "info", "neither reading is authoritative"


def test_the_stub_still_serves_the_golden_example_by_default() -> None:
    """`make dev` must keep working for the three agents wired against :8002."""
    body = client.post("/v1/intent", json={"prompt": PROMPT, "artifact": ARTIFACT}).json()
    golden = json.loads((ROOT / "contracts" / "examples" / "intent.response.json").read_text())
    assert body["scores"] == golden["scores"]
    assert "_note" not in body


def _simple_artifact() -> str:
    import sys

    if str(ROOT / "datasets") not in sys.path:
        sys.path.insert(0, str(ROOT / "datasets"))
    from tools.bpmn import emit, end, start, task

    return emit("invoice", [
        start("Start_invoice", "Invoice received by email", message=True),
        task("Task_extract", "Extract vendor and amount", "service"),
        task("Task_approve", "Manager approval", "user"),
        task("Task_autopay", "Pay it automatically", "service"),
        end("End_done", "Done"),
    ])


def test_calibration_is_computed_once_not_per_request() -> None:
    """With an LLM judge this would be 54 model calls. On the request path that is
    a latency and cost bug that only shows up in production."""
    assert isinstance(main.CALIBRATION, Calibration)
    assert main.CALIBRATION.n == len(load_calibration_set())


def test_labelled_pair_round_trips() -> None:
    pair = LabelledPair(id="x", step="a", element="b", label="match", why="w", provenance="test")
    assert pair.label == "match"
