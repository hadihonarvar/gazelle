"""
================================================================
EXAMPLE 27 — "Handoff graph: the edge is a permission boundary" (ADVANCED)
================================================================

SCENARIO:
    Multi-agent setups usually fail two ways: the orchestrator agent
    bypasses its role and does the work itself (tool bleed), and handoffs
    lose context. Lynx's handoff graph fixes both structurally:

      - each node is one complete run_agent() call with ITS OWN policy,
        tools, and budget — the triage node CANNOT write even if its
        model tries (enforced, not prompted)
      - context passing is explicit: the next node's task carries the
        previous node's result, clearly marked
      - edges are pure predicates over outcomes — including DENIAL COUNTS,
        a routing signal only possible because policy is first-class
      - mandatory max_transitions: unbounded recursion is impossible

    And it's all OPTIONAL — a node is just a run_agent() call, so this
    module is declarative sugar over a loop you could write yourself.

WHAT THIS EXAMPLE SHOWS:
    - The killer pattern: triage (read-only) → fixer (write) → reviewer
      (read-only), looping fixer↔reviewer until approved
    - The SAME policy file refusing writes in one node and a different
      policy allowing them in the next
    - YAML-declared edges (compile_graph) with answer_matches routing
    - The full path printed with per-node denial counts

RUN WITH:
    python examples/27_handoff_graph.py
"""

from __future__ import annotations

import asyncio

from lynx import (
    FinalAnswer,
    GraphNode,
    Message,
    ToolCall,
    ToolSet,
    compile_graph,
    compile_policy,
    run_graph,
    tool,
)

# ---------------------------------------------------------------------------
# Tools — one read, one write. Which node may use which is POLICY, not vibes.
# ---------------------------------------------------------------------------


@tool(reversible=True, scope=("fs:read",))
async def read_file(path: str) -> str:
    return f"def login(user):  # TODO: timing-unsafe compare in {path}"


@tool(reversible=True, scope=("fs:write",))
async def patch_file(path: str, change: str) -> str:
    return f"patched {path}: {change}"


TOOLS = ToolSet.from_functions(read_file, patch_file)

READ_ONLY = compile_policy(
    """
version: 1
defaults: { on_no_match: allow }
rules:
  - id: no-writes-here
    match: { declared.scope.contains: "fs:write" }
    decision: deny
    reason: this node is read-only — hand off to the fixer
"""
)
CAN_WRITE = compile_policy("version: 1\ndefaults: { on_no_match: allow }\nrules: []")


# ---------------------------------------------------------------------------
# Scripted "models" so the demo is deterministic and offline. Note the triage
# model TRIES to patch — and gets denied, because its node is read-only.
# ---------------------------------------------------------------------------


class TriageAgent:
    async def step(self, conv: tuple[Message, ...]):
        text = " ".join(m.content for m in conv)
        if "timing-unsafe" not in text:
            return ToolCall(tool="read_file", args={"path": "auth.py"}, call_id="c1")
        if "[denied]" not in text:
            # The model overreaches — it tries to fix it itself.
            return ToolCall(
                tool="patch_file", args={"path": "auth.py", "change": "hmac"}, call_id="c2"
            )
        return FinalAnswer(text="needs fix: timing-unsafe compare in auth.py")


class FixerAgent:
    async def step(self, conv: tuple[Message, ...]):
        text = " ".join(m.content for m in conv)
        if "patched" not in text:
            return ToolCall(
                tool="patch_file",
                args={"path": "auth.py", "change": "use hmac.compare_digest"},
                call_id="c1",
            )
        return FinalAnswer(text="patched auth.py with hmac.compare_digest")


class ReviewerAgent:
    def __init__(self) -> None:
        self.visits = 0

    async def step(self, conv: tuple[Message, ...]):
        self.visits += 1
        # First review rejects (sends it back to the fixer); second approves.
        if self.visits == 1:
            return FinalAnswer(text="rejected: missing constant-time note in docstring")
        return FinalAnswer(text="approved: patch is correct and documented")


# ---------------------------------------------------------------------------
# The graph — reviewable YAML. First matching edge wins; cycles are fine;
# max_transitions makes runaway loops impossible by construction.
# ---------------------------------------------------------------------------

GRAPH = compile_graph(
    """
version: 1
start: triage
max_transitions: 8
edges:
  - from: triage
    when: { status: succeeded, answer_matches: "(?i)needs fix" }
    to: fixer
  - from: triage
    to: done
  - from: fixer
    to: reviewer
  - from: reviewer
    when: { answer_matches: "(?i)approved" }
    to: done
  - from: reviewer
    to: fixer
"""
)


async def main() -> None:
    reviewer = ReviewerAgent()
    nodes = {
        "triage": GraphNode(agent=TriageAgent(), tools=TOOLS, policy=READ_ONLY),
        "fixer": GraphNode(agent=FixerAgent(), tools=TOOLS, policy=CAN_WRITE),
        "reviewer": GraphNode(agent=reviewer, tools=TOOLS, policy=READ_ONLY),
    }

    print("=" * 66)
    print("triage (read-only) -> fixer (write) -> reviewer (read-only) loop")
    print("=" * 66)

    result = await run_graph(nodes, "Fix the security bug in auth.py", router=GRAPH)

    for o in result.path:
        outcome = o.result.final_answer or o.result.error
        denials = f"  [{o.denials} denial(s)]" if o.denials else ""
        print(f"  hop {o.transitions}: {o.node:<9} -> {outcome}{denials}")

    print()
    print(f"  final: {result.final.final_answer}")
    print(f"  hops : {result.transitions + 1} node runs, error={result.error}")
    print()
    print("  Notice hop 0: the triage MODEL tried to patch the file itself —")
    print("  its node's policy denied it (that's the [1 denial(s)]), so it")
    print("  handed off instead. Role boundaries enforced, not prompted.")


if __name__ == "__main__":
    asyncio.run(main())
