"""Deterministic extraction: prompt -> Spec.

Two kinds of test here, and the second kind matters more.

1. Each rule does what it claims on a phrasing the corpus actually contains.
2. Each rule *declines* on the phrasings that look like a match and are not.
   Every one of these is a real false positive that this extractor produced
   against `datasets/corpus/` before the rule was tightened. An invented
   trigger, or a branch on a variable called `anything`, is worse than an empty
   field: it is confident, plausible, and wrong all the way through to D8's
   boundary cases and P4's cost model.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from wfeval.core.ir import Spec

from services.intent.src.extract import Refiner, extract

ROOT = Path(__file__).resolve().parents[3]
CORPUS = ROOT / "datasets" / "corpus"
SHARED_PROMPT = (ROOT / "contracts" / "examples" / "prompt.txt").read_text()


def prompt_for(case_id: str) -> str:
    return (CORPUS / case_id / "prompt.txt").read_text()


# ---------- the shared fixture, end to end ----------


def test_the_shared_prompt_extracts_what_the_golden_spec_says() -> None:
    """contracts/examples/prompt.txt against contracts/examples/spec.response.json.
    Not field-for-field -- the golden example is hand-written and includes
    residue this extractor deliberately leaves empty -- but every deterministic
    field has to agree, or one of the two is wrong."""
    spec = extract(SHARED_PROMPT)

    assert spec.trigger == "an invoice arrives by email"
    assert [b.expression_hint for b in spec.branches] == ["amount > 10000"]
    assert spec.branches[0].probability_hint == 0.1
    assert spec.budget_per_instance == 0.50
    assert spec.integrations == ["email"]
    assert spec.source == "extracted"
    assert [s.kind_hint for s in spec.steps] == ["agent", "user", "service", "service"]
    assert [s.id for s in spec.steps] == ["s1", "s2", "s3", "s4"]
    assert [s.depends_on for s in spec.steps] == [[], ["s1"], ["s2"], ["s3"]]
    assert spec.steps[0].is_deterministic is False, "an extraction step is the agent, not a rule"
    assert spec.steps[2].side_effecting is True, "paying is side-effecting"


def test_budget_matches_the_golden_spec() -> None:
    golden = json.loads((ROOT / "contracts" / "examples" / "spec.response.json").read_text())["spec"]
    assert extract(SHARED_PROMPT).budget_per_instance == golden["budget_per_instance"]


# ---------- triggers ----------


@pytest.mark.parametrize(
    ("case_id", "expected"),
    [
        ("c01_invoice_approval", "an invoice arrives by email"),
        ("c05_employee_onboarding", "a new hire signs their contract"),
        ("c13_inventory_replenishment", "Every night at 2am"),
        ("c25_server_patching", "On the first Sunday of every month"),
        ("c29_appointment_reminder", "Two days before a patient's appointment"),
    ],
)
def test_trigger_from_the_corpus(case_id: str, expected: str) -> None:
    assert extract(prompt_for(case_id)).trigger == expected


def test_a_schedule_trigger_keeps_its_leading_phrase() -> None:
    """"2am" without "every night at" is not a trigger anyone can act on."""
    assert extract("Every night at 2am, run the report.").trigger == "Every night at 2am"


def test_when_mid_sentence_is_not_a_trigger() -> None:
    assert extract("Notify the vendor when the invoice is settled.").trigger is None


def test_a_later_sentences_temporal_clause_is_not_the_trigger() -> None:
    """The join inside c05 ("When all three are done, ...") is not what starts
    the process. Reading it as one produces a confident, wrong trigger."""
    spec = extract(
        "The team does three things in parallel. When all three are done, the manager confirms the date."
    )
    assert spec.trigger is None


def test_an_explicit_triggered_by_is_read_anywhere() -> None:
    spec = extract("The process is triggered by a webhook from the CRM. Then update the record.")
    assert spec.trigger == "a webhook from the CRM"


def test_no_trigger_stated_stays_none() -> None:
    """u01 exists to be scored on this: SPEC-NO-TRIGGER at D5 depends on the
    extractor not inventing one."""
    assert extract(prompt_for("u01_refunds_no_trigger")).trigger is None


# ---------- numeric branch conditions ----------


@pytest.mark.parametrize(
    ("text", "expression"),
    [
        ("If the amount is over 10000 route it to a manager.", "amount > 10000"),
        ("Claims under 100 are reimbursed straight away.", "claims < 100"),
        ("Orders above $500 need a check.", "orders > 500"),
        ("If the score is at least 60, qualify the lead.", "score >= 60"),
        ("Escalate when the queue exceeds 25 tickets.", "queue > 25"),
        ("Reject anything where the discount is no more than 5.", "discount <= 5"),
    ],
)
def test_numeric_conditions(text: str, expression: str) -> None:
    assert [b.expression_hint for b in extract(text).branches] == [expression]


def test_thousands_separators_survive() -> None:
    spec = extract("If the amount is over 10,000 escalate it.")
    assert spec.branches[0].expression_hint == "amount > 10000"


def test_a_subject_that_names_nothing_is_dropped() -> None:
    """"anything scoring above 0.8" parses as a threshold and names no
    variable. `anything > 0.8` would reach P3 as a seedable input and D8 as a
    boundary case, both nonsense."""
    assert extract("Anything scoring above 0.8 goes to investigations.").branches == []
    assert extract("A claim has never more than 20 documents.").branches == []


def test_a_budget_is_not_a_branch() -> None:
    """"Keep it under 50 cents per invoice" is a budget; read as a condition it
    becomes a branch on a variable called `it`."""
    spec = extract("Pay the invoice. Keep it under 50 cents per invoice.")
    assert spec.budget_per_instance == 0.50
    assert spec.branches == []


def test_probability_attaches_only_when_unambiguous() -> None:
    one = extract("Route amounts over 10000 to approval. Roughly 10% of invoices need approval.")
    assert one.branches[0].probability_hint == 0.1

    two = extract(
        "Route amounts over 10000 to approval. Orders over 500 need a check. "
        "Roughly 10% of invoices need approval."
    )
    assert [b.probability_hint for b in two.branches] == [None, None], (
        "with two branches the percentage could belong to either; a guess puts a wrong "
        "number into P4's cost model"
    )


# ---------- budget ----------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Keep it under 50 cents per invoice.", 0.50),
        ("Keep it under $0.50 per invoice.", 0.50),
        ("The whole run has to cost us no more than 20 dollars.", 20.0),
        ("Budget of $2 per instance.", 2.0),
        ("Each run should cost under $1.25 each.", 1.25),
    ],
)
def test_budget(text: str, expected: float) -> None:
    assert extract(text).budget_per_instance == expected


def test_a_bare_amount_is_not_a_budget() -> None:
    assert extract("Claims under 500 are auto-approved.").budget_per_instance is None


# ---------- error behaviour, integrations, inputs ----------


def test_error_behaviour_is_the_sentence_that_names_the_failure() -> None:
    spec = extract(prompt_for("c01_invoice_approval"))
    assert spec.error_behaviour is not None
    assert "park the invoice" in spec.error_behaviour


def test_no_error_behaviour_stated_stays_none() -> None:
    """u03's whole purpose: SPEC-NO-ERROR-BEHAVIOUR at D5 needs this to be None."""
    assert extract(prompt_for("u03_payment_no_error_path")).error_behaviour is None


