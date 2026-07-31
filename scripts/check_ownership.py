#!/usr/bin/env python3
"""Fail if an agent edited files outside its lane.

Four agents run in separate sessions and cannot see each other's work. A
"helpful" edit to another service is invisible to its owner and will be
clobbered or conflict. Run before every commit:  make check-ownership

Usage:  AGENT=P2 python scripts/check_ownership.py [--base main]
"""
from __future__ import annotations

import os
import subprocess
import sys

LANES: dict[str, list[str]] = {
    "P1": ["packages/", "services/validation/", "services/gateway/",
           ".github/", "Makefile", "pyproject.toml", ".importlinter", "CODEOWNERS", "scripts/"],
    "P2": ["services/intent/", "datasets/"],
    "P3": ["services/sandbox/", "sandbox-infra/"],
    "P4": ["services/cost/", "services/gateway/src/weights.yaml",
           "services/gateway/src/score.py", "services/gateway/src/render.py"],
}
# Everyone may touch these.
SHARED = ["docs/decisions/", "tests/fixtures/", "contracts/examples/", "README.md"]

# P4 owns three files inside P1's gateway; make sure the prefix rule doesn't
# accidentally grant P4 the whole directory.
EXPLICIT_ONLY = {"P4": ["services/gateway/"]}


def changed_files(base: str) -> list[str]:
    out = subprocess.run(["git", "diff", "--name-only", f"{base}...HEAD"],
                         capture_output=True, text=True)
    if out.returncode != 0:
        out = subprocess.run(["git", "diff", "--name-only"], capture_output=True, text=True)
    return [f for f in out.stdout.splitlines() if f.strip()]


def allowed(agent: str, path: str) -> bool:
    if path.startswith(tuple(SHARED)):
        return True
    if path == f"docs/handoff/{agent}.md" or path.startswith(f"docs/agents/{agent}"):
        return True
    for restricted in EXPLICIT_ONLY.get(agent, []):
        if path.startswith(restricted):
            return path in LANES[agent]
    return path.startswith(tuple(LANES[agent]))


def main() -> int:
    agent = os.environ.get("AGENT", "").upper()
    if agent not in LANES:
        print("Set AGENT=P1|P2|P3|P4 before committing. See AGENTS.md.", file=sys.stderr)
        return 2
    base = sys.argv[sys.argv.index("--base") + 1] if "--base" in sys.argv else "main"
    violations = [f for f in changed_files(base) if not allowed(agent, f)]
    if violations:
        print(f"\n{agent} edited files outside its lane:\n", file=sys.stderr)
        for v in violations:
            print(f"  {v}", file=sys.stderr)
        print("\nThose files belong to another agent who cannot see your session.", file=sys.stderr)
        print("Revert them. If you need a change there, open docs/decisions/NNNN-*.md.\n", file=sys.stderr)
        return 1
    print(f"{agent}: ownership OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
