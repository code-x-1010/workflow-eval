"""Hand-written under-specified corpus cases 31-40.

These were written prompt-first, in the register real users actually use: short,
elliptical, and missing at least one thing the generator cannot invent. Nothing
here was derived from a diagram.

**The reference artifact for each of these is one reasonable reading, not ground
truth.** An ambiguous prompt has several defensible expansions; a generator that
picks a different one has not necessarily failed. Alignment scores on these
cases are a signal about *which* reading a generator prefers, and the real
deliverable is whether `/v1/spec` raises the right `SPEC-*` diagnostic instead
of quietly inventing the missing detail. `manifest.json` marks them
`reference_is_ground_truth: false` so nobody scores them strictly by accident.
"""
from __future__ import annotations

from .bpmn import branch, end, goto, par, start, task, xor
from .case import Case

UNDERSPECIFIED: list[Case] = [
    Case(
        id="u01_refunds_no_trigger",
        title="Refunds with no stated trigger",
        domain="finance",
        provenance="hand_written",
        patterns=("linear",),
        prompt="Process refunds and update the ledger.\n",
        process_id="Process_refunds",
        nodes=[
            start("StartEvent_refund", "Refund request received"),
            task("Task_process_refund", "Process refund"),
            task("Task_update_ledger", "Update ledger"),
            end("EndEvent_refund_done", "Refund processed"),
        ],
        expected_diagnostics=(
            "SPEC-NO-TRIGGER", "SPEC-NO-ERROR-BEHAVIOUR", "SPEC-NO-BUDGET",
        ),
        notes=(
            "Nothing says what starts this. The reference guesses a request event; a batch "
            "timer is an equally defensible reading, and that is the point."
        ),
    ),
    Case(
        id="u02_big_orders",
        title="Unquantified 'big' orders",
        domain="sales",
        provenance="hand_written",
        patterns=("categorical_branch", "human_task"),
        prompt="Big orders should go to a manager. Small ones can just go through.\n",
        process_id="Process_big_orders",
        nodes=[
            start("StartEvent_order", "Order received"),
            xor("Gateway_size", "Big order?", [
                branch("big", [task("Task_manager_review", "Manager reviews order", "user")],
                       condition="order_is_big == true"),
                branch("small", [], default=True),
            ]),
            task("Task_process_order", "Process order"),
            end("EndEvent_order_done", "Order processed"),
        ],
        expected_diagnostics=(
            "SPEC-AMBIGUOUS-CONDITION", "SPEC-NO-TRIGGER",
            "SPEC-NO-ERROR-BEHAVIOUR", "SPEC-NO-BUDGET",
        ),
        notes=(
            "The canonical ambiguous-condition case. There is no threshold to generate "
            "boundary tests from, so D8 must emit SPEC-AMBIGUOUS-CONDITION rather than "
            "inventing a number — an invented threshold produces boundary cases that test "
            "the generator's guess, not the user's intent."
        ),
    ),
    Case(
        id="u03_payment_no_error_path",
        title="Payment with no failure behaviour stated",
        domain="finance",
        provenance="hand_written",
        patterns=("linear", "send_task"),
        prompt="Take the payment and email the customer a receipt.\n",
        process_id="Process_take_payment",
        nodes=[
            start("StartEvent_checkout", "Checkout completed"),
            task("Task_take_payment", "Take payment"),
            task("Task_email_receipt", "Email receipt", "send"),
            end("EndEvent_paid", "Payment complete"),
        ],
        expected_diagnostics=(
            "SPEC-NO-ERROR-BEHAVIOUR", "SPEC-NO-TRIGGER", "SPEC-NO-BUDGET",
        ),
        notes=(
            "A side-effecting external call with no stated failure path. The reference has no "
            "boundary error event on purpose: adding one would be inventing a requirement. "
            "The right output is the diagnostic."
        ),
    ),
    Case(
        id="u04_spreadsheet_unbounded",
        title="Loop over an unbounded collection",
        domain="operations",
        provenance="hand_written",
        patterns=("multi_instance_loop",),
        prompt="Read the spreadsheet and create a record for every row.\n",
        process_id="Process_spreadsheet_import",
        nodes=[
            start("StartEvent_spreadsheet", "Spreadsheet provided"),
            task("Task_read_sheet", "Read spreadsheet"),
            task("Task_create_record", "Create record for row", loop_over="rows"),
            end("EndEvent_import_done", "Import complete"),
        ],
        expected_diagnostics=(
            "SPEC-UNBOUNDED-INPUT", "SPEC-NO-TRIGGER",
            "SPEC-NO-ERROR-BEHAVIOUR", "SPEC-NO-BUDGET",
        ),
        notes=(
            "No row count, so per-instance cost is unbounded and P4 cannot gate on it. Ten "
            "rows and ten million rows are the same prompt."
        ),
    ),
    Case(
        id="u05_put_it_in_the_system",
        title="Unnamed target system and unnamed recipient",
        domain="operations",
        provenance="hand_written",
        patterns=("linear", "send_task"),
        prompt="When a form comes in, put the details in the system and let the team know.\n",
        process_id="Process_form_intake",
        nodes=[
            start("StartEvent_form", "Form received", message=True),
            task("Task_store_details", "Store details in system of record"),
            task("Task_notify_team", "Notify the team", "send"),
            end("EndEvent_form_handled", "Form handled"),
        ],
        expected_diagnostics=(
            "SPEC-UNSPECIFIED-INTEGRATION", "SPEC-AMBIGUOUS-ACTOR",
            "SPEC-NO-ERROR-BEHAVIOUR", "SPEC-NO-BUDGET",
        ),
        notes=(
            "'the system' and 'the team' are both unresolvable. Two integrations are implied "
            "and neither can be named, so no MockDefinition or TaskStub asset_ref can be "
            "derived — this case is why SPEC-UNSPECIFIED-INTEGRATION blocks D9."
        ),
    ),
    Case(
        id="u06_someone_signs_off",
        title="Approval with no named approver",
        domain="operations",
        provenance="hand_written",
        patterns=("human_task", "linear"),
        prompt="Someone needs to sign this off before it goes out.\n",
        process_id="Process_signoff",
        nodes=[
            start("StartEvent_ready", "Item ready to go out"),
            task("Task_signoff", "Sign off", "user"),
            task("Task_send_out", "Send out", "send"),
            end("EndEvent_sent", "Item sent"),
        ],
        expected_diagnostics=(
            "SPEC-AMBIGUOUS-ACTOR", "SPEC-NO-TRIGGER",
            "SPEC-NO-ERROR-BEHAVIOUR", "SPEC-NO-BUDGET",
        ),
        notes=(
            "No role, so the user task cannot be assigned and there is no rejection path — "
            "'signs off' implies the possibility of not signing off, which the prompt never "
            "addresses."
        ),
    ),
    Case(
        id="u07_until_its_sorted",
        title="Loop with no exit condition",
        domain="operations",
        provenance="hand_written",
        patterns=("loop_back",),
        prompt="Keep checking the status until it's sorted.\n",
        process_id="Process_status_polling",
        nodes=[
            start("StartEvent_polling", "Polling started"),
            task("Task_check_status", "Check status"),
            xor("Gateway_sorted", "Sorted?", [
                branch("not yet", [task("Task_wait_poll", "Wait before checking again"),
                                   goto("Task_check_status", name="check again")],
                       condition="sorted == false"),
                branch("sorted", [], default=True),
            ]),
            end("EndEvent_sorted", "Status sorted"),
        ],
        expected_diagnostics=(
            "SPEC-NO-TERMINAL-STATE", "SPEC-UNBOUNDED-INPUT",
            "SPEC-NO-TRIGGER", "SPEC-NO-BUDGET",
        ),
        notes=(
            "No attempt cap, no timeout, no definition of 'sorted'. The reference loops "
            "forever if the condition never flips — which is the honest rendering of the "
            "prompt, and exactly what the invariant assertions at D8 should catch."
        ),
    ),
    Case(
        id="u08_contradictory_discounts",
        title="Two instructions that cannot both hold",
        domain="sales",
        provenance="hand_written",
        patterns=("numeric_threshold", "human_task"),
        prompt=(
            "Approve all discounts automatically so deals don't get held up. Every discount "
            "over 10% has to be signed off by the sales manager.\n"
        ),
        process_id="Process_discount_approval",
        nodes=[
            start("StartEvent_discount", "Discount requested"),
            xor("Gateway_discount_pct", "Discount over 10%?", [
                branch("over 10 percent", [task("Task_sales_manager", "Sales manager sign-off", "user")],
                       condition="discount_pct > 10"),
                branch("10 percent or less", [task("Task_auto_approve", "Auto-approve discount")],
                       default=True),
            ]),
            task("Task_apply_discount", "Apply discount to deal"),
            end("EndEvent_discount_applied", "Discount applied"),
        ],
        expected_diagnostics=(
            "SPEC-CONTRADICTORY-REQUIREMENT", "SPEC-NO-TRIGGER",
            "SPEC-NO-ERROR-BEHAVIOUR", "SPEC-NO-BUDGET",
        ),
        notes=(
            "'approve all automatically' and 'over 10% needs sign-off' cannot both be "
            "satisfied. The reference resolves it the way a human would — the specific rule "
            "beats the general one — but a generator that silently picks either reading "
            "without flagging the conflict is the failure mode this case exists to catch."
        ),
    ),
    Case(
        id="u09_urgent_tickets",
        title="Urgency with no definition and no deadline",
        domain="support",
        provenance="hand_written",
        patterns=("categorical_branch", "send_task"),
        prompt="Urgent tickets need to be dealt with quickly. The rest can wait.\n",
        process_id="Process_urgent_tickets",
        nodes=[
            start("StartEvent_ticket_in", "Ticket received"),
            xor("Gateway_urgent", "Urgent?", [
                branch("urgent", [task("Task_escalate", "Escalate ticket", "send")],
                       condition="is_urgent == true"),
                branch("not urgent", [task("Task_queue", "Add to standard queue")], default=True),
            ]),
            end("EndEvent_ticket_routed", "Ticket routed"),
        ],
        expected_diagnostics=(
            "SPEC-AMBIGUOUS-CONDITION", "SPEC-UNSTATED-SLA",
            "SPEC-NO-TRIGGER", "SPEC-NO-ERROR-BEHAVIOUR", "SPEC-NO-BUDGET",
        ),
        notes=(
            "Two separate gaps that look like one: what makes a ticket urgent, and how fast "
            "'quickly' is. A generator typically invents both and reports success."
        ),
    ),
    Case(
        id="u10_automate_onboarding",
        title="A whole process named and nothing else",
        domain="hr",
        provenance="hand_written",
        patterns=("parallel_split", "human_task"),
        prompt="Automate our onboarding process.\n",
        process_id="Process_generic_onboarding",
        nodes=[
            start("StartEvent_new_starter", "New starter identified"),
            par("Gateway_setup", "Set up in parallel", [
                branch("accounts", [task("Task_accounts", "Create accounts")]),
                branch("paperwork", [task("Task_paperwork", "Collect paperwork", "user")]),
            ]),
            task("Task_manager_check", "Manager confirms setup complete", "user"),
            end("EndEvent_onboarded", "Starter onboarded"),
        ],
        expected_diagnostics=(
            "SPEC-NO-TRIGGER", "SPEC-AMBIGUOUS-CONDITION", "SPEC-AMBIGUOUS-ACTOR",
            "SPEC-UNSPECIFIED-INTEGRATION", "SPEC-NO-ERROR-BEHAVIOUR", "SPEC-NO-BUDGET",
        ),
        notes=(
            "The floor case. Onboarding *what* — an employee, a customer, a vendor? The "
            "reference guesses employee onboarding and is almost certainly wrong for any "
            "given user. Compare against c05: same words, 40x the specification. If the "
            "generator produces something similar for both, its output is not driven by the "
            "prompt."
        ),
    ),
]
