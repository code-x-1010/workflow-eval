"""A tiny BPMN 2.0 emitter for corpus reference artifacts.

The corpus needs 40 reference artifacts that are structurally varied but
consistently well-formed. Hand-writing 40 XML files guarantees typos and
dangling `sequenceFlow` refs; describing each process as a small node tree and
emitting the XML does not.

The node tree is deliberately close to how a *prompt* reads — a trigger, some
steps, a branch with a condition, an end state — because that is what the
reference artifact is ground truth for. See `datasets/README.md`.

Nothing here imports from `wfeval` or from `services/`. It is authoring
tooling, not runtime code.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from typing import Any

BPMN_NS = "http://www.omg.org/spec/BPMN/20100524/MODEL"
XSI_NS = "http://www.w3.org/2001/XMLSchema-instance"

ET.register_namespace("", BPMN_NS)
ET.register_namespace("xsi", XSI_NS)

TASK_TAGS = {
    "service": "serviceTask",
    "user": "userTask",
    "script": "scriptTask",
    "rule": "businessRuleTask",
    "send": "sendTask",
    "receive": "receiveTask",
    "manual": "manualTask",
}


# ---------------------------------------------------------------- node DSL

def start(id: str, name: str, *, timer: str | None = None, message: bool = False) -> dict[str, Any]:
    return {"n": "start", "id": id, "name": name, "timer": timer, "message": message}


def task(
    id: str,
    name: str,
    kind: str = "service",
    *,
    loop_over: str | None = None,
    boundary_error: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """`loop_over` marks a multi-instance task (the collection it iterates).

    `boundary_error` is `{"id", "name", "nodes"}` — an interrupting error event
    attached to this task whose handler chain must reach its own end event.
    """
    if kind not in TASK_TAGS:
        raise ValueError(f"unknown task kind {kind!r}")
    return {
        "n": "task", "id": id, "name": name, "kind": kind,
        "loop_over": loop_over, "boundary_error": boundary_error,
    }


def branch(
    label: str,
    nodes: list[dict[str, Any]],
    *,
    condition: str | None = None,
    default: bool = False,
) -> dict[str, Any]:
    return {"label": label, "nodes": nodes, "condition": condition, "default": default}


def xor(id: str, name: str, branches: list[dict[str, Any]], *, join: str | None = None) -> dict[str, Any]:
    return {"n": "xor", "id": id, "name": name, "branches": branches, "join": join}


def par(id: str, name: str, branches: list[dict[str, Any]], *, join: str | None = None) -> dict[str, Any]:
    return {"n": "par", "id": id, "name": name, "branches": branches, "join": join}


def end(id: str, name: str, *, terminate: bool = False) -> dict[str, Any]:
    return {"n": "end", "id": id, "name": name, "terminate": terminate}


def goto(target: str, *, name: str | None = None) -> dict[str, Any]:
    """A loop-back edge to an element already emitted. Terminates the chain."""
    return {"n": "goto", "target": target, "name": name}


# ---------------------------------------------------------------- emitter

class _Builder:
    def __init__(self, process_id: str) -> None:
        self.process = ET.Element(f"{{{BPMN_NS}}}process", {"id": process_id, "isExecutable": "true"})
        self._flow_n = 0
        # Flows are collected separately so they can be appended after the
        # flow nodes -- readable diffs, and it matches the shared fixture.
        self.flows: list[ET.Element] = []

    def node(self, tag: str, id: str, name: str | None = None, **attrs: str) -> ET.Element:
        el = ET.SubElement(self.process, f"{{{BPMN_NS}}}{tag}", {"id": id, **attrs})
        if name:
            el.set("name", name)
        return el

    def connect(
        self, src: str, tgt: str, *, name: str | None = None, condition: str | None = None
    ) -> str:
        self._flow_n += 1
        fid = f"Flow_{self._flow_n:02d}"
        el = ET.Element(f"{{{BPMN_NS}}}sequenceFlow", {"id": fid, "sourceRef": src, "targetRef": tgt})
        if name:
            el.set("name", name)
        if condition is not None:
            cond = ET.SubElement(el, f"{{{BPMN_NS}}}conditionExpression")
            cond.set(f"{{{XSI_NS}}}type", "tFormalExpression")
            cond.text = condition
        self.flows.append(el)
        return fid


def _walk(
    b: _Builder, nodes: list[dict[str, Any]], prev: str | None, edge: dict[str, Any] | None = None
) -> tuple[str | None, dict[str, Any] | None]:
    """Emit `nodes` in sequence starting from `prev`.

    Returns `(tail, pending_edge)`. `tail` is the id of the chain's last element,
    or None if the chain terminated (an end event or a loop-back), meaning there
    is nothing left to connect forward. `pending_edge` is an undecorated branch
    label/condition that still has to land on the tail's *next* outgoing flow --
    it travels back up out of the recursion because the flow it belongs on may
    not be emitted until the caller connects the tail onward.

    `edge` decorates only the first connection -- that is how branch labels and
    condition expressions get onto a gateway's outgoing flow.
    """
    def link(tgt: str) -> None:
        nonlocal prev, edge
        if prev is not None:
            e = edge or {}
            fid = b.connect(prev, tgt, name=e.get("name"), condition=e.get("condition"))
            if e.get("default"):
                b.process.find(f".//*[@id='{prev}']").set("default", fid)  # type: ignore[union-attr]
        edge = None

    for spec in nodes:
        kind = spec["n"]

        if kind == "start":
            ev = b.node("startEvent", spec["id"], spec["name"])
            if spec["timer"]:
                d = ET.SubElement(ev, f"{{{BPMN_NS}}}timerEventDefinition")
                ET.SubElement(d, f"{{{BPMN_NS}}}timeCycle").text = spec["timer"]
            elif spec["message"]:
                ET.SubElement(ev, f"{{{BPMN_NS}}}messageEventDefinition")
            prev = spec["id"]

        elif kind == "task":
            el = b.node(TASK_TAGS[spec["kind"]], spec["id"], spec["name"])
            link(spec["id"])
            if spec["loop_over"]:
                mi = ET.SubElement(
                    el, f"{{{BPMN_NS}}}multiInstanceLoopCharacteristics", {"isSequential": "true"}
                )
                ET.SubElement(mi, f"{{{BPMN_NS}}}loopDataInputRef").text = spec["loop_over"]
            if spec["boundary_error"]:
                be = spec["boundary_error"]
                ev = b.node("boundaryEvent", be["id"], be["name"], attachedToRef=spec["id"])
                ET.SubElement(ev, f"{{{BPMN_NS}}}errorEventDefinition")
                if _walk(b, be["nodes"], be["id"])[0] is not None:
                    raise ValueError(f"boundary handler {be['id']} must reach an end event or goto")
            prev = spec["id"]

        elif kind in ("xor", "par"):
            tag = "exclusiveGateway" if kind == "xor" else "parallelGateway"
            b.node(tag, spec["id"], spec["name"])
            link(spec["id"])
            # (tail id, edge to decorate its flow into the join). The edge is only
            # set for a pass-through branch, whose label/condition/default has
            # nowhere else to live -- its single flow *is* the whole branch.
            tails: list[tuple[str, dict[str, Any] | None]] = []
            for br in spec["branches"]:
                if kind == "par" and (br["condition"] or br["default"]):
                    raise ValueError(f"parallel gateway {spec['id']} branch cannot carry a condition")
                e = {"name": br["label"], "condition": br["condition"], "default": br["default"]}
                if not br["nodes"]:
                    tails.append((spec["id"], e))
                    continue
                tail, tail_edge = _walk(b, br["nodes"], spec["id"], e)
                if tail is not None:
                    tails.append((tail, tail_edge))
            if not tails:
                prev = None  # every branch terminated in its own end event
                continue
            if len(tails) == 1 and kind == "xor":
                # Nothing to merge -- every other branch ended on its own. Emitting a
                # join here would leave a 1-in-1-out gateway, and a reference artifact
                # carrying elements the prompt never asked for shows up as noise in
                # every alignment diff computed against it. If the surviving branch is
                # a pass-through, its label/condition/default has not been emitted yet;
                # defer it onto the next connection instead.
                prev, edge = tails[0]
                continue
            join_id = spec["join"] or f"{spec['id']}_join"
            b.node(tag, join_id, None)
            for t, e in tails:
                e = e or {}
                fid = b.connect(t, join_id, name=e.get("name"), condition=e.get("condition"))
                if e.get("default"):
                    b.process.find(f".//*[@id='{t}']").set("default", fid)  # type: ignore[union-attr]
            prev = join_id

        elif kind == "end":
            ev = b.node("endEvent", spec["id"], spec["name"])
            link(spec["id"])
            if spec["terminate"]:
                ET.SubElement(ev, f"{{{BPMN_NS}}}terminateEventDefinition")
            prev = None

        elif kind == "goto":
            if prev is None:
                raise ValueError("goto with nothing to connect from")
            # A goto that opens a branch carries that branch's condition -- the
            # loop-back edge *is* the branch.
            e = edge or {}
            fid = b.connect(
                prev, spec["target"],
                name=spec["name"] or e.get("name"), condition=e.get("condition"),
            )
            if e.get("default"):
                b.process.find(f".//*[@id='{prev}']").set("default", fid)  # type: ignore[union-attr]
            edge = None
            prev = None

        else:
            raise ValueError(f"unknown node kind {kind!r}")

    return prev, edge


def emit(process_id: str, nodes: list[dict[str, Any]], *, header: str | None = None) -> str:
    """Render a node tree as a BPMN 2.0 XML document."""
    b = _Builder(process_id)
    tail, _ = _walk(b, nodes, None)
    if tail is not None:
        raise ValueError(f"{process_id}: process does not reach an end event (tail={tail})")
    for f in b.flows:
        b.process.append(f)

    defs = ET.Element(
        f"{{{BPMN_NS}}}definitions",
        {"id": f"Defs_{process_id.removeprefix('Process_')}",
         "targetNamespace": "http://uipath.com/maestro"},
    )
    defs.append(b.process)
    ET.indent(defs, space="  ")
    xml = ET.tostring(defs, encoding="unicode")
    parts = ['<?xml version="1.0" encoding="UTF-8"?>']
    if header:
        # `--` is illegal inside an XML comment, and the house comment style uses it.
        parts.append("<!-- " + header.replace("--", "-") + " -->")
    parts.append(xml)
    return "\n".join(parts) + "\n"


# ---------------------------------------------------------------- inspection

_TASK_PATTERN = {
    "userTask": "human_task",
    "businessRuleTask": "business_rule_task",
    "sendTask": "send_task",
    "receiveTask": "receive_task",
    "manualTask": "manual_task",
    "scriptTask": "script_task",
}
_NUMERIC_COMPARISON = re.compile(r"[<>]=?\s*-?\d|==\s*-?\d|\|\s*length")
_CATEGORICAL_COMPARISON = re.compile(r"==\s*'|!=\s*'|==\s*(true|false)")


def derive_patterns(xml: str) -> list[str]:
    """Read the structural patterns back out of an emitted artifact.

    Derived rather than hand-tagged: a hand-written tag list drifts the moment a
    case is edited, and a manifest that says a corpus covers a pattern it does
    not cover is worse than one that says nothing.
    """
    root = ET.fromstring(xml)
    proc = root.find(f"{{{BPMN_NS}}}process")
    if proc is None:
        return []
    found: set[str] = set()
    order = {el.get("id", ""): i for i, el in enumerate(proc)}
    flows = [el for el in proc if el.tag.endswith("}sequenceFlow")]
    out_count: dict[str, int] = {}
    splits = 0

    for el in proc:
        tag = el.tag.split("}")[-1]
        if tag in _TASK_PATTERN:
            found.add(_TASK_PATTERN[tag])
        if el.find(f"{{{BPMN_NS}}}multiInstanceLoopCharacteristics") is not None:
            found.add("multi_instance_loop")
        if tag == "startEvent":
            if el.find(f"{{{BPMN_NS}}}messageEventDefinition") is not None:
                found.add("message_start")
            elif el.find(f"{{{BPMN_NS}}}timerEventDefinition") is not None:
                found.add("timer_start")
        if tag == "endEvent" and el.find(f"{{{BPMN_NS}}}terminateEventDefinition") is not None:
            found.add("terminate_end")
        if tag == "boundaryEvent" and el.find(f"{{{BPMN_NS}}}errorEventDefinition") is not None:
            found.add("boundary_error")

    for f in flows:
        src, tgt = f.get("sourceRef", ""), f.get("targetRef", "")
        out_count[src] = out_count.get(src, 0) + 1
        if order.get(tgt, 0) < order.get(src, 0):
            found.add("loop_back")
        cond = f.find(f"{{{BPMN_NS}}}conditionExpression")
        if cond is not None and cond.text:
            if _NUMERIC_COMPARISON.search(cond.text):
                found.add("numeric_threshold")
            if _CATEGORICAL_COMPARISON.search(cond.text):
                found.add("categorical_branch")

    for gw in proc:
        tag = gw.tag.split("}")[-1]
        outs = out_count.get(gw.get("id", ""), 0)
        if tag == "exclusiveGateway" and outs >= 2:
            splits += 1
            found.add("exclusive_gateway")
            if outs >= 3:
                found.add("three_way_branch")
        if tag == "parallelGateway" and outs >= 2:
            found.add("parallel_split")
    if splits >= 2:
        found.add("multi_gateway")
    if not splits and "parallel_split" not in found:
        found.add("linear")
    return sorted(found)


# ---------------------------------------------------------------- validation

def check(xml: str) -> list[str]:
    """Structural checks on an emitted artifact. Returns a list of problems.

    Deliberately stricter than "is it well-formed XML": a reference artifact
    with a dangling flow ref is worse than no reference artifact, because the
    alignment scores computed against it would be quietly wrong.
    """
    problems: list[str] = []
    root = ET.fromstring(xml)
    proc = root.find(f"{{{BPMN_NS}}}process")
    if proc is None:
        return ["no <process> element"]

    ids: list[str] = []
    node_ids: set[str] = set()
    flows: list[ET.Element] = []
    starts = ends = 0
    for el in proc:
        tag = el.tag.split("}")[-1]
        eid = el.get("id", "")
        ids.append(eid)
        if tag == "sequenceFlow":
            flows.append(el)
            continue
        node_ids.add(eid)
        starts += tag == "startEvent"
        ends += tag == "endEvent"

    dupes = {i for i in ids if ids.count(i) > 1}
    if dupes:
        problems.append(f"duplicate ids: {sorted(dupes)}")
    if starts != 1:
        problems.append(f"expected exactly 1 start event, found {starts}")
    if ends == 0:
        problems.append("no end event")

    targeted: set[str] = set()
    for f in flows:
        src, tgt = f.get("sourceRef", ""), f.get("targetRef", "")
        for ref, which in ((src, "sourceRef"), (tgt, "targetRef")):
            if ref not in node_ids:
                problems.append(f"{f.get('id')}: {which}={ref!r} does not resolve")
        targeted.add(tgt)

    for el in proc:
        tag = el.tag.split("}")[-1]
        eid = el.get("id", "")
        if tag in ("sequenceFlow", "startEvent"):
            continue
        if tag == "boundaryEvent":
            if el.get("attachedToRef") not in node_ids:
                problems.append(f"{eid}: attachedToRef does not resolve")
            continue
        if eid not in targeted:
            problems.append(f"{eid} ({tag}) is unreachable -- no incoming flow")

    for gw in proc.findall(f"{{{BPMN_NS}}}exclusiveGateway"):
        out = [f for f in flows if f.get("sourceRef") == gw.get("id")]
        if len(out) > 1:
            unconditioned = [
                f for f in out
                if f.find(f"{{{BPMN_NS}}}conditionExpression") is None
                and gw.get("default") != f.get("id")
            ]
            if unconditioned:
                # This is exactly the defect P3 hit on contracts/examples/artifact.bpmn:
                # a split with neither a condition nor a default will not execute.
                problems.append(
                    f"{gw.get('id')}: outgoing flow(s) "
                    f"{[f.get('id') for f in unconditioned]} have no condition and are not the default"
                )
    return problems
