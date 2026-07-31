# Handoff notes — the agents' memory

An agent session ends and everything it learned evaporates. These files are how each
agent survives that, and how the humans see state at standup.

**Append at the end of every session.** Read your own file at the start of every session,
before touching code.

Be concrete. "Worked on validation" is useless. "L3 gateway-balance in
`services/validation/src/l3_structure.py:88` handles exclusive splits but not inclusive;
inclusive needs the token-count approach, see decision 0003" is useful.
