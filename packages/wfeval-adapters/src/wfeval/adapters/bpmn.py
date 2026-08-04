"""BPMN 2.0 XML -> canonical WorkflowAST.

Owner: P1. FROZEN types consumed from wfeval.core.ast -- if this file and
ast.py ever disagree, ast.py wins and this file is the bug.

NEVER imported by services/intent/src/testgen/** -- enforced by .importlinter
contract 1 (wfeval.core depends on nothing) plus contract 2 (testgen may not
see wfeval.adapters at all).

Locators are set at construction time, not retrofitted -- see
docs/agents/P1-validation.md. Format matches the convention already used in
contracts/examples/validation.response.json: `/definitions/process/serviceTask[@id='Task_notify']`,
ancestor `definitions`/`process` segments left bare, every other segment
(including nested subProcess) gets an `[@id='...']` predicate for
disambiguation.

KNOWN v1 LIMITATIONS (fail loudly via AdapterParseError rather than silently
mis-modelling -- see tests/fixtures/bpmn/adapter_rich.bpmn and
docs/handoff/P1.md, 2026-08-03 entry, for what IS covered):

- Only `timerEventDefinition` is understood on intermediate/boundary events.
  Message, error, signal and escalation events have no ElementKind to map to
  yet (the enum is frozen) -- raises rather than dropping the element, since
  a silently-dropped task/event would corrupt L3 reachability far worse than
  a loud parse failure would.
- `callActivity` is not supported for the same reason (it isn't a task, and
  treating it as one would hide a process-boundary crossing from L3/L4).
- `declared_variables` is always `{}`. No verified UiPath convention for a
  process-level variable declaration table exists in this repo yet (the
  <uipath:variables> read/write markers below are per-element, not a process-
  level table). L4 dataflow falls back to first-write-wins when nothing is
  declared.
- `Element.expressions` is always `[]`. Only `Flow.condition_expr` is
  populated today (from standard BPMN <conditionExpression>); task-level
  expression extraction (e.g. business rule task input mappings) needs a
  verified UiPath export to model correctly and isn't guessed at here.
- The `uipath:*` namespace/attributes (`activityType`, `assetRef`, the
  `<uipath:variables>` extension) are wfeval-adapters' OWN PROVISIONAL
  convention, not a verified UiPath Maestro export -- isolated to this file
  (`UIPATH_NS`, `_kind_for`, `_variables`, `_asset_ref`) so it is a one-file
  change when a real sample lands. Everything else this module reads
  (`conditionExpression`, `multiInstanceLoopCharacteristics`, `default`,
  `timerEventDefinition`) is plain BPMN 2.0, verified against
  tests/fixtures/spiff/executable_invoice.bpmn.
"""
from __future__ import annotations

import hashlib

from lxml import etree
from wfeval.core.ast import Element, ElementKind, Flow, LoopSpec, WorkflowAST

from .errors import AdapterParseError

BPMN_NS = "http://www.omg.org/spec/BPMN/20100524/MODEL"
UIPATH_NS = "http://uipath.com/schema/maestro"

# Direct children of <process>/<subProcess> that are never flow nodes -- safe
# to skip outright. Anything NOT in this set is assumed to be a flow node and
# goes through _kind_for(), which raises for anything it can't classify.
_SKIP_TAGS = frozenset({
    "laneSet", "lane", "ioSpecification", "dataObject", "dataObjectReference",
    "dataStoreReference", "textAnnotation", "association", "extensionElements",
    "documentation", "category", "resourceRole", "property", "performer",
    "potentialOwner", "correlationSubscription",
})

_AGENT_CAPABLE_TAGS = frozenset({"serviceTask", "task", "scriptTask", "sendTask", "receiveTask", "manualTask"})


def parse(content: str, *, platform: str = "uipath_maestro") -> WorkflowAST:
    """Parse BPMN 2.0 XML into a canonical WorkflowAST.

    `platform` is the deploy target this artifact targets -- it isn't
    reliably inferrable from generic BPMN markup, so callers (Validation's
    /v1/validate, Gateway) pass through whatever the request declared.
    """
    root = _fromstring(content)

    if _local(root) != "definitions":
        raise AdapterParseError(f"Expected a BPMN <definitions> root, got <{_local(root)}>.")

    process = _child(root, "process")
    if process is None:
        raise AdapterParseError("No <process> element found under <definitions>.")
    process_id = process.get("id")
    if not process_id:
        raise AdapterParseError("<process> element has no id.")

    elements: list[Element] = []
    flows: list[Flow] = []
    default_flow_ids: set[str] = set()

    def walk(container: etree._Element) -> None:
        for el in container:
            if not isinstance(el.tag, str):  # comments, PIs
                continue
            tag = _local(el)
            if tag == "sequenceFlow":
                flows.append(_build_flow(el))
                continue
            if tag in _SKIP_TAGS:
                continue

            kind = _kind_for(el)
            default_ref = el.get("default")
            if default_ref:
                default_flow_ids.add(default_ref)
            reads, writes = _variables(el)
            elements.append(Element(
                id=_require_id(el),
                kind=kind,
                name=el.get("name"),
                locator=_locator(el),
                loop=_loop_spec(el),
                expressions=[],
                variables_read=reads,
                variables_written=writes,
                asset_ref=_asset_ref(el),
                attributes=_uipath_attributes(el),
            ))
            if tag == "subProcess":
                walk(el)

    walk(process)

    for flow in flows:
        if flow.id in default_flow_ids:
            flow.is_default = True

    return WorkflowAST(
        platform=platform,
        process_id=process_id,
        elements=elements,
        flows=flows,
        declared_variables={},
        digest=f"sha256:{hashlib.sha256(content.encode('utf-8')).hexdigest()}",
    )


