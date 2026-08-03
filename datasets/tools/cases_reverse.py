"""Reverse-generated corpus cases 1-30.

Procedure (the charter's bootstrap trick): the reference artifact was authored
first from a common process template, then described in natural language, and
that description became the prompt. So the reference genuinely is what the
prompt was written from.

Known bias, stated up front because it matters for how these are read: a prompt
written *from* a diagram names every step, every actor and every threshold. Real
users do not. That is what `cases_underspecified.py` exists to counterbalance --
use both halves or the corpus will flatter the generator.
"""
from __future__ import annotations

from .bpmn import branch, end, goto, par, start, task, xor
from .case import Case

REVERSE: list[Case] = [
    Case(
        id="c01_invoice_approval",
        title="Invoice approval with amount threshold and payment failure handling",
        domain="finance",
        provenance="reverse_generated",
        patterns=("message_start", "numeric_threshold", "human_task", "boundary_error"),
        prompt=(
            "When an invoice arrives by email, extract the vendor, the amount and the line "
            "items. If the amount is over 10000 send it to a manager for approval; otherwise "
            "pay it automatically. If the payment API fails, park the invoice for the finance "
            "team to review rather than retrying. Either way, notify the vendor once the "
            "invoice is settled. Keep it under 50 cents per invoice.\n"
        ),
        process_id="Process_invoice_approval",
        nodes=[
            start("StartEvent_invoice", "Invoice received by email", message=True),
            task("Task_extract", "Extract vendor, amount and line items"),
            xor("Gateway_amount", "Amount over 10000?", [
                branch("over", [task("Task_approval", "Manager approval", "user")],
                       condition="amount > 10000"),
                branch("under", [task("Task_autopay", "Auto-pay invoice", boundary_error={
                    "id": "Boundary_payment_failed", "name": "Payment API failed",
                    "nodes": [task("Task_park", "Park for finance review", "user"),
                              end("EndEvent_parked", "Parked for review")],
                })], default=True),
            ]),
            task("Task_notify", "Notify vendor of settlement", "send"),
            end("EndEvent_settled", "Invoice settled"),
        ],
        expected_diagnostics=(),
        notes=(
            "The negative control: trigger, threshold, failure path and budget are all "
            "stated, so /v1/spec should raise nothing at all. A sufficiency checker is "
            "only worth having if it stays quiet on a prompt that leaves nothing out."
        ),
    ),
    Case(
        id="c02_expense_reimbursement",
        title="Expense reimbursement with three approval tiers",
        domain="finance",
        provenance="reverse_generated",
        patterns=("three_way_branch", "numeric_threshold", "human_task"),
        prompt=(
            "An employee submits an expense claim. Validate the receipts first. Claims under "
            "100 are reimbursed straight away with no approval. Claims from 100 up to 1000 go "
            "to the employee's line manager. Anything above 1000 goes to the finance director. "
            "Once approved, raise the payment and email the employee a confirmation. Reject "
            "the claim outright if the receipts do not validate.\n"
        ),
        process_id="Process_expense_reimbursement",
        nodes=[
            start("StartEvent_claim", "Expense claim submitted"),
            task("Task_validate", "Validate receipts"),
            xor("Gateway_valid", "Receipts valid?", [
                branch("invalid", [task("Task_reject", "Notify employee of rejection", "send"),
                                   end("EndEvent_rejected", "Claim rejected")],
                       condition="receipts_valid == false"),
                branch("valid", [], default=True),
            ]),
            xor("Gateway_tier", "Claim amount tier?", [
                branch("under 100", [], condition="amount < 100"),
                branch("100 to 1000", [task("Task_manager", "Line manager approval", "user")],
                       condition="amount >= 100 and amount <= 1000"),
                branch("over 1000", [task("Task_director", "Finance director approval", "user")],
                       default=True),
            ]),
            task("Task_pay", "Raise reimbursement payment"),
            task("Task_confirm", "Email confirmation to employee", "send"),
            end("EndEvent_reimbursed", "Employee reimbursed"),
        ],
        expected_diagnostics=("SPEC-NO-ERROR-BEHAVIOUR", "SPEC-NO-BUDGET"),
        notes="Two sequential gateways; the tier gateway has a genuine three-way split.",
    ),
    Case(
        id="c03_purchase_order_approval",
        title="Purchase order approval, nested on value and vendor risk",
        domain="procurement",
        provenance="reverse_generated",
        patterns=("multi_gateway", "numeric_threshold", "categorical_branch", "human_task"),
        prompt=(
            "When a purchase order is raised, look up the vendor's risk rating. Orders of "
            "50000 or more always need a procurement review, and if the vendor is also rated "
            "high risk they need a compliance sign-off on top of that. Orders under 50000 from "
            "low risk vendors are approved automatically. Send the approved order to the "
            "vendor and record it in the ledger.\n"
        ),
        process_id="Process_purchase_order",
        nodes=[
            start("StartEvent_po", "Purchase order raised"),
            task("Task_risk_lookup", "Look up vendor risk rating"),
            xor("Gateway_value", "Order value 50000 or more?", [
                branch("50000 or more", [
                    task("Task_procurement_review", "Procurement review", "user"),
                    xor("Gateway_risk", "Vendor high risk?", [
                        branch("high risk", [task("Task_compliance", "Compliance sign-off", "user")],
                               condition="vendor_risk == 'high'"),
                        branch("not high risk", [], default=True),
                    ]),
                ], condition="order_value >= 50000"),
                branch("under 50000", [task("Task_autoapprove", "Auto-approve order")], default=True),
            ]),
            task("Task_send_po", "Send order to vendor", "send"),
            task("Task_ledger", "Record order in ledger"),
            end("EndEvent_po_placed", "Order placed"),
        ],
        expected_diagnostics=("SPEC-NO-ERROR-BEHAVIOUR", "SPEC-NO-BUDGET"),
    ),
    Case(
        id="c04_vendor_onboarding",
        title="Vendor onboarding with parallel credit and compliance checks",
        domain="procurement",
        provenance="reverse_generated",
        patterns=("parallel_split", "human_task", "categorical_branch"),
        prompt=(
            "A new vendor submits their onboarding form. Run a credit check and a sanctions "
            "screening at the same time, since neither depends on the other and we do not want "
            "to wait twice. When both come back, a procurement officer reviews the combined "
            "result and either approves the vendor, in which case create them in the ERP and "
            "email them their supplier code, or rejects them with a reason.\n"
        ),
        process_id="Process_vendor_onboarding",
        nodes=[
            start("StartEvent_vendor_form", "Vendor form submitted"),
            par("Gateway_checks", "Run checks in parallel", [
                branch("credit", [task("Task_credit_check", "Credit check")]),
                branch("sanctions", [task("Task_sanctions", "Sanctions screening")]),
            ]),
            task("Task_officer_review", "Procurement officer review", "user"),
            xor("Gateway_decision", "Vendor approved?", [
                branch("approved", [
                    task("Task_create_erp", "Create vendor in ERP"),
                    task("Task_send_code", "Email supplier code to vendor", "send"),
                    end("EndEvent_onboarded", "Vendor onboarded"),
                ], condition="decision == 'approved'"),
                branch("rejected", [
                    task("Task_reject_notice", "Email rejection with reason", "send"),
                    end("EndEvent_vendor_rejected", "Vendor rejected"),
                ], default=True),
            ]),
        ],
        expected_diagnostics=("SPEC-NO-ERROR-BEHAVIOUR", "SPEC-NO-BUDGET"),
        notes="Both gateway branches terminate; there is no join after Gateway_decision.",
    ),
    Case(
        id="c05_employee_onboarding",
        title="Employee onboarding fan-out across IT, payroll and facilities",
        domain="hr",
        provenance="reverse_generated",
        patterns=("parallel_split", "human_task", "send_task"),
        prompt=(
            "Once a new hire signs their contract, three things need to happen in parallel: IT "
            "creates their accounts and orders a laptop, payroll registers them and sets up the "
            "salary record, and facilities issues a building badge. When all three are done, the "
            "hiring manager confirms the start date and the new hire gets a welcome email with "
            "their first-day details.\n"
        ),
        process_id="Process_employee_onboarding",
        nodes=[
            start("StartEvent_contract_signed", "Contract signed"),
            par("Gateway_provision", "Provision in parallel", [
                branch("it", [task("Task_create_accounts", "Create IT accounts"),
                              task("Task_order_laptop", "Order laptop")]),
                branch("payroll", [task("Task_payroll", "Register in payroll")]),
                branch("facilities", [task("Task_badge", "Issue building badge")]),
            ]),
            task("Task_confirm_start", "Hiring manager confirms start date", "user"),
            task("Task_welcome", "Send welcome email", "send"),
            end("EndEvent_onboarded", "New hire onboarded"),
        ],
        expected_diagnostics=("SPEC-NO-ERROR-BEHAVIOUR", "SPEC-NO-BUDGET"),
    ),
    Case(
        id="c06_employee_offboarding",
        title="Employee offboarding with a delayed account deletion",
        domain="hr",
        provenance="reverse_generated",
        patterns=("parallel_split", "timer_start", "categorical_branch"),
        prompt=(
            "Offboarding runs on the employee's last working day. Revoke their system access "
            "and collect their equipment at the same time. If they are leaving voluntarily, "
            "schedule an exit interview; if it is an involuntary exit, skip that and notify "
            "legal instead. Finally archive their mailbox and close the record.\n"
        ),
        process_id="Process_employee_offboarding",
        nodes=[
            start("StartEvent_last_day", "Last working day reached", timer="P0D"),
            par("Gateway_revoke", "Revoke and collect in parallel", [
                branch("access", [task("Task_revoke_access", "Revoke system access")]),
                branch("equipment", [task("Task_collect_kit", "Collect equipment", "manual")]),
            ]),
            xor("Gateway_leaver_type", "Voluntary leaver?", [
                branch("voluntary", [task("Task_exit_interview", "Schedule exit interview", "user")],
                       condition="leaver_type == 'voluntary'"),
                branch("involuntary", [task("Task_notify_legal", "Notify legal", "send")], default=True),
            ]),
            task("Task_archive_mailbox", "Archive mailbox"),
            end("EndEvent_offboarded", "Employee offboarded"),
        ],
        expected_diagnostics=("SPEC-NO-ERROR-BEHAVIOUR", "SPEC-NO-BUDGET"),
    ),
    Case(
        id="c07_leave_request",
        title="Leave request approved on duration",
        domain="hr",
        provenance="reverse_generated",
        patterns=("numeric_threshold", "human_task", "multi_gateway"),
        prompt=(
            "An employee requests leave. Check their remaining balance first — if they do not "
            "have enough days, decline immediately and tell them how many they have left. "
            "Requests of 5 days or fewer are approved by their line manager. Longer requests "
            "need the department head as well. On approval, deduct the days from the balance "
            "and put the leave in the team calendar.\n"
        ),
        process_id="Process_leave_request",
        nodes=[
            start("StartEvent_leave_request", "Leave requested"),
            task("Task_check_balance", "Check leave balance"),
            xor("Gateway_balance", "Enough balance?", [
                branch("insufficient", [
                    task("Task_decline", "Decline and report remaining balance", "send"),
                    end("EndEvent_declined", "Request declined"),
                ], condition="days_requested > balance_remaining"),
                branch("sufficient", [], default=True),
            ]),
            task("Task_manager_approval", "Line manager approval", "user"),
            xor("Gateway_duration", "More than 5 days?", [
                branch("more than 5", [task("Task_head_approval", "Department head approval", "user")],
                       condition="days_requested > 5"),
                branch("5 or fewer", [], default=True),
            ]),
            task("Task_deduct", "Deduct days from balance"),
            task("Task_calendar", "Add leave to team calendar"),
            end("EndEvent_leave_booked", "Leave booked"),
        ],
        expected_diagnostics=("SPEC-NO-ERROR-BEHAVIOUR", "SPEC-NO-BUDGET"),
    ),
    Case(
        id="c08_candidate_screening",
        title="Candidate CV screening with a scored shortlist",
        domain="hr",
        provenance="reverse_generated",
        patterns=("numeric_threshold", "human_task", "categorical_branch"),
        prompt=(
            "When a candidate applies, parse their CV and score it against the job "
            "requirements out of 100. Anything scoring below 40 is rejected automatically with "
            "a polite email. Scores of 70 and above go straight to the hiring manager to book "
            "a first interview. Everything in between goes to a recruiter for a manual read, "
            "and the recruiter decides whether to shortlist or reject.\n"
        ),
        process_id="Process_candidate_screening",
        nodes=[
            start("StartEvent_application", "Application received"),
            task("Task_parse_cv", "Parse CV"),
            task("Task_score", "Score CV against requirements"),
            xor("Gateway_score", "Screening score?", [
                branch("below 40", [
                    task("Task_auto_reject", "Send rejection email", "send"),
                    end("EndEvent_rejected", "Candidate rejected"),
                ], condition="score < 40"),
                branch("40 to 69", [
                    task("Task_recruiter_review", "Recruiter manual review", "user"),
                    xor("Gateway_recruiter", "Shortlist?", [
                        branch("shortlist", [], condition="recruiter_decision == 'shortlist'"),
                        branch("reject", [
                            task("Task_recruiter_reject", "Send rejection email", "send"),
                            end("EndEvent_rejected_manual", "Candidate rejected after review"),
                        ], default=True),
                    ]),
                ], condition="score < 70"),
                branch("70 or above", [], default=True),
            ]),
            task("Task_book_interview", "Hiring manager books first interview", "user"),
            end("EndEvent_interview_booked", "Interview booked"),
        ],
        expected_diagnostics=("SPEC-NO-ERROR-BEHAVIOUR", "SPEC-NO-BUDGET"),
        notes="Two numeric thresholds (40, 70) on one variable — six boundary cases at D8.",
    ),
    Case(
        id="c09_support_ticket_triage",
        title="Support ticket triage by severity with escalation",
        domain="support",
        provenance="reverse_generated",
        patterns=("three_way_branch", "categorical_branch", "parallel_split", "send_task"),
        prompt=(
            "Incoming support tickets are classified by severity. P1 tickets page the on-call "
            "engineer and open an incident channel at the same time. P2 tickets are assigned to "
            "the duty queue. P3 and below are acknowledged with an email and left in the "
            "backlog. Every ticket gets a tracking record written before it is routed.\n"
        ),
        process_id="Process_ticket_triage",
        nodes=[
            start("StartEvent_ticket", "Ticket received"),
            task("Task_classify", "Classify severity"),
            task("Task_track", "Write tracking record"),
            xor("Gateway_severity", "Severity?", [
                branch("P1", [
                    par("Gateway_p1", "Page and open channel", [
                        branch("page", [task("Task_page_oncall", "Page on-call engineer", "send")]),
                        branch("channel", [task("Task_open_channel", "Open incident channel")]),
                    ]),
                ], condition="severity == 'P1'"),
                branch("P2", [task("Task_assign_duty", "Assign to duty queue")],
                       condition="severity == 'P2'"),
                branch("P3 or lower", [task("Task_ack", "Send acknowledgement email", "send")],
                       default=True),
            ]),
            end("EndEvent_routed", "Ticket routed"),
        ],
        expected_diagnostics=("SPEC-NO-ERROR-BEHAVIOUR", "SPEC-UNSTATED-SLA", "SPEC-NO-BUDGET"),
    ),
    Case(
        id="c10_refund_request",
        title="Customer refund with a payment failure path",
        domain="support",
        provenance="reverse_generated",
        patterns=("numeric_threshold", "boundary_error", "human_task"),
        prompt=(
            "A customer requests a refund. Pull the original order and check the refund is "
            "within the 30 day window — if it is not, decline it and explain why. Refunds of "
            "250 or less are processed automatically. Above that a support lead has to approve "
            "it first. If the payment provider rejects the refund, raise a ticket for the "
            "finance team instead of failing silently. Confirm the outcome to the customer.\n"
        ),
        process_id="Process_refund_request",
        nodes=[
            start("StartEvent_refund_request", "Refund requested"),
            task("Task_load_order", "Load original order"),
            xor("Gateway_window", "Within 30 day window?", [
                branch("outside window", [
                    task("Task_decline_refund", "Decline and explain", "send"),
                    end("EndEvent_declined", "Refund declined"),
                ], condition="days_since_order > 30"),
                branch("within window", [], default=True),
            ]),
            xor("Gateway_refund_amount", "Refund over 250?", [
                branch("over 250", [task("Task_lead_approval", "Support lead approval", "user")],
                       condition="refund_amount > 250"),
                branch("250 or less", [], default=True),
            ]),
            task("Task_process_refund", "Process refund with provider", boundary_error={
                "id": "Boundary_refund_rejected", "name": "Provider rejected refund",
                "nodes": [task("Task_finance_ticket", "Raise finance ticket"),
                          end("EndEvent_finance_ticket", "Escalated to finance")],
            }),
            task("Task_confirm_refund", "Confirm outcome to customer", "send"),
            end("EndEvent_refunded", "Refund complete"),
        ],
        expected_diagnostics=("SPEC-NO-BUDGET",),
    ),
    Case(
        id="c11_order_fulfilment",
        title="Order fulfilment iterating over line items",
        domain="logistics",
        provenance="reverse_generated",
        patterns=("multi_instance_loop", "parallel_split", "numeric_threshold"),
        prompt=(
            "When an order is placed, reserve stock for each line item in turn — an order can "
            "have up to 100 lines. Once everything is reserved, print the picking list and book "
            "the courier at the same time. Orders over 500 ship insured, everything else ships "
            "standard. Send the customer a dispatch confirmation with the tracking number.\n"
        ),
        process_id="Process_order_fulfilment",
        nodes=[
            start("StartEvent_order", "Order placed"),
            task("Task_reserve_stock", "Reserve stock for line item", loop_over="line_items"),
            par("Gateway_prepare", "Prepare dispatch", [
                branch("pick", [task("Task_picking_list", "Print picking list")]),
                branch("courier", [task("Task_book_courier", "Book courier")]),
            ]),
            xor("Gateway_value", "Order over 500?", [
                branch("over 500", [task("Task_insure", "Add shipping insurance")],
                       condition="order_value > 500"),
                branch("500 or less", [], default=True),
            ]),
            task("Task_dispatch_confirm", "Send dispatch confirmation", "send"),
            end("EndEvent_dispatched", "Order dispatched"),
        ],
        expected_diagnostics=("SPEC-NO-ERROR-BEHAVIOUR", "SPEC-NO-BUDGET"),
        notes="Explicit collection bound (100 lines) — feeds Cost free variables and the D8 loop cases.",
    ),
    Case(
        id="c12_shipment_exception",
        title="Shipment exception with bounded retry",
        domain="logistics",
        provenance="reverse_generated",
        patterns=("loop_back", "numeric_threshold", "human_task"),
        prompt=(
            "When a carrier reports a delivery exception, try to re-book the delivery "
            "automatically. Give it up to three attempts — after each failed attempt wait and "
            "try again. If it still has not worked after the third attempt, hand it to a "
            "logistics coordinator to sort out manually. Update the customer either way.\n"
        ),
        process_id="Process_shipment_exception",
        nodes=[
            start("StartEvent_exception", "Carrier reports exception", message=True),
            task("Task_rebook", "Attempt automatic re-booking"),
            xor("Gateway_rebooked", "Re-booking succeeded?", [
                branch("succeeded", [], condition="rebooked == true"),
                branch("failed", [
                    xor("Gateway_attempts", "Attempts remaining?", [
                        branch("retry", [task("Task_wait", "Wait before retry"),
                                         goto("Task_rebook", name="retry")],
                               condition="attempts < 3"),
                        branch("give up", [task("Task_coordinator", "Logistics coordinator resolves", "user")],
                               default=True),
                    ]),
                ], default=True),
            ]),
            task("Task_update_customer", "Update customer", "send"),
            end("EndEvent_resolved", "Exception resolved"),
        ],
        expected_diagnostics=("SPEC-NO-BUDGET",),
        notes="The retry loop is the interesting structure: a bounded loop-back to Task_rebook.",
    ),
    Case(
        id="c13_inventory_replenishment",
        title="Nightly inventory replenishment on a reorder point",
        domain="logistics",
        provenance="reverse_generated",
        patterns=("timer_start", "multi_instance_loop", "numeric_threshold"),
        prompt=(
            "Every night at 2am, go through the catalogue — around 2000 SKUs — and check each "
            "one's stock level against its reorder point. Where stock has fallen below the "
            "reorder point, raise a replenishment order with the preferred supplier. At the end "
            "send the warehouse manager a summary of everything that was ordered. The whole "
            "run has to cost us no more than 20 dollars.\n"
        ),
        process_id="Process_inventory_replenishment",
        nodes=[
            start("StartEvent_nightly", "Nightly at 2am", timer="0 0 2 * * ?"),
            task("Task_load_catalogue", "Load catalogue"),
            task("Task_check_sku", "Check SKU against reorder point", loop_over="skus"),
            xor("Gateway_below", "Any SKU below reorder point?", [
                branch("below", [task("Task_raise_replenishment", "Raise replenishment order",
                                      loop_over="skus_below_reorder_point")],
                       condition="skus_below_reorder_point | length > 0"),
                branch("none", [], default=True),
            ]),
            task("Task_summary", "Email summary to warehouse manager", "send"),
            end("EndEvent_replenished", "Replenishment run complete"),
        ],
        expected_diagnostics=("SPEC-NO-ERROR-BEHAVIOUR",),
        notes="2000 SKUs is a stated volume bound — a per-instance cost ceiling here is a real gate.",
    ),
    Case(
        id="c14_customer_kyc",
        title="Customer KYC with risk-based manual review",
        domain="finance",
        provenance="reverse_generated",
        patterns=("three_way_branch", "categorical_branch", "human_task", "terminate_end"),
        prompt=(
            "A new customer signs up. Verify their identity document, then screen them against "
            "the PEP and sanctions lists and produce a risk band. Low risk customers are "
            "approved and their account is opened immediately. Medium risk goes to a compliance "
            "analyst for review. High risk is refused outright and the case is reported to the "
            "MLRO — nothing else should run after that.\n"
        ),
        process_id="Process_customer_kyc",
        nodes=[
            start("StartEvent_signup", "Customer signs up"),
            task("Task_verify_id", "Verify identity document"),
            task("Task_screen", "Screen against PEP and sanctions lists"),
            xor("Gateway_risk_band", "Risk band?", [
                branch("high", [
                    task("Task_report_mlro", "Report case to MLRO", "send"),
                    end("EndEvent_refused", "Customer refused", terminate=True),
                ], condition="risk_band == 'high'"),
                branch("medium", [task("Task_analyst_review", "Compliance analyst review", "user")],
                       condition="risk_band == 'medium'"),
                branch("low", [], default=True),
            ]),
            task("Task_open_account", "Open account"),
            end("EndEvent_kyc_done", "Customer onboarded"),
        ],
        expected_diagnostics=("SPEC-NO-ERROR-BEHAVIOUR", "SPEC-NO-BUDGET"),
    ),
    Case(
        id="c15_loan_application",
        title="Loan application scored by a decision table",
        domain="finance",
        provenance="reverse_generated",
        patterns=("business_rule_task", "numeric_threshold", "human_task", "boundary_error"),
        prompt=(
            "When someone applies for a loan, pull their credit file and run the affordability "
            "rules — those are a fixed table, not a judgement call. If the credit bureau is "
            "unreachable, park the application and tell the applicant we will come back to "
            "them. Applications for 25000 or less that pass the rules are approved "
            "automatically; anything larger goes to an underwriter. Send the decision letter "
            "either way.\n"
        ),
        process_id="Process_loan_application",
        nodes=[
            start("StartEvent_loan_application", "Loan application submitted"),
            task("Task_credit_file", "Pull credit file", boundary_error={
                "id": "Boundary_bureau_down", "name": "Credit bureau unreachable",
                "nodes": [task("Task_park_application", "Park application"),
                          task("Task_holding_notice", "Send holding notice to applicant", "send"),
                          end("EndEvent_parked", "Application parked")],
            }),
            task("Task_affordability", "Run affordability rules", "rule"),
            xor("Gateway_passed", "Rules passed?", [
                branch("failed", [
                    task("Task_decline_letter", "Send decline letter", "send"),
                    end("EndEvent_declined", "Application declined"),
                ], condition="affordability_passed == false"),
                branch("passed", [], default=True),
            ]),
            xor("Gateway_loan_amount", "Loan over 25000?", [
                branch("over 25000", [task("Task_underwriter", "Underwriter review", "user")],
                       condition="loan_amount > 25000"),
                branch("25000 or less", [], default=True),
            ]),
            task("Task_decision_letter", "Send decision letter", "send"),
            end("EndEvent_decided", "Application decided"),
        ],
        expected_diagnostics=("SPEC-NO-BUDGET",),
        notes=(
            "'a fixed table, not a judgement call' is the deterministic hint - a DMN task, "
            "not an agent. This is the one case in the corpus base SpiffWorkflow cannot "
            "parse: it has no parser for businessRuleTask, so P3's runner reports "
            "EXE-RUNNER-UNSUPPORTED here. That is a runner limitation, not an artifact "
            "defect - businessRuleTask is the correct BPMN element for a decision table, "
            "and swapping it for a serviceTask to please the runner would delete the "
            "deterministic signal this case exists to test."
        ),
    ),
    Case(
        id="c16_insurance_claim",
        title="Insurance claim with document loop and fraud check",
        domain="insurance",
        provenance="reverse_generated",
        patterns=("multi_instance_loop", "numeric_threshold", "human_task", "categorical_branch"),
        prompt=(
            "A policyholder files a claim with supporting documents — never more than 20. "
            "Classify each document as you receive it, then check the policy is in force. If it "
            "lapsed, decline the claim. Run a fraud score on the claim; anything scoring above "
            "0.8 goes to the special investigations unit. Otherwise claims up to 5000 are "
            "settled automatically and larger ones are assessed by a claims handler.\n"
        ),
        process_id="Process_insurance_claim",
        nodes=[
            start("StartEvent_claim_filed", "Claim filed"),
            task("Task_classify_document", "Classify supporting document", loop_over="documents"),
            xor("Gateway_policy", "Policy in force?", [
                branch("lapsed", [
                    task("Task_decline_claim", "Decline claim", "send"),
                    end("EndEvent_claim_declined", "Claim declined"),
                ], condition="policy_in_force == false"),
                branch("in force", [], default=True),
            ]),
            task("Task_fraud_score", "Score claim for fraud"),
            xor("Gateway_fraud", "Fraud score over 0.8?", [
                branch("suspected fraud", [
                    task("Task_siu", "Special investigations unit review", "user"),
                    end("EndEvent_siu", "Referred to SIU"),
                ], condition="fraud_score > 0.8"),
                branch("clear", [], default=True),
            ]),
            xor("Gateway_claim_value", "Claim over 5000?", [
                branch("over 5000", [task("Task_handler_assess", "Claims handler assessment", "user")],
                       condition="claim_amount > 5000"),
                branch("5000 or less", [], default=True),
            ]),
            task("Task_settle", "Settle claim"),
            end("EndEvent_settled", "Claim settled"),
        ],
        expected_diagnostics=("SPEC-NO-ERROR-BEHAVIOUR", "SPEC-NO-BUDGET"),
        notes="Numeric conditions on two scales (0.8 probability, 5000 currency) in one process.",
    ),
    Case(
        id="c17_contract_review",
        title="Contract review with a redline loop back to counsel",
        domain="legal",
        provenance="reverse_generated",
        patterns=("loop_back", "human_task", "categorical_branch"),
        prompt=(
            "When a counterparty returns a contract, extract the changed clauses and have "
            "counsel review them. If counsel raises redlines, send them back to the "
            "counterparty and wait for the next version — that cycle repeats until counsel is "
            "satisfied. Once there are no redlines, route the contract for signature and file "
            "the executed copy.\n"
        ),
        process_id="Process_contract_review",
        nodes=[
            start("StartEvent_contract_returned", "Counterparty returns contract", message=True),
            task("Task_extract_clauses", "Extract changed clauses"),
            task("Task_counsel_review", "Counsel reviews clauses", "user"),
            xor("Gateway_redlines", "Redlines raised?", [
                branch("redlines", [
                    task("Task_send_redlines", "Send redlines to counterparty", "send"),
                    task("Task_await_version", "Await next version", "receive"),
                    goto("Task_extract_clauses", name="next version"),
                ], condition="redlines_raised == true"),
                branch("clean", [], default=True),
            ]),
            task("Task_signature", "Route for signature", "user"),
            task("Task_file", "File executed contract"),
            end("EndEvent_executed", "Contract executed"),
        ],
        expected_diagnostics=("SPEC-NO-ERROR-BEHAVIOUR", "SPEC-NO-TERMINAL-STATE", "SPEC-NO-BUDGET"),
        notes="Unbounded review cycle — the prompt never says when to stop trying.",
    ),
    Case(
        id="c18_nda_generation",
        title="Straight-through NDA generation",
        domain="legal",
        provenance="reverse_generated",
        patterns=("linear", "send_task"),
        prompt=(
            "When a sales rep requests an NDA, take the counterparty details from the request, "
            "generate the document from our standard template, store it in the document "
            "management system and email it to the counterparty for signature. There are no "
            "approvals in this one — the template is fixed and legal has pre-approved it.\n"
        ),
        process_id="Process_nda_generation",
        nodes=[
            start("StartEvent_nda_request", "NDA requested"),
            task("Task_read_details", "Read counterparty details"),
            task("Task_generate_nda", "Generate NDA from template"),
            task("Task_store", "Store in document management system"),
            task("Task_email_nda", "Email NDA for signature", "send"),
            end("EndEvent_nda_sent", "NDA sent"),
        ],
        expected_diagnostics=("SPEC-NO-ERROR-BEHAVIOUR", "SPEC-NO-BUDGET"),
        notes="Deliberately trivial. A corpus of only hard cases hides regressions on easy ones.",
    ),
    Case(
        id="c19_lead_qualification",
        title="Inbound lead qualification on a fit score",
        domain="sales",
        provenance="reverse_generated",
        patterns=("numeric_threshold", "categorical_branch", "send_task"),
        prompt=(
            "An inbound lead fills in the web form. Enrich the record from our data provider, "
            "then score the lead for fit out of 100. Leads scoring 60 or more are assigned to an "
            "account executive and get a meeting invite. Leads below 60 go into the nurture "
            "sequence. If enrichment finds the company is an existing customer, route it to the "
            "account manager instead of treating it as new business.\n"
        ),
        process_id="Process_lead_qualification",
        nodes=[
            start("StartEvent_lead", "Lead submits web form"),
            task("Task_enrich", "Enrich lead from data provider"),
            xor("Gateway_existing", "Existing customer?", [
                branch("existing", [
                    task("Task_route_am", "Route to account manager"),
                    end("EndEvent_routed_am", "Routed to account manager"),
                ], condition="is_existing_customer == true"),
                branch("new business", [], default=True),
            ]),
            task("Task_score_fit", "Score lead for fit"),
            xor("Gateway_fit", "Fit score 60 or more?", [
                branch("60 or more", [
                    task("Task_assign_ae", "Assign to account executive"),
                    task("Task_meeting_invite", "Send meeting invite", "send"),
                ], condition="fit_score >= 60"),
                branch("below 60", [task("Task_nurture", "Add to nurture sequence")], default=True),
            ]),
            end("EndEvent_lead_handled", "Lead handled"),
        ],
        expected_diagnostics=("SPEC-NO-ERROR-BEHAVIOUR", "SPEC-NO-BUDGET"),
    ),
    Case(
        id="c20_quote_approval",
        title="Sales quote approval escalating on discount depth",
        domain="sales",
        provenance="reverse_generated",
        patterns=("three_way_branch", "numeric_threshold", "human_task"),
        prompt=(
            "A rep builds a quote. Work out the discount percentage against list price. "
            "Discounts up to 10 percent need no approval. Between 10 and 25 percent the sales "
            "manager approves. Over 25 percent it goes to the VP of sales. If any approver "
            "rejects it, send it back to the rep with the reason. Approved quotes are sent to "
            "the customer and the CRM opportunity is updated.\n"
        ),
        process_id="Process_quote_approval",
        nodes=[
            start("StartEvent_quote", "Quote built"),
            task("Task_calc_discount", "Calculate discount percentage"),
            xor("Gateway_discount", "Discount band?", [
                branch("10 percent or less", [], condition="discount_pct <= 10"),
                branch("10 to 25 percent", [task("Task_manager_approve", "Sales manager approval", "user")],
                       condition="discount_pct <= 25"),
                branch("over 25 percent", [task("Task_vp_approve", "VP of sales approval", "user")],
                       default=True),
            ]),
            xor("Gateway_approved", "Approved?", [
                branch("rejected", [
                    task("Task_return_to_rep", "Return to rep with reason", "send"),
                    end("EndEvent_quote_rejected", "Quote rejected"),
                ], condition="approved == false"),
                branch("approved", [], default=True),
            ]),
            task("Task_send_quote", "Send quote to customer", "send"),
            task("Task_update_crm", "Update CRM opportunity"),
            end("EndEvent_quote_sent", "Quote sent"),
        ],
        expected_diagnostics=("SPEC-NO-ERROR-BEHAVIOUR", "SPEC-NO-BUDGET"),
    ),
    Case(
        id="c21_subscription_renewal",
        title="Subscription renewal run 30 days before expiry",
        domain="sales",
        provenance="reverse_generated",
        patterns=("timer_start", "categorical_branch", "boundary_error"),
        prompt=(
            "Thirty days before a subscription expires, check the account's usage and churn "
            "risk. High risk accounts go to a customer success manager to call. Everyone else "
            "gets an automatic renewal notice and we take payment on the renewal date. If the "
            "card is declined, retry once the next day and then, if it still fails, hand it to "
            "collections.\n"
        ),
        process_id="Process_subscription_renewal",
        nodes=[
            start("StartEvent_pre_expiry", "30 days before expiry", timer="P30D"),
            task("Task_usage", "Check account usage"),
            task("Task_churn_risk", "Score churn risk"),
            xor("Gateway_churn", "High churn risk?", [
                branch("high risk", [
                    task("Task_csm_call", "Customer success manager calls account", "user"),
                    end("EndEvent_csm_owned", "Owned by customer success"),
                ], condition="churn_risk == 'high'"),
                branch("normal", [], default=True),
            ]),
            task("Task_renewal_notice", "Send renewal notice", "send"),
            task("Task_take_payment", "Take renewal payment", boundary_error={
                "id": "Boundary_card_declined", "name": "Card declined",
                "nodes": [task("Task_retry_next_day", "Retry payment next day"),
                          xor("Gateway_retry", "Retry succeeded?", [
                              branch("succeeded", [end("EndEvent_renewed_on_retry", "Renewed on retry")],
                                     condition="payment_captured == true"),
                              branch("failed", [task("Task_collections", "Hand to collections"),
                                                end("EndEvent_collections", "Sent to collections")],
                                     default=True),
                          ])],
            }),
            end("EndEvent_renewed", "Subscription renewed"),
        ],
        expected_diagnostics=("SPEC-NO-BUDGET",),
    ),
    Case(
        id="c22_it_access_request",
        title="IT access request split by privilege level",
        domain="it",
        provenance="reverse_generated",
        patterns=("categorical_branch", "human_task", "parallel_split"),
        prompt=(
            "An employee requests access to a system. If the role they are asking for is "
            "privileged, both their line manager and the system owner have to approve, and "
            "those approvals can happen in either order. Standard access only needs the line "
            "manager. Once approved, grant the entitlement and log it in the access register "
            "for audit.\n"
        ),
        process_id="Process_access_request",
        nodes=[
            start("StartEvent_access_request", "Access requested"),
            task("Task_lookup_role", "Look up requested role"),
            xor("Gateway_privileged", "Privileged role?", [
                branch("privileged", [
                    par("Gateway_dual_approval", "Dual approval", [
                        branch("manager", [task("Task_mgr_approve_priv", "Line manager approval", "user")]),
                        branch("owner", [task("Task_owner_approve", "System owner approval", "user")]),
                    ]),
                ], condition="role_privileged == true"),
                branch("standard", [task("Task_mgr_approve_std", "Line manager approval", "user")],
                       default=True),
            ]),
            task("Task_grant", "Grant entitlement"),
            task("Task_log_register", "Log in access register"),
            end("EndEvent_access_granted", "Access granted"),
        ],
        expected_diagnostics=("SPEC-NO-ERROR-BEHAVIOUR", "SPEC-NO-BUDGET"),
        notes="'in either order' is the parallel-gateway signal; a sequential chain would be wrong.",
    ),
    Case(
        id="c23_incident_response",
        title="Production incident response with severity fan-out",
        domain="it",
        provenance="reverse_generated",
        patterns=("three_way_branch", "parallel_split", "human_task", "send_task"),
        prompt=(
            "When monitoring raises an alert, enrich it with the affected service and recent "
            "deploys. Sev1 means paging the on-call, notifying the status page and opening a "
            "bridge call — all three at once. Sev2 pages the on-call only. Sev3 creates a "
            "ticket for the next working day. After the incident is closed, the on-call writes "
            "a postmortem.\n"
        ),
        process_id="Process_incident_response",
        nodes=[
            start("StartEvent_alert", "Monitoring alert raised", message=True),
            task("Task_enrich_alert", "Enrich with service and recent deploys"),
            xor("Gateway_sev", "Severity?", [
                branch("Sev1", [
                    par("Gateway_sev1_fanout", "Sev1 fan-out", [
                        branch("page", [task("Task_page", "Page on-call", "send")]),
                        branch("status page", [task("Task_status_page", "Update status page")]),
                        branch("bridge", [task("Task_bridge", "Open bridge call")]),
                    ]),
                ], condition="severity == 'Sev1'"),
                branch("Sev2", [task("Task_page_only", "Page on-call", "send")],
                       condition="severity == 'Sev2'"),
                branch("Sev3", [
                    task("Task_next_day_ticket", "Create next-working-day ticket"),
                    end("EndEvent_ticketed", "Ticket raised"),
                ], default=True),
            ]),
            task("Task_close_incident", "Close incident", "user"),
            task("Task_postmortem", "Write postmortem", "user"),
            end("EndEvent_incident_closed", "Incident closed"),
        ],
        expected_diagnostics=("SPEC-NO-ERROR-BEHAVIOUR", "SPEC-UNSTATED-SLA", "SPEC-NO-BUDGET"),
    ),
    Case(
        id="c24_password_reset",
        title="Self-service password reset with a verification failure path",
        domain="it",
        provenance="reverse_generated",
        patterns=("categorical_branch", "human_task"),
        prompt=(
            "A user asks for a password reset. Send a one-time code to their registered phone "
            "and check what they type back. If the code is wrong, lock the request and tell "
            "them to contact the service desk — do not let them keep guessing. If it is right, "
            "reset the password, force a change at next logon, and email them to confirm.\n"
        ),
        process_id="Process_password_reset",
        nodes=[
            start("StartEvent_reset_request", "Password reset requested"),
            task("Task_send_otp", "Send one-time code to registered phone", "send"),
            task("Task_collect_otp", "Collect code from user", "user"),
            xor("Gateway_otp", "Code correct?", [
                branch("incorrect", [
                    task("Task_lock_request", "Lock reset request"),
                    task("Task_tell_servicedesk", "Tell user to contact service desk", "send"),
                    end("EndEvent_locked", "Request locked"),
                ], condition="otp_valid == false"),
                branch("correct", [], default=True),
            ]),
            task("Task_reset_password", "Reset password"),
            task("Task_force_change", "Force change at next logon"),
            task("Task_confirm_reset", "Email confirmation", "send"),
            end("EndEvent_reset_done", "Password reset"),
        ],
        expected_diagnostics=("SPEC-NO-BUDGET",),
        notes="'do not let them keep guessing' is an explicit no-retry instruction — a loop here is a defect.",
    ),
    Case(
        id="c25_server_patching",
        title="Monthly server patching across a host list",
        domain="it",
        provenance="reverse_generated",
        patterns=("timer_start", "multi_instance_loop", "boundary_error"),
        prompt=(
            "On the first Sunday of every month, take the list of servers due for patching — "
            "typically 200 hosts — and patch them one at a time. Snapshot each host before "
            "patching it. If a patch fails, roll that host back from the snapshot and add it to "
            "an exceptions list rather than stopping the whole run. When the run finishes, send "
            "the platform team a report of what patched and what did not.\n"
        ),
        process_id="Process_server_patching",
        nodes=[
            start("StartEvent_patch_window", "First Sunday of the month", timer="0 0 1 ? * SUN#1"),
            task("Task_load_hosts", "Load servers due for patching"),
            task("Task_snapshot", "Snapshot host", loop_over="hosts"),
            task("Task_patch", "Patch host", loop_over="hosts", boundary_error={
                "id": "Boundary_patch_failed", "name": "Patch failed",
                "nodes": [task("Task_rollback", "Roll back host from snapshot"),
                          task("Task_add_exception", "Add host to exceptions list"),
                          end("EndEvent_host_excepted", "Host added to exceptions")],
            }),
            task("Task_patch_report", "Send patch report to platform team", "send"),
            end("EndEvent_patch_run_done", "Patch run complete"),
        ],
        expected_diagnostics=("SPEC-NO-BUDGET",),
        notes="200 hosts is a stated bound; the error handler is per-host, not per-run.",
    ),
    Case(
        id="c26_data_subject_request",
        title="GDPR data subject access request against a statutory deadline",
        domain="compliance",
        provenance="reverse_generated",
        patterns=("parallel_split", "human_task", "send_task"),
        prompt=(
            "When someone submits a data subject access request we have 30 days to respond. "
            "Verify who they are first. Then search the CRM, the support system and the data "
            "warehouse in parallel — they are independent and doing them one after another "
            "wastes the deadline. Have the privacy officer review the compiled pack for third "
            "party data before it goes out, then send it to the requester and record that we "
            "responded.\n"
        ),
        process_id="Process_dsar",
        nodes=[
            start("StartEvent_dsar", "Data subject request received"),
            task("Task_verify_identity", "Verify requester identity"),
            par("Gateway_search", "Search systems in parallel", [
                branch("crm", [task("Task_search_crm", "Search CRM")]),
                branch("support", [task("Task_search_support", "Search support system")]),
                branch("warehouse", [task("Task_search_dwh", "Search data warehouse")]),
            ]),
            task("Task_compile", "Compile response pack"),
            task("Task_privacy_review", "Privacy officer reviews for third party data", "user"),
            task("Task_send_pack", "Send pack to requester", "send"),
            task("Task_record_response", "Record response for audit"),
            end("EndEvent_dsar_done", "Request answered"),
        ],
        expected_diagnostics=("SPEC-NO-ERROR-BEHAVIOUR", "SPEC-NO-BUDGET"),
        notes="The 30 day deadline is stated but never enforced by the reference — a real gap to detect.",
    ),
    Case(
        id="c27_campaign_approval",
        title="Marketing campaign approval on spend",
        domain="marketing",
        provenance="reverse_generated",
        patterns=("numeric_threshold", "human_task"),
        prompt=(
            "A marketer submits a campaign brief with a proposed spend. Brand always reviews "
            "the creative. Campaigns with a spend of 20000 or more additionally need the CMO to "
            "sign off the budget. Once everything is approved, schedule the campaign and book "
            "the spend against the department budget.\n"
        ),
        process_id="Process_campaign_approval",
        nodes=[
            start("StartEvent_brief", "Campaign brief submitted"),
            task("Task_brand_review", "Brand reviews creative", "user"),
            xor("Gateway_spend", "Spend 20000 or more?", [
                branch("20000 or more", [task("Task_cmo_signoff", "CMO signs off budget", "user")],
                       condition="spend >= 20000"),
                branch("under 20000", [], default=True),
            ]),
            task("Task_schedule_campaign", "Schedule campaign"),
            task("Task_book_spend", "Book spend against department budget"),
            end("EndEvent_campaign_live", "Campaign scheduled"),
        ],
        expected_diagnostics=("SPEC-NO-ERROR-BEHAVIOUR", "SPEC-NO-BUDGET"),
    ),
    Case(
        id="c28_content_publication",
        title="Content publication with an editorial rework loop",
        domain="marketing",
        provenance="reverse_generated",
        patterns=("loop_back", "human_task", "categorical_branch"),
        prompt=(
            "A writer submits a draft. An editor reviews it and either approves it or sends it "
            "back with comments, in which case the writer revises and resubmits and the editor "
            "looks again. Approved drafts get a legal check if the piece mentions a customer by "
            "name; otherwise they go straight to publication. Publish to the site and post the "
            "link to social.\n"
        ),
        process_id="Process_content_publication",
        nodes=[
            start("StartEvent_draft", "Draft submitted"),
            task("Task_editor_review", "Editor reviews draft", "user"),
            xor("Gateway_editor", "Editor approves?", [
                branch("rework", [
                    task("Task_revise", "Writer revises draft", "user"),
                    goto("Task_editor_review", name="resubmit"),
                ], condition="editor_decision == 'rework'"),
                branch("approved", [], default=True),
            ]),
            xor("Gateway_customer_named", "Names a customer?", [
                branch("names a customer", [task("Task_legal_check", "Legal check", "user")],
                       condition="mentions_customer == true"),
                branch("no customer named", [], default=True),
            ]),
            task("Task_publish", "Publish to site"),
            task("Task_social", "Post link to social", "send"),
            end("EndEvent_published", "Content published"),
        ],
        expected_diagnostics=("SPEC-NO-ERROR-BEHAVIOUR", "SPEC-NO-TERMINAL-STATE", "SPEC-NO-BUDGET"),
    ),
    Case(
        id="c29_appointment_reminder",
        title="Patient appointment reminder with a no-response path",
        domain="healthcare",
        provenance="reverse_generated",
        patterns=("timer_start", "categorical_branch", "send_task", "human_task"),
        prompt=(
            "Two days before a patient's appointment, text them a reminder and ask them to "
            "confirm. If they confirm, mark the appointment confirmed and stop there. If they "
            "cancel, release the slot and offer it to the waiting list. If they do not reply at "
            "all by the next morning, a receptionist rings them.\n"
        ),
        process_id="Process_appointment_reminder",
        nodes=[
            start("StartEvent_two_days_before", "Two days before appointment", timer="P2D"),
            task("Task_send_reminder", "Text appointment reminder", "send"),
            task("Task_await_reply", "Await patient reply", "receive"),
            xor("Gateway_reply", "Patient reply?", [
                branch("confirmed", [
                    task("Task_mark_confirmed", "Mark appointment confirmed"),
                    end("EndEvent_confirmed", "Appointment confirmed"),
                ], condition="reply == 'confirm'"),
                branch("cancelled", [
                    task("Task_release_slot", "Release slot"),
                    task("Task_offer_waitlist", "Offer slot to waiting list", "send"),
                    end("EndEvent_cancelled", "Appointment cancelled"),
                ], condition="reply == 'cancel'"),
                branch("no reply", [task("Task_receptionist_call", "Receptionist rings patient", "user")],
                       default=True),
            ]),
            end("EndEvent_reminder_done", "Reminder handled"),
        ],
        expected_diagnostics=("SPEC-NO-ERROR-BEHAVIOUR", "SPEC-NO-BUDGET"),
    ),
    Case(
        id="c30_lab_result_routing",
        title="Lab result routing with critical-value escalation",
        domain="healthcare",
        provenance="reverse_generated",
        patterns=("categorical_branch", "terminate_end", "send_task", "loop_back"),
        prompt=(
            "When a lab result arrives, match it to the patient record. If the result is "
            "flagged critical, page the on-call clinician immediately and keep paging until "
            "someone acknowledges — nothing else happens for that result until then. Normal "
            "results are filed to the record and the patient is notified through the portal. "
            "Every result is written to the audit log whatever happens to it.\n"
        ),
        process_id="Process_lab_result",
        nodes=[
            start("StartEvent_result", "Lab result received", message=True),
            task("Task_match_patient", "Match result to patient record"),
            task("Task_audit_log", "Write result to audit log"),
            xor("Gateway_critical", "Critical value?", [
                branch("critical", [
                    task("Task_page_clinician", "Page on-call clinician", "send"),
                    task("Task_await_ack", "Await clinician acknowledgement", "receive"),
                    xor("Gateway_ack", "Acknowledged?", [
                        branch("not acknowledged", [goto("Task_page_clinician", name="page again")],
                               condition="acknowledged == false"),
                        branch("acknowledged", [], default=True),
                    ]),
                    end("EndEvent_escalated", "Critical result acknowledged", terminate=True),
                ], condition="critical_flag == true"),
                branch("normal", [], default=True),
            ]),
            task("Task_file_result", "File result to record"),
            task("Task_notify_portal", "Notify patient through portal", "send"),
            end("EndEvent_filed", "Result filed"),
        ],
        expected_diagnostics=("SPEC-NO-ERROR-BEHAVIOUR", "SPEC-NO-TERMINAL-STATE", "SPEC-NO-BUDGET"),
        notes="'keep paging until acknowledged' is an unbounded loop the prompt asks for explicitly.",
    ),
]
