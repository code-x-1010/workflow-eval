"""SPEC-* sufficiency rules, one fixture per decline.

The charter names three fixtures for D5 -- missing trigger, undefined error
behaviour, ambiguous condition -- and they are here. Most of this file is the
*other* half: the cases where a rule must stay quiet. That is where a sufficiency
checker actually fails, because a false SPEC-* tells the generation team to fix a
prompt that was fine, and enough of those and the whole prefix gets ignored.

Every "stays quiet" test below is a false positive this module really produced
against `datasets/corpus/` before the rule was narrowed. See
`test_sufficiency_corpus.py` for the measured precision and recall those
narrowings bought.
"""
from __future__ import annotations

from services.intent.src.extract import extract
from services.intent.src.sufficiency import diagnose
from wfeval.core.diagnostics import Severity


def codes(prompt: str) -> set[str]:
    return {d.code for d in diagnose(prompt, extract(prompt))}


def only(prompt: str, code: str) -> object:
    matches = [d for d in diagnose(prompt, extract(prompt)) if d.code == code]
    assert len(matches) == 1, f"expected exactly one {code}, got {[d.code for d in matches]}"
    return matches[0]


# ---------- the three the charter names ----------


def test_missing_trigger() -> None:
    assert "SPEC-NO-TRIGGER" in codes("Process refunds and update the ledger.")


def test_undefined_error_behaviour() -> None:
    assert "SPEC-NO-ERROR-BEHAVIOUR" in codes("Take the payment and email the customer a receipt.")


def test_ambiguous_condition() -> None:
    assert "SPEC-AMBIGUOUS-CONDITION" in codes("Big orders should go to a manager. Small ones can just go through.")


# ---------- every rule has a decline, and the decline is the tested part ----------


def test_a_stated_trigger_in_a_form_the_extractor_misses_is_still_a_trigger() -> None:
    """The correction that took precision from 0.71 to 1.00. `extract._trigger()`
    reads a temporal clause; "A rep builds a quote" is a trigger it does not
    match, and reading its silence as the user's omission accused fourteen
    corpus prompts of an omission they had not made."""
    prompt = "A rep builds a quote. Work out the discount against list price."
    assert extract(prompt).trigger is None, "precondition: the extractor does not find this one"
    assert "SPEC-NO-TRIGGER" not in codes(prompt)


def test_a_schedule_counts_as_a_trigger() -> None:
    assert "SPEC-NO-TRIGGER" not in codes("Every night at 2am, archive last month's orders.")


def test_an_imperative_with_no_actor_is_not_a_trigger() -> None:
    """The other side of the same rule: "Read the spreadsheet and create a record"
    has an article and a verb but no actor, and must still be reported."""
    assert "SPEC-NO-TRIGGER" in codes("Read the spreadsheet and create a record for every row.")


def test_a_business_rejection_is_not_error_behaviour() -> None:
    """The distinction four corpus cases turn on. Rejecting a claim whose receipts
    do not validate is the process working, not a failure path -- so the prompt
    still owes us one."""
    prompt = (
        "An employee submits an expense claim. Validate the receipts first. "
        "Reject the claim outright if the receipts do not validate. Once approved, "
        "raise the payment and email the employee a confirmation."
    )
    assert "SPEC-NO-ERROR-BEHAVIOUR" in codes(prompt)


def test_a_named_system_failure_with_a_remedy_is_error_behaviour() -> None:
    prompt = (
        "When someone applies for a loan, pull their credit file. If the credit bureau is "
        "unreachable, park the application and tell the applicant we will come back to them."
    )
    assert "SPEC-NO-ERROR-BEHAVIOUR" not in codes(prompt)


def test_a_process_with_no_side_effects_is_not_asked_for_a_failure_path() -> None:
    """Reporting a missing failure path for a process that only reads is noise."""
    assert "SPEC-NO-ERROR-BEHAVIOUR" not in codes("Keep checking the status until it's sorted.")


def test_a_stated_threshold_elsewhere_settles_a_fuzzy_word() -> None:
    """"Anything larger" refers back to the number in the previous clause. It is
    prose, not an undefined criterion."""
    prompt = (
        "When someone applies for a loan, applications for 25000 or less that pass the rules "
        "are approved automatically; anything larger goes to an underwriter."
    )
    assert "SPEC-AMBIGUOUS-CONDITION" not in codes(prompt)


def test_a_categorised_flag_is_not_a_fuzzy_condition() -> None:
    """"Flagged urgent" names a field the data already carries. "Urgent tickets"
    names a decision nobody has defined."""
    assert "SPEC-AMBIGUOUS-CONDITION" not in codes("If the ticket is flagged urgent, page the on-call.")
    assert "SPEC-AMBIGUOUS-CONDITION" in codes("Urgent tickets need to be dealt with. The rest can wait.")


def test_named_levels_count_as_defined_categories() -> None:
    assert "SPEC-AMBIGUOUS-CONDITION" not in codes(
        "Incoming tickets are classified by severity. P1 tickets page the on-call engineer."
    )


def test_a_container_fanned_out_per_item_is_unbounded_but_a_per_instance_step_is_not() -> None:
    assert "SPEC-UNBOUNDED-INPUT" in codes("Read the spreadsheet and create a record for every row.")
    assert "SPEC-UNBOUNDED-INPUT" not in codes(
        "Incoming support tickets are classified by severity. Every ticket gets a tracking record."
    )


