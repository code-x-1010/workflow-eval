"""DMN 1.3 XML -> canonical DecisionModel.

Owner: P1. FROZEN types consumed from wfeval.core.dmn -- if this file and
that module ever disagree, wfeval.core.dmn wins and this file is the bug.

Full DMN 1.3 XSD validation is NOT implemented here -- same conscious choice
as bpmn.py's L1 gap (see that module's docstring). The structural shape
extracted below (`definitions` -> `decision` -> `decisionTable` ->
`input`/`output`/`rule`, each `inputEntry`/`outputEntry` holding a `<text>`
FEEL literal) is real DMN 1.3 per the OMG spec's own worked examples, not a
memory reconstruction of the full schema -- but nothing here claims to
reject every malformed DMN file, only to extract what's actually present.

A `<decision>` using a `<literalExpression>` instead of a `<decisionTable>`
is recognized (doesn't raise) but its `table` is left `None` rather than
guessed at -- see `wfeval.core.dmn.Decision.table`'s docstring.

Locators follow the same XPath-shaped, id-qualified convention as
`wfeval.adapters.bpmn` -- see that module's docstring for the exact format.
"""
from __future__ import annotations

import hashlib

from lxml import etree
from wfeval.core.dmn import Decision, DecisionModel, DecisionTable, HitPolicy, InputClause, OutputClause, Rule

from .errors import AdapterParseError


def parse(content: str) -> DecisionModel:
    root = _fromstring(content)
    if _local(root) != "definitions":
        raise AdapterParseError(f"Expected a DMN <definitions> root, got <{_local(root)}>.")
    definitions_id = root.get("id")
    if not definitions_id:
        raise AdapterParseError("<definitions> element has no id.")

    decisions = [_build_decision(el) for el in root if isinstance(el.tag, str) and _local(el) == "decision"]
    if not decisions:
        raise AdapterParseError("No <decision> elements found under <definitions>.")

    return DecisionModel(
        definitions_id=definitions_id,
        decisions=decisions,
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


def _text(el: etree._Element | None) -> str | None:
    if el is None:
        return None
    child_text = _child(el, "text")
    raw = child_text.text if child_text is not None else el.text
    return raw.strip() if raw and raw.strip() else None


def _build_decision(el: etree._Element) -> Decision:
    decision_id = _require_id(el)
    table_el = _child(el, "decisionTable")
    return Decision(
        id=decision_id,
        name=el.get("name"),
        locator=_locator(el),
        table=_build_table(table_el) if table_el is not None else None,
    )


def _build_table(el: etree._Element) -> DecisionTable:
    hit_policy_raw = el.get("hitPolicy", "UNIQUE")
    try:
        hit_policy = HitPolicy(hit_policy_raw)
    except ValueError as e:
        raise AdapterParseError(
            f"<decisionTable id={el.get('id')!r}>: unrecognized hitPolicy {hit_policy_raw!r}."
        ) from e

    inputs = [_build_input(c) for c in el if isinstance(c.tag, str) and _local(c) == "input"]
    outputs = [_build_output(c) for c in el if isinstance(c.tag, str) and _local(c) == "output"]
    if not inputs:
        raise AdapterParseError(f"<decisionTable id={el.get('id')!r}> has no <input> clauses.")
    if not outputs:
        raise AdapterParseError(f"<decisionTable id={el.get('id')!r}> has no <output> clauses.")

    rules = [_build_rule(c, len(inputs), len(outputs))
             for c in el if isinstance(c.tag, str) and _local(c) == "rule"]

    return DecisionTable(hit_policy=hit_policy, inputs=inputs, outputs=outputs, rules=rules)


def _build_input(el: etree._Element) -> InputClause:
    expr_el = _child(el, "inputExpression")
    expression = _text(expr_el)
    if not expression:
        raise AdapterParseError(f"<input id={el.get('id')!r}> has no inputExpression text.")
    return InputClause(id=_require_id(el), label=el.get("label"), expression=expression)


def _build_output(el: etree._Element) -> OutputClause:
    name = el.get("name")
    if not name:
        raise AdapterParseError(f"<output id={el.get('id')!r}> has no name attribute.")
    return OutputClause(id=_require_id(el), label=el.get("label"), name=name)


def _build_rule(el: etree._Element, expected_inputs: int, expected_outputs: int) -> Rule:
    rule_id = _require_id(el)
    input_entries: list[str | None] = []
    output_entries: list[str] = []
    for c in el:
        if not isinstance(c.tag, str):
            continue
        tag = _local(c)
        if tag == "inputEntry":
            raw = _text(c)
            input_entries.append(None if raw in (None, "-") else raw)
        elif tag == "outputEntry":
            raw = _text(c)
            output_entries.append(raw if raw is not None else "")

    if len(input_entries) != expected_inputs:
        raise AdapterParseError(
            f"<rule id={rule_id!r}> has {len(input_entries)} inputEntry elements, "
            f"expected {expected_inputs} (one per <input> clause)."
        )
    if len(output_entries) != expected_outputs:
        raise AdapterParseError(
            f"<rule id={rule_id!r}> has {len(output_entries)} outputEntry elements, "
            f"expected {expected_outputs} (one per <output> clause)."
        )

    return Rule(id=rule_id, locator=_locator(el), input_entries=input_entries, output_entries=output_entries)


def _locator(el: etree._Element) -> str:
    """Same convention as wfeval.adapters.bpmn._locator -- id-qualified at
    every level except the single-per-file `definitions` ancestor."""
    ancestors: list[str] = []
    node = el.getparent()
    while node is not None:
        tag = _local(node)
        if tag == "definitions":
            ancestors.append("definitions")
            break
        nid = node.get("id")
        ancestors.append(f"{tag}[@id='{nid}']" if nid else tag)
        node = node.getparent()
    ancestors.reverse()

    leaf_tag = _local(el)
    leaf_id = el.get("id")
    leaf = f"{leaf_tag}[@id='{leaf_id}']" if leaf_id else leaf_tag
    return "/" + "/".join([*ancestors, leaf])
