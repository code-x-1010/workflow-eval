# AGENTS.md — read this before anything else

Four engineers are building this repo. Each runs **their own coding agent in a separate session**. The agents cannot see each other, cannot message each other, and do not share memory. Four parallel agents editing one repo is normally a recipe for merge hell and silent contract drift.

This file is the protocol that makes it work. Every agent reads this file first, every session, before touching code.

---

## 1. Identify yourself

Your human will tell you which of P1–P4 you are. If they haven't, **ask before writing any code.** Then read, in this order:

1. This file.
2. `docs/agents/P<N>-*.md` — your charter: ownership, contract, deliverables, traps.
3. `docs/handoff/P<N>.md` — **your own notes from your previous session.** You have no memory across sessions. This file is your memory. Read it first, append to it last.
4. `contracts/<your-service>.openapi.yaml` — your frozen interface.

---

## 2. The one rule that matters

> **Stay inside your directory. Consume everyone else through frozen contracts and golden examples.**

You will be tempted to fix things you find in other people's code. Do not. A "helpful" edit to another service is invisible to the agent that owns it, and they will overwrite it or conflict with it. Their bug is their bug; report it, don't fix it.

### Ownership map

| Agent | May edit | Must never edit |
|---|---|---|
| **P1** | `packages/**`, `services/validation/**`, `services/gateway/**` | `services/{intent,sandbox,cost}/**` |
| **P2** | `services/intent/**`, `datasets/**` | `packages/**`, `services/{validation,sandbox,cost,gateway}/**` |
| **P3** | `services/sandbox/**`, `sandbox-infra/**` | `packages/**`, `services/{validation,intent,cost,gateway}/**` |
| **P4** | `services/cost/**`, `services/gateway/src/{weights.yaml,score.py,render.py}` | `packages/**`, `services/{validation,intent,sandbox}/**` |

Everyone may add to: `docs/decisions/`, `docs/handoff/<your own file>`, `tests/fixtures/`, `contracts/examples/<your own outputs>`.

`CODEOWNERS` enforces this at review. `make check-ownership` enforces it locally. Run it before you commit.

---

## 3. Frozen contracts

**Frozen after Day 2:**

- `packages/wfeval-core/**` — shared types
- `contracts/*.openapi.yaml` — service interfaces

These are the only things four isolated agents share. If they drift, integration fails in week 2 and the project fails with it.

### Changing a frozen contract

If you conclude a frozen type or contract is wrong:

1. **Stop. Do not edit it.**
2. Write `docs/decisions/NNNN-short-title.md` using the template in that directory. State what's wrong, what you propose, and who else it affects.
3. Tell your human, in your response, that you are blocked pending a decision.
4. Work around it locally if you can, and note the workaround in your handoff file.

An agent that silently edits a shared type has broken three other people's builds and nobody will know until CI turns red in a way that looks like someone else's fault.

**Exception, Days 1–2 only:** P1 is actively drafting these. Before the D2 freeze, propose changes to P1 through a decision record and they will be folded in.

---

## 4. How to work when the services you need don't exist yet

This is the core of the design. **Nobody waits for anybody.**

### Golden examples

`contracts/examples/` holds realistic, contract-valid payloads for every service boundary. They are committed to the repo, so they are available to every agent regardless of whether the producing service runs.

| File | Produced by | Consumed by |
|---|---|---|
| `artifact.bpmn` | shared fixture | everyone |
| `validation.response.json` | P1 | P4 (Gateway aggregation), tests |
| `testcases.response.json` | **P2** | **P3** |
| `execution.response.json` | **P3** | **P4** (calibration) |
| `cost.response.json` | P4 | P1 (Gateway aggregation) |

**Your first deliverable is your golden example, not your implementation.** If you produce something another agent consumes, commit a realistic example of it by **Day 2**. P3 builds their execution loop against `testcases.response.json` on Day 3 — three days before P2's generator actually works.

An example that is unrealistic is worse than none. Make it look like real output: real element ids from `artifact.bpmn`, plausible values, edge cases included.

### Dependency stubs

