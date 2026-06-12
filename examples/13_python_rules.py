"""
================================================================
EXAMPLE 13 — "Python rules + rule-error diagnostics" (ADVANCED)
================================================================

SCENARIO:
    YAML can't easily express things like "the path the agent is about to
    touch escapes the workspace". For that, drop into a Python rule. This
    example shows:

      1. A Python rule that blocks path-escape attempts
      2. A Python rule that intentionally raises — to demonstrate that
         exceptions become diagnostic markers in matched_rules instead of
         silently failing-open
      3. Python and YAML rules interleaved by priority (a higher-priority
         YAML rule wins; a higher-priority Python rule wins back)

WHAT THIS EXAMPLE SHOWS:
    - `compile_policy(..., python_rules=(fn1, fn2), python_rule_priorities=(...))`
    - The Python rule contract: `(ActionRequest, ExecutionContext) -> Decision | None`
    - `<rule_error:rule_id:ExceptionName>` markers in `Decision.matched_rules`
    - Priority interleaving: same priority means file order; different
      priority means highest wins regardless of source

RUN WITH:
    python examples/13_python_rules.py
"""

from __future__ import annotations

import asyncio
import os

from lynx import (
    ActionRequest,
    Decision,
    ExecutionContext,
    FinalAnswer,
    Message,
    ToolCall,
    ToolSet,
    auto_deny,
    callback_sink,
    compile_policy,
    deny,
    run_agent,
    stdout_sink,
    tool,
)


@tool(reversible=True, scope=("filesystem:read",))
async def read_file(path: str) -> str:
    """Pretend to read a file (returns the path so the demo stays offline)."""
    return f"contents of {path}"


# ---------------------------------------------------------------------------
# Python rules
# ---------------------------------------------------------------------------


def block_paths_outside_workspace(req: ActionRequest, ctx: ExecutionContext) -> Decision | None:
    """Deny any read_file call whose path resolves outside ctx.workspace."""
    if req.tool != "read_file":
        return None  # not our concern
    path = req.args.get("path", "")
    workspace = os.path.abspath(ctx.workspace)
    absolute = os.path.abspath(os.path.join(workspace, path))
    if not absolute.startswith(workspace + os.sep) and absolute != workspace:
        return deny(reason=f"path {absolute!r} escapes workspace {workspace!r}")
    return None


def buggy_rule(req: ActionRequest, ctx: ExecutionContext) -> Decision | None:
    """Intentionally broken — raises on every call so we can see the
    diagnostic marker in matched_rules."""
    raise RuntimeError("oops, the rule code is wrong")


# ---------------------------------------------------------------------------
# YAML side — interacts with the Python rules by priority
# ---------------------------------------------------------------------------


POLICY_YAML = """
version: 1
defaults: { on_no_match: allow }
rules:
  - id: yaml-allow-relative-reads
    priority: 50
    match: { tool: read_file }
    decision: allow
"""


# ---------------------------------------------------------------------------
# Scripted agent
# ---------------------------------------------------------------------------


class _ScriptedAgent:
    def __init__(self):
        self._plan = [
            # Normal read inside workspace — Python rule abstains; YAML allows.
            ToolCall("read_file", {"path": "notes.txt"}, call_id="c1"),
            # Path that escapes workspace — Python rule denies.
            ToolCall("read_file", {"path": "../../../etc/passwd"}, call_id="c2"),
            FinalAnswer(text="done"),
        ]
        self._i = 0

    async def step(self, conv: tuple[Message, ...]):
        action = self._plan[self._i]
        self._i += 1
        return action


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------


async def main() -> None:
    bundle = compile_policy(
        POLICY_YAML,
        # Python rules MUST be passed explicitly — no global registry.
        python_rules=(block_paths_outside_workspace, buggy_rule),
        # The path-escape rule outranks YAML (priority 100 > 50).
        # The buggy rule sits at low priority but still gets evaluated every
        # step, demonstrating that exceptions surface as diagnostics, not
        # silent skips.
        python_rule_priorities=(
            ("block_paths_outside_workspace", 100),
            ("buggy_rule", 10),
        ),
    )

    matched_rules_seen: list[tuple[str, ...]] = []

    async def collect(event):
        if event.kind == "policy.evaluated":
            matched_rules_seen.append(tuple(event.body["matched_rules"]))

    result = await run_agent(
        _ScriptedAgent(),
        task="read two files",
        tools=ToolSet.from_functions(read_file),
        policy=bundle,
        sinks=(stdout_sink(), callback_sink(collect)),
        on_approval=auto_deny("not used"),
        workspace=os.getcwd(),
    )

    print()
    print(f"Final answer: {result.final_answer}")
    print()
    print("matched_rules across the two policy.evaluated events:")
    for i, m in enumerate(matched_rules_seen, start=1):
        print(f"  step {i}: {list(m)}")
    print()
    print("Notice:")
    print("  - Step 1's matched_rules includes '<rule_error:buggy_rule:RuntimeError>'")
    print("    AND ends in 'yaml-allow-relative-reads' — the buggy rule did NOT")
    print("    fail-open; it was recorded and evaluation continued.")
    print("  - Step 2's matched_rules ends in 'block_paths_outside_workspace' —")
    print("    the Python rule (priority 100) beat the YAML rule (priority 50).")


if __name__ == "__main__":
    asyncio.run(main())