def test_a_stated_volume_settles_a_collection() -> None:
    assert "SPEC-UNBOUNDED-INPUT" not in codes(
        "On the first Sunday of every month, take the list of servers due for patching "
        "— typically 200 hosts — and patch them one at a time."
    )


def test_an_unbounded_retry_has_no_terminal_state() -> None:
    prompt = "When a lab result arrives, if it is flagged critical keep paging the on-call until someone acknowledges."
    assert "SPEC-NO-TERMINAL-STATE" in codes(prompt)


def test_a_capped_retry_does_have_one() -> None:
    assert "SPEC-NO-TERMINAL-STATE" not in codes(
        "When a lab result arrives, keep paging the on-call until someone acknowledges, up to 5 times, then escalate."
    )


def test_a_prompt_forbidding_a_loop_is_not_a_loop() -> None:
    """"Do not let them keep guessing" is the prompt closing an unbounded retry.
    Reading it as opening one inverts the finding."""
    assert "SPEC-NO-TERMINAL-STATE" not in codes(
        "A user asks for a password reset. If the code is wrong, lock the request "
        "— do not let them keep guessing."
    )


def test_writing_to_an_unnamed_system_is_reported() -> None:
    assert "SPEC-UNSPECIFIED-INTEGRATION" in codes("When a form comes in, put the details in the system.")


def test_a_named_integration_settles_it() -> None:
    assert "SPEC-UNSPECIFIED-INTEGRATION" not in codes(
        "When a form comes in, create the record in Salesforce and post to Slack."
    )


def test_a_system_as_subject_matter_is_not_an_integration() -> None:
    """"Requests access to a system" is what the process is *about*. Nothing calls it."""
    assert "SPEC-UNSPECIFIED-INTEGRATION" not in codes(
        "An employee requests access to a system. Once approved, grant the entitlement."
    )


def test_an_indefinite_actor_is_reported_and_a_named_role_is_not() -> None:
    assert "SPEC-AMBIGUOUS-ACTOR" in codes("Someone needs to sign this off before it goes out.")
    assert "SPEC-AMBIGUOUS-ACTOR" not in codes("The finance manager needs to sign this off before it goes out.")


def test_a_document_management_system_is_not_an_ambiguous_approver() -> None:
    """A real false positive: bare "management" matched inside "the document
    management system", turning a storage integration into an unnamed approver."""
    assert "SPEC-AMBIGUOUS-ACTOR" not in codes(
        "When a sales rep requests an NDA, generate the document and store it in "
        "the document management system."
    )


def test_a_universal_auto_approval_beside_a_subset_control_is_contradictory() -> None:
    assert "SPEC-CONTRADICTORY-REQUIREMENT" in codes(
        "Approve all discounts automatically so deals don't get held up. "
        "Every discount over 10% has to be signed off by the sales manager."
    )


def test_a_threshold_alone_is_not_a_contradiction() -> None:
    assert "SPEC-CONTRADICTORY-REQUIREMENT" not in codes(
        "Every discount over 10% has to be signed off by the sales manager."
    )


def test_a_vague_urgency_is_an_unstated_sla_but_a_definite_instruction_is_not() -> None:
    """"Straight away" says this path has no wait in it, which is checkable.
    "Quickly" is a wish about elapsed time that nobody has quantified."""
    assert "SPEC-UNSTATED-SLA" in codes("Urgent tickets need to be dealt with quickly. The rest can wait.")
    assert "SPEC-UNSTATED-SLA" not in codes(
        "An employee submits an expense claim. Claims under 100 are reimbursed straight away."
    )


def test_a_stated_duration_settles_it() -> None:
    assert "SPEC-UNSTATED-SLA" not in codes("Urgent tickets must be acknowledged within 15 minutes.")


def test_a_stated_budget_settles_no_budget() -> None:
    assert "SPEC-NO-BUDGET" not in codes(
        "When an invoice arrives by email, pay it. Keep it under 50 cents per invoice."
    )


# ---------- shape ----------


def test_nothing_in_this_prefix_is_ever_an_error() -> None:
    """`0008`'s severity rule, and the reason it exists: an under-specified prompt
    is a normal thing for a user to send. `error` blocks a gate, and no `SPEC-*`
    may. Checked over every corpus-shaped prompt this file uses."""
    prompts = [
        "Automate our onboarding process.",
        "Read the spreadsheet and create a record for every row.",
        "Someone needs to sign this off.",
        "Keep checking the status until it's sorted.",
    ]
    for prompt in prompts:
        for diagnostic in diagnose(prompt, extract(prompt)):
            assert diagnostic.severity != Severity.ERROR, diagnostic.code


def test_every_diagnostic_carries_an_actionable_fix() -> None:
    """`Diagnostic.suggested_fix` is documented as an imperative the generator can
    act on. A sufficiency finding without one just tells the user they are wrong."""
    for diagnostic in diagnose("Automate our onboarding process.", extract("Automate our onboarding process.")):
        assert diagnostic.suggested_fix
        assert "e.g." in diagnostic.suggested_fix, f"{diagnostic.code} should show, not just tell"


def test_diagnostics_never_reference_an_element() -> None:
    """A SPEC-* code is a statement about the prompt. It is emitted whether or not
    an artifact exists, so it can never carry an element id or a locator."""
    prompt = "Automate our onboarding process."
    for diagnostic in diagnose(prompt, extract(prompt)):
        assert diagnostic.element_id is None
        assert diagnostic.locator is None