Every service supports `WFEVAL_STUB_DEPS=1`. In that mode it serves the golden examples instead of calling real dependencies. So:

```bash
make dev            # whole stack, all deps stubbed — always works
make dev-real       # real inter-service calls — expect breakage until D8
```

You can always run the full stack. You can always test your service end to end. You are never blocked on another agent.

---

## 5. The Day 3 stub milestone

By end of Day 3 **every service must return contract-valid responses**, even if every value is hardcoded nonsense.

This is non-negotiable and it is the most important date in the schedule. With four independently built services, integration failure discovered in week 2 is fatal. Prove the wiring on fake data first; spend the remaining seven days on real logic behind stable interfaces.

`make contract` must pass from Day 3 onward. If it goes red, that is a stop-work event for whoever broke it.

---

## 6. Handoff notes — your memory

Your session ends and everything you learned evaporates. `docs/handoff/P<N>.md` is how you survive that.

**At the end of every working session, append:**

```markdown
## YYYY-MM-DD

**Done:** what actually landed, with file paths.
**In progress:** what is half-built and where the loose end is.
**Blocked on:** decisions pending, other agents, external access.
**Decisions I made:** non-obvious choices a future session would otherwise re-litigate.
**Next session, start here:** one concrete instruction to your future self.
```

Be concrete. "Worked on validation" is useless. "L3 gateway-balance check in `services/validation/src/l3_structure.py:88` handles exclusive splits but not inclusive; inclusive needs the token-count approach, see decision 0003" is useful.

Your human reads these at standup. So do you, next session.

---

## 7. Cross-agent communication

You have exactly three channels. All of them are files, all of them go through a human.

| Channel | Use for | Path |
|---|---|---|
| **Decision records** | Anything affecting a shared contract or another agent | `docs/decisions/NNNN-*.md` |
| **Golden examples** | "Here is what my output looks like, build against it" | `contracts/examples/` |
| **Handoff notes** | Status, blockers, context | `docs/handoff/P<N>.md` |

There is no fourth channel. Do not leave `TODO(P3)` comments in another agent's files — they will never see them.

### The two hard cross-team dependencies

Both must be agreed by **Day 2** and both live in `packages/wfeval-core/`:

1. **P2 → P3** — `TestCase`, `Assertion`, `MockDefinition` in `testcase.py`. P2 proposes, P3 signs off.
2. **P3 → P4** — `Actuals` in `trace.py`. P3 proposes, P4 signs off.

If either is unresolved on Day 3, escalate to your human immediately. These are the only two places where four isolated workstreams genuinely touch.

---

## 8. Definition of done

A deliverable is done when all five hold:

1. `make test` passes — your unit tests, including a fixture per diagnostic code you emit.
2. `make contract` passes — your service satisfies its OpenAPI spec.
3. `make lint` passes — ruff, mypy strict, import-linter.
4. `make check-ownership` passes — you touched nothing outside your lane.
5. Your handoff file is updated.

Code that works but has no fixture is not done. The fixtures are how the next agent session (and the other three engineers) know your behaviour without reading your implementation.

---

## 9. House rules

- **Diagnostic codes are append-only.** Never rename or repurpose one. The generation team keys repair logic off these strings. You may only emit codes under your own prefixes (`PREFIX_OWNER` in `diagnostics.py`).
- **Every diagnostic needs a `suggested_fix`** phrased as an imperative the generator can act on. "Connect an outgoing flow from `Gateway_0kk`" — not "the graph is invalid".
- **Never ship a number without its confidence.** Applies to cost estimates, intent scores, and soundness results alike. An unqualified number will be screenshotted into a slide deck by Friday.
- **New analysers ship at `warning` severity first.** Promote to `error` only after fixtures validate them. A false-positive hard-fail destroys the generation team's trust in the whole layer, and you do not get it back.
- **Prefer boring.** Two weeks. Four people. No Kubernetes, no service mesh, no new frameworks. If you are reaching for a dependency not in `pyproject.toml`, write a decision record.
- **Ask rather than assume.** If your charter is ambiguous, say so in your response instead of picking an interpretation and building three days on it.
