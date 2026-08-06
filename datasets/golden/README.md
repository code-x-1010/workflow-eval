# `datasets/golden/` — the judge calibration set

## `intent_judgements.jsonl`

54 `(step description, element name)` pairs, each labelled `match` or `no_match`,
27 of each. They are the calibration set behind `judge_agreement` on every
`IntentReport`.

Each pair is deliberately **hard for a lexical matcher**: the `match` pairs share
few or no tokens ("Extract the vendor and the amount" / "Parse invoice fields"),
and the `no_match` pairs share almost all of them ("Store it in the document
management system" / "Delete it from the document management system"). That is
the point. A calibration set of easy pairs measures nothing — the deterministic
matcher in `align.py` already settles those, and what `judge_agreement` needs to
describe is performance on the residue that reaches the judge.

## Provenance — read this before quoting the number

**These labels were authored by P2. They are not independent human labels, and
the charter asked for ~50 human-labelled examples.** That gap is real and it is
not closed by this file.

Why it matters, stated plainly: the same party wrote the matcher, the judge
prompt, and the answer key. An agreement figure measured this way is an **upper
bound**. It tells you the judge behaves the way P2 expects on cases P2 chose; it
does not tell you the judge agrees with a domain expert who has never seen the
implementation. Those are different claims, and only the second is what a
calibration number is normally understood to mean.

What this file is genuinely good for:

- It is a real regression suite. A judge or matcher change that breaks on
  opposite-outcome pairs shows up immediately.
- The labels are defensible one by one: every entry carries a `why`, and the
  reasoning is about the *act*, not the wording ("revoke" vs "grant" are opposite
  acts; "file" vs "archive" are the same act).
- **The harness does not care where the labels came from.** Replacing this file
  with genuinely human-labelled pairs is a data change, not a code change — same
  schema, same loader, same `calibrate()` call.

`provenance` is a field on every row precisely so a later human pass can be mixed
in and told apart. Rows added by an independent labeller should carry
`"provenance": "human"` and the agreement should be reported over those alone.

## Schema

```json
{"id": "j001", "step": "...", "element": "...", "label": "match|no_match",
 "why": "...", "provenance": "authored_by_p2"}
```

## Regenerating

The file is committed, not generated at test time — a calibration set that
changes when the code changes is not a calibration set.