def test_integrations_come_from_a_curated_vocabulary() -> None:
    spec = extract(prompt_for("c01_invoice_approval"))
    assert spec.integrations == ["email", "payments_api"]


def test_an_unnamed_system_is_not_an_integration() -> None:
    """u05 says "put it in the system". Naming that as an integration would
    hide SPEC-UNSPECIFIED-INTEGRATION, which is the finding the case exists
    for."""
    assert extract(prompt_for("u05_put_it_in_the_system")).integrations == []


def test_inputs_come_from_conditions_and_extraction_lists() -> None:
    spec = extract(SHARED_PROMPT)
    assert [(f.name, f.type) for f in spec.inputs] == [
        ("amount", "decimal"),
        ("vendor", "string"),
        ("line_items", "array"),
    ]


def test_a_collection_input_is_left_unbounded() -> None:
    """bound=None is the finding, not a gap: it is SPEC-UNBOUNDED-INPUT at D5
    and an unbounded term in P4's cost expression. Inventing a bound hides
    both."""
    (line_items,) = [f for f in extract(SHARED_PROMPT).inputs if f.name == "line_items"]
    assert line_items.bound is None


# ---------- residue: what this extractor deliberately does not do ----------


def test_outputs_are_left_to_the_refiner() -> None:
    assert extract(SHARED_PROMPT).outputs == []


def test_an_unknown_verb_produces_no_step_rather_than_a_guessed_one() -> None:
    spec = extract("Frobnicate the widget.")
    assert spec.steps == []


def test_an_empty_prompt_yields_an_empty_spec_not_an_error() -> None:
    spec = extract("")
    assert spec == Spec(source="extracted")


def test_the_refiner_seam_receives_the_draft_and_no_artifact() -> None:
    """The refiner is the LLM pass wired at D4. It takes a prompt and a draft.
    There is no parameter for an artifact and there will not be -- extract()'s
    signature is leg 3 of the anti-circularity guarantee."""
    seen: list[tuple[str, Spec]] = []

    class Recorder:
        name = "recorder"

        def refine(self, prompt: str, draft: Spec) -> Spec:
            seen.append((prompt, draft))
            return draft.model_copy(update={"outputs": [], "source": "merged"})

    refiner: Refiner = Recorder()
    spec = extract(SHARED_PROMPT, refiner=refiner)

    assert spec.source == "merged"
    assert seen[0][0] == SHARED_PROMPT
    assert seen[0][1].trigger == "an invoice arrives by email"


# ---------- the whole corpus ----------


def test_every_corpus_prompt_extracts_without_error() -> None:
    """40 prompts, 13 domains, 10 of them deliberately under-specified. This is
    the cheap regression that catches a rule that only works on the one prompt
    it was written against."""
    manifest = json.loads((CORPUS / "manifest.json").read_text())
    for case in manifest["cases"]:
        spec = extract((CORPUS / case["prompt_path"]).read_text())
        assert isinstance(spec, Spec)
        assert spec.source == "extracted"
        for step in spec.steps:
            assert step.description
            assert step.kind_hint in {"agent", "service", "user", "decision"}
        for branch in spec.branches:
            assert branch.expression_hint is None or len(branch.expression_hint.split()) == 3


def test_extraction_is_deterministic() -> None:
    """Same prompt, same Spec -- byte for byte. The disk cache assumes it, and
    a corpus baseline that moves on its own is not a baseline."""
    for case_id in ("c01_invoice_approval", "c16_insurance_claim", "u10_automate_onboarding"):
        text = prompt_for(case_id)
        assert extract(text).model_dump_json() == extract(text).model_dump_json()