def _fromstring(content: str) -> etree._Element:
    try:
        return etree.fromstring(content.encode("utf-8"))
    except etree.XMLSyntaxError as e:
        raise AdapterParseError(f"Malformed XML: {e}") from e


def _local(el: etree._Element) -> str:
    return str(etree.QName(el).localname)


def _child(el: etree._Element, localname: str) -> etree._Element | None:
    for c in el:
        if isinstance(c.tag, str) and _local(c) == localname:
            return c
    return None


def _require_id(el: etree._Element) -> str:
    el_id: str | None = el.get("id")
    if not el_id:
        raise AdapterParseError(f"<{_local(el)}> element has no id.")
    return el_id


def _kind_for(el: etree._Element) -> ElementKind:
    tag = _local(el)
    if tag == "startEvent":
        return ElementKind.START_EVENT
    if tag == "endEvent":
        return ElementKind.END_EVENT
    if tag in ("intermediateCatchEvent", "intermediateThrowEvent", "boundaryEvent"):
        if _child(el, "timerEventDefinition") is not None:
            return ElementKind.TIMER
        raise AdapterParseError(
            f"<{tag} id={el.get('id')!r}>: only timerEventDefinition is supported today "
            "(no ElementKind exists yet for message/error/signal/escalation events)."
        )
    if tag == "exclusiveGateway":
        return ElementKind.GATEWAY_EXCLUSIVE
    if tag == "parallelGateway":
        return ElementKind.GATEWAY_PARALLEL
    if tag == "inclusiveGateway":
        return ElementKind.GATEWAY_INCLUSIVE
    if tag == "subProcess":
        return ElementKind.SUBPROCESS
    if tag == "businessRuleTask":
        return ElementKind.DECISION_TASK
    if tag == "userTask":
        return ElementKind.USER_TASK
    if tag in _AGENT_CAPABLE_TAGS:
        if el.get(f"{{{UIPATH_NS}}}activityType") == "Agent":
            return ElementKind.AGENT_TASK
        return ElementKind.SERVICE_TASK
    raise AdapterParseError(f"<{tag} id={el.get('id')!r}> is not yet mapped to an ElementKind.")


def _build_flow(el: etree._Element) -> Flow:
    # Flow has no `locator` field (only Element does, per ast.py) -- flows are
    # located via their source/target element ids instead.
    cond_el = _child(el, "conditionExpression")
    return Flow(
        id=_require_id(el),
        source=el.get("sourceRef", ""),
        target=el.get("targetRef", ""),
        condition_expr=cond_el.text.strip() if cond_el is not None and cond_el.text else None,
        is_default=False,  # patched by parse() once every node's `default` attr is known
    )


def _loop_spec(el: etree._Element) -> LoopSpec | None:
    mi = _child(el, "multiInstanceLoopCharacteristics")
    if mi is None:
        return None
    is_parallel = mi.get("isSequential", "true").strip().lower() != "true"
    card_el = _child(mi, "loopCardinality")
    max_iterations: int | None = None
    cardinality_expr: str | None = None
    if card_el is not None and card_el.text and card_el.text.strip():
        text = card_el.text.strip()
        if text.isdigit():
            max_iterations = int(text)
        else:
            cardinality_expr = text
    return LoopSpec(max_iterations=max_iterations, cardinality_expr=cardinality_expr, is_parallel=is_parallel)


def _variables(el: etree._Element) -> tuple[list[str], list[str]]:
    ext = _child(el, "extensionElements")
    if ext is None:
        return [], []
    vars_el = _child(ext, "variables")
    if vars_el is None:
        return [], []
    reads: list[str] = []
    writes: list[str] = []
    for c in vars_el:
        if not isinstance(c.tag, str):
            continue
        name = c.get("name")
        if not name:
            continue
        if _local(c) == "read":
            reads.append(name)
        elif _local(c) == "write":
            writes.append(name)
    return reads, writes


def _asset_ref(el: etree._Element) -> str | None:
    ref: str | None = el.get(f"{{{UIPATH_NS}}}assetRef")
    return ref


def _uipath_attributes(el: etree._Element) -> dict[str, str]:
    prefix = f"{{{UIPATH_NS}}}"
    return {
        etree.QName(k).localname: v
        for k, v in el.attrib.items()
        if isinstance(k, str) and k.startswith(prefix)
    }


def _locator(el: etree._Element) -> str:
    """XPath-shaped locator, id-qualified at every level except the
    single-per-file `definitions`/`process` ancestors. Matches the format
    already used in contracts/examples/validation.response.json's golden
    diagnostics."""
    ancestors: list[str] = []
    node = el.getparent()
    while node is not None:
        tag = _local(node)
        if tag == "definitions":
            ancestors.append("definitions")
            break
        if tag == "process":
            ancestors.append("process")
        else:
            nid = node.get("id")
            ancestors.append(f"{tag}[@id='{nid}']" if nid else tag)
        node = node.getparent()
    ancestors.reverse()

    leaf_tag = _local(el)
    leaf_id = el.get("id")
    leaf = f"{leaf_tag}[@id='{leaf_id}']" if leaf_id else leaf_tag
    return "/" + "/".join([*ancestors, leaf])
