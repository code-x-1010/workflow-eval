"""Gateway fan-out. Owner: P1.

The short-circuit is not an optimisation. Across a corpus run it is the
difference between an hour and a day -- an artifact that fails L1 should never
consume sandbox minutes or LLM judge calls.
"""
from __future__ import annotations

STAGES = """
1. Validation /v1/validate                       (sync, ~500ms)
   any gate false -> verdict=fail, SKIP 2-4, short_circuited_at="validation"
2. parallel:
     a. Intent /v1/intent  +  /v1/testcases
     b. Cost   /v1/cost
     c. Sandbox /v1/deploy                        (L5 acceptance)
   deploy rejected -> verdict=fail, SKIP 3, short_circuited_at="deploy"
3. Sandbox /v1/executions   (consumes 2a's test cases)   <- minutes, long pole
4. P4's score() + render(); deliver via callback
"""

# TODO(P1 D3): implement against stubs. TODO(P1 D9): async queue + webhook retry.
