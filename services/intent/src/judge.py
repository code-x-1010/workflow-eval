"""The judge for the fuzzy residue, and the agreement number that must ship with it. D7.

## What the judge is allowed to decide

One question, on one pair at a time: *does this artifact element implement this
spec step?* Nothing else. It does not score a workflow, does not read the whole
artifact, and never emits an `INT-*` code -- those all come from the deterministic
diff in `align.py`, which can explain itself.

The charter's trap for this service is the reason: *"the temptation is to hand
the prompt and the artifact to an LLM and ask 'does this match?'. That produces
unstable, unexplainable scores."* A judge confined to one binary comparison, run
only on pairs the lexical matcher could not settle, is the smallest version of
this that still buys something -- and it is small enough to calibrate.

## `judge_agreement` is not optional and not decorative

`IntentReport` documents it as *"Ship the score WITH this or not at all"*, and
`contracts/intent.openapi.yaml` encodes that as an `if/then`: non-empty `scores`
requires a non-null `judge_agreement`. So the number has to exist on every
report, which means it has to be *measured*, not asserted.

`calibrate()` measures it: run whatever is actually deciding pairs against
`datasets/golden/intent_judgements.jsonl` and report the fraction it gets right.
**When no LLM judge is configured -- the default, since this repo has no LLM
client -- the thing deciding pairs is the lexical matcher, so that is what gets
calibrated and reported.** That is an honest answer to "how much do you trust
this score", and it avoids the alternative of publishing `1.0` or `null` and
hoping nobody reads it.

Below `MIN_TRUSTWORTHY_AGREEMENT` the charter says to say so loudly rather than
ship a confident-looking number. `Calibration.warning` is that, in words, and it
travels with the report.

Owner: P2.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, ClassVar, Protocol

log = logging.getLogger(__name__)

JUDGE_VERSION = "d7.1"

# The charter's bar: "If agreement is below ~0.8, say so loudly rather than
# shipping a confident-looking number."
MIN_TRUSTWORTHY_AGREEMENT = 0.8

CALIBRATION_PATH = Path(__file__).resolve().parents[3] / "datasets" / "golden" / "intent_judgements.jsonl"


class Verdict(str, Enum):
    MATCH = "match"
    NO_MATCH = "no_match"
    UNSURE = "unsure"


@dataclass
class LabelledPair:
    id: str
    step: str
    element: str
    label: str
    why: str = ""
    provenance: str = "unknown"


class Judge(Protocol):
    name: str
    version: str

    def judge(self, step: str, element: str) -> Verdict: ...


# ---------- the deterministic baseline ----------


class LexicalJudge:
    """The default. Reuses `align._similarity`, so calibrating it measures the
    matcher that is actually deciding pairs today rather than a stand-in.

    It returns `UNSURE` in a band around the threshold instead of forcing a call.
    That band is the residue an LLM judge would be given, and reporting its size
    is more useful than pretending a coin-flip was a decision.
    """

    name = "lexical"
    version = JUDGE_VERSION

    def __init__(self, match_at: float = 0.5, unsure_below: float = 0.34) -> None:
        self.match_at = match_at
        self.unsure_below = unsure_below

    def judge(self, step: str, element: str) -> Verdict:
        from .align import _similarity

        score = _similarity(step, element)
        if score >= self.match_at:
            return Verdict.MATCH
        if score < self.unsure_below:
            return Verdict.NO_MATCH
        return Verdict.UNSURE


class LLMJudge:
    """The judge proper, wired the same way `refine.py` wires its refiner: the
    transport is injected, so the prompt, the parsing and the fallback are all
    testable with no network and no key.

    Fails to `UNSURE` rather than guessing. An unavailable judge that silently
    answers `MATCH` inflates coverage on exactly the pairs nobody could settle.
    """

    name = "llm"
    version = JUDGE_VERSION

    def __init__(self, transport: Any) -> None:
        self.transport = transport
        self.name = f"llm:{getattr(transport, 'name', 'unknown')}"

    SYSTEM = (
        "You decide whether one step of a described process is implemented by one task in a "
        "workflow that was built from that description.\n\n"
        "Answer about the ACT, not the wording. 'File the receipt' and 'Archive receipt' are the "
        "same act. 'Revoke access' and 'Grant access' are opposite acts that happen to share "
        "almost every word. Different recipient, different direction of funds, or different "
        "outcome all mean no.\n\n"
        "You are seeing this pair because simple text comparison could not settle it, so shared "
        "vocabulary is not evidence either way. If you genuinely cannot tell, say unsure -- an "
        "unsure answer is handled; a confident wrong one is not."
    )

    SCHEMA: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "verdict": {"type": "string", "enum": ["match", "no_match", "unsure"]},
            "reason": {"type": "string"},
        },
        "required": ["verdict", "reason"],
        "additionalProperties": False,
    }

    def judge(self, step: str, element: str) -> Verdict:
        user = f"Process step:\n  {step}\n\nWorkflow task:\n  {element}\n\nSame act?"
        try:
            raw = self.transport.complete(self.SYSTEM, user, self.SCHEMA)
            verdict = json.loads(raw)["verdict"]
            return Verdict(verdict)
        except Exception as exc:  # noqa: BLE001 -- an unavailable judge is not an error
            log.warning("judge %s could not decide (%s); returning unsure", self.name, exc)
            return Verdict.UNSURE


# ---------- calibration ----------


@dataclass
class Calibration:
    """A measured agreement figure and everything needed to distrust it."""

    judge: str
    agreement: float
    n: int
    unsure: int
    disagreements: list[str] = field(default_factory=list)
    provenance: dict[str, int] = field(default_factory=dict)
    warning: str | None = None

    @property
    def trustworthy(self) -> bool:
        return self.agreement >= MIN_TRUSTWORTHY_AGREEMENT


def load_calibration_set(path: Path | None = None) -> list[LabelledPair]:
    source = path or CALIBRATION_PATH
    pairs = []
    for line in source.read_text().splitlines():
        if line.strip():
            pairs.append(LabelledPair(**json.loads(line)))
    return pairs


def calibrate(judge: Judge, pairs: list[LabelledPair] | None = None) -> Calibration:
    """Agreement between `judge` and the answer key.

    `UNSURE` counts as a **disagreement**, not as an abstention removed from the
    denominator. Dropping unsure answers would let a judge that answers "unsure"
    to everything report perfect agreement over the two pairs it did decide,
    which is the most flattering possible lie a calibration number can tell.
    """
    cases = pairs if pairs is not None else load_calibration_set()
    if not cases:
        return Calibration(judge=judge.name, agreement=0.0, n=0, unsure=0,
                           warning="the calibration set is empty; judge_agreement is not measurable")

    correct = 0
    unsure = 0
    disagreements: list[str] = []
    provenance: dict[str, int] = {}
    for case in cases:
        provenance[case.provenance] = provenance.get(case.provenance, 0) + 1
        verdict = judge.judge(case.step, case.element)
        if verdict == Verdict.UNSURE:
            unsure += 1
            disagreements.append(f"{case.id}: unsure ({case.step!r} / {case.element!r})")
        elif verdict.value == case.label:
            correct += 1
        else:
            disagreements.append(f"{case.id}: said {verdict.value}, key says {case.label}")

    agreement = correct / len(cases)
    warnings = []
    if agreement < MIN_TRUSTWORTHY_AGREEMENT:
        warnings.append(
            f"judge/key agreement is {agreement:.2f}, below the {MIN_TRUSTWORTHY_AGREEMENT} bar. "
            "Treat intent scores from this configuration as indicative only."
        )
    authored = provenance.get("authored_by_p2", 0)
    if authored:
        warnings.append(
            f"{authored} of {len(cases)} calibration labels were authored by P2 rather than by an "
            "independent labeller, so this figure is an upper bound. See datasets/golden/README.md."
        )
    return Calibration(
        judge=judge.name, agreement=round(agreement, 3), n=len(cases), unsure=unsure,
        disagreements=disagreements, provenance=provenance,
        warning=" ".join(warnings) or None,
    )


def judge_from_env() -> Judge:
    """The judge `/v1/intent` runs. Lexical unless asked otherwise.

    Never returns None: something always decides the residue, and whatever it is
    has to be the thing that gets calibrated. A `None` judge would leave
    `judge_agreement` describing a component that is not running.
    """
    choice = os.environ.get("WFEVAL_INTENT_JUDGE", "lexical").strip().lower()
    if choice in {"llm", "anthropic"}:
        from .refine import AnthropicTransport

        return LLMJudge(AnthropicTransport())
    if choice not in {"", "lexical", "off", "none"}:
        log.warning("unknown WFEVAL_INTENT_JUDGE=%r, falling back to the lexical judge", choice)
    return LexicalJudge()
