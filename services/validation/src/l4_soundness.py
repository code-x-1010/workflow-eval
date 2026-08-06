"""L4 soundness: BPMN -> workflow net -> WOFLAN.

Translation from `WorkflowAST` to a Petri net follows the standard
flow-as-place / element-as-transition scheme (Dijkman et al., "Semantics and
Analysis of Business Process Models in BPMN"): every `Flow` becomes a place,
every `Element` becomes one or more transitions depending on its split/join
semantics.

  - A parallel gateway (AND) synchronises: one transition consumes every
    incoming place and produces every outgoing place.
  - An exclusive gateway, or an ordinary element with more than one incoming
    or outgoing flow (an implicit merge/choice many BPMN tools allow without
    an explicit gateway), is modelled as a *choice*: one transition per
    incoming/outgoing place, competing for the same tokens.
  - An inclusive gateway is approximated as AND (all branches fire). This is
    a deliberate, documented over-approximation -- inclusive-join semantics
    ("did every branch that was actually activated deliver a token?") are
    the textbook undecidable-in-general OR-join problem, and guessing wrong
    produces false positives, which is exactly what shipping at `warning`
    (not `error`) exists to absorb. See docs/agents/P1-validation.md.
  - Elements with zero incoming/outgoing flows that aren't a start/end event
    (already flagged by L3 as STR-UNREACHABLE-TASK / dead-end) become a
    spurious token source/sink in the net. Also a documented approximation,
    not a bug: fixing it means duplicating L3's reachability analysis here.

Multiple start/end events converge on synthetic `__start__`/`__end__` places
so the net always has the unique source/sink WOFLAN's WF-net definition
requires, regardless of what L3 found. L4 runs whenever L1 parsed the
artifact, independent of L3's result -- same short-circuit rule as the rest
of the ladder ("don't run a tier against a meaningless AST", not "don't run
a tier unless every earlier tier was clean").

Ships at `warning` severity, never `error` -- see module docstring in
l3_structure.py and docs/agents/P1-validation.md for why.
"""
from __future__ import annotations

from itertools import product
from typing import Any

import pm4py
from pm4py.objects.petri_net.obj import Marking, PetriNet
from pm4py.objects.petri_net.utils import petri_utils

from wfeval.core.ast import ElementKind, WorkflowAST
from wfeval.core.diagnostics import Diagnostic, Severity

_AND_SPLIT_KINDS = (ElementKind.GATEWAY_PARALLEL, ElementKind.GATEWAY_INCLUSIVE)


def check(ast: WorkflowAST) -> list[Diagnostic]:
    net, im, fm, transition_owner = _build_petri_net(ast)
    sound, diagnostics_dict = pm4py.check_soundness(net, im, fm)
    if sound:
        return []

    findings: list[Diagnostic] = []
    dead_tasks = diagnostics_dict.get("dead_tasks") or []
    for t in dead_tasks:
        element_id = transition_owner.get(t)
        el = ast.element(element_id) if element_id else None
        findings.append(Diagnostic(
            code="FLW-DEAD-TRANSITION", severity=Severity.WARNING,
            message=f"'{el.name or el.id if el else element_id}' can never fire in any run of "
            "this process, given its current gateway structure.",
            suggested_fix="Check the gateway split/join pairing around this element -- a common "
            "cause is an AND-join downstream of an XOR-split, which can never receive tokens on "
            "every incoming branch in the same run.",
            element_id=element_id, locator=el.locator if el else None,
        ))

    if not findings:
        messages = diagnostics_dict.get("diagnostic_messages") or []
        findings.append(Diagnostic(
            code="FLW-NOT-SOUND", severity=Severity.WARNING,
            message="The process is not a sound workflow net: " + " ".join(str(m) for m in messages)
            if messages else "The process is not a sound workflow net (WOFLAN analysis failed).",
            suggested_fix="Review gateway split/join pairing for deadlocks (tokens that get stuck "
            "and never reach an end event) or dead activities (steps that can never execute). "
            "This check has known false positives on legitimate patterns -- treat as a prompt to "
            "review, not a confirmed defect.",
        ))
    return findings


def score(diagnostics: list[Diagnostic]) -> float:
    """Heuristic, not calibrated -- see l3_structure.score() for the same caveat.
    Binary-ish on purpose: soundness is closer to pass/fail than a smooth gradient,
    and the false-positive risk means a harsh per-finding penalty would be misleading."""
    return 0.6 if diagnostics else 1.0


def _build_petri_net(ast: WorkflowAST) -> tuple[PetriNet, Marking, Marking, dict[Any, str]]:
    net = PetriNet("workflow")
    p_start = PetriNet.Place("__start__")
    p_end = PetriNet.Place("__end__")
    net.places.add(p_start)
    net.places.add(p_end)

    flow_places: dict[str, PetriNet.Place] = {}
    for flow in ast.flows:
        place = PetriNet.Place(flow.id)
        net.places.add(place)
        flow_places[flow.id] = place

    transition_owner: dict[Any, str] = {}

    for el in ast.elements:
        incoming = [flow_places[f.id] for f in ast.flows if f.target == el.id]
        outgoing = [flow_places[f.id] for f in ast.flows if f.source == el.id]
        if not incoming and el.kind == ElementKind.START_EVENT:
            incoming = [p_start]
        if not outgoing and el.kind == ElementKind.END_EVENT:
            outgoing = [p_end]

        join_alternatives = _alternatives(incoming, and_join=el.kind == ElementKind.GATEWAY_PARALLEL)
        split_alternatives = _alternatives(outgoing, and_join=el.kind in _AND_SPLIT_KINDS)

        for idx, (in_set, out_set) in enumerate(product(join_alternatives, split_alternatives)):
            t = PetriNet.Transition(f"{el.id}#{idx}", el.name or el.id)
            net.transitions.add(t)
            transition_owner[t] = el.id
            for p in in_set:
                petri_utils.add_arc_from_to(p, t, net)
            for p in out_set:
                petri_utils.add_arc_from_to(t, p, net)

    im = Marking()
    im[p_start] = 1
    fm = Marking()
    fm[p_end] = 1
    return net, im, fm, transition_owner


def _alternatives(places: list[PetriNet.Place], *, and_join: bool) -> list[list[PetriNet.Place]]:
    if len(places) <= 1 or and_join:
        return [places]
    return [[p] for p in places]
