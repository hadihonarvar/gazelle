"""
================================================================
EXAMPLE 19 — "Policy hot-swap + budget + unknown tool" (ADVANCED)
================================================================

SCENARIO:
    The README claims "hot-swappable per call" — the bundle is just an
    immutable value the kernel takes as a parameter. Pass a different
    bundle on the next call and the next call uses it; no restart, no
    cache invalidation. This example demonstrates that empirically.

    Also covered: two operational corner cases users hit:
      - Budget.steps exhaustion — the run ends gracefully with
        `error="step budget exhausted (N)"`, NOT an exception.
      - Unknown tool — the run continues; the agent sees an [error]
        message in the conversation; an `action.failed` event is emitted.

WHAT THIS EXAMPLE SHOWS:
    - The same agent + same tools producing DIFFERENT verdicts under two
      different policy bundles (no leaked state between calls)
    - `Budget(steps=3, duration_seconds=10)` cutting a runaway loop
    - The kernel surviving an unknown tool reference

RUN WITH:
    python examples/19_hot_swap.py
"""

from __future__ import annotations

import asyncio

from lynx import (
    Budget,
    FinalAnswer,
    Message,
    ToolCall,
    ToolSet,
    auto_deny,
    compile_policy,
    run_agent,
    stdout_sink,
    tool,
)


@tool(reversible=True, scope=("compute:read",))
async def echo(msg: str) -> str:
    return msg


PERMISSIVE = "version: 1\ndefaults: { on_no_match: allow }\nrules: []"

STRICT = """
version: 1
defaults: { on_no_match: deny }
rules: []
"""


class _OneShot:
    def __init__(self, tool_name: str):
        self._plan = [
            ToolCall(tool_name, {"msg": "hello"}, call_id="c1"),
            FinalAnswer(text="done"),
        ]
        self._i = 0

    async def step(self, conv: tuple[Message, ...]):
        a = self._plan[self._i]
        self._i += 1
        return a


class _NeverFinishes:
    """Used by the budget demo — keeps asking forever."""

    async def step(self, conv: tuple[Message, ...]):
        return ToolCall("echo", {"msg": "x"}, call_id="c")


async def main() -> None:
    tools = ToolSet.from_functions(echo)

    # -----------------------------------------------------------------------
    # Hot-swap: same code, different bundle => different verdict.
    # -----------------------------------------------------------------------
    print("=== Run A: permissive policy ===")
    a = await run_agent(
        _OneShot("echo"),
        task="hot-swap demo",
        tools=tools,
        policy=compile_policy(PERMISSIVE),
        sinks=(stdout_sink(),),
        on_approval=auto_deny("n/a"),
    )
    print(f"  final={a.final_answer}  bundle_id={a.bundle_id}")

    print()
    print("=== Run B: strict policy (default deny), same agent + same tools ===")
    b = await run_agent(
        _OneShot("echo"),
        task="hot-swap demo",
        tools=tools,
        policy=compile_policy(STRICT),
        sinks=(stdout_sink(),),
        on_approval=auto_deny("n/a"),
    )
    print(f"  final={b.final_answer}  bundle_id={b.bundle_id}")
    print("  (different bundle IDs prove they're distinct content-addressed values)")

    # -----------------------------------------------------------------------
    # Budget exhaustion — run ends gracefully, no exception thrown
    # -----------------------------------------------------------------------
    print()
    print("=== Run C: NeverFinishes agent + Budget(steps=3) ===")
    c = await run_agent(
        _NeverFinishes(),
        task="loop forever",
        tools=tools,
        policy=compile_policy(PERMISSIVE),
        budget=Budget(steps=3, duration_seconds=30),
        sinks=(stdout_sink(),),
        on_approval=auto_deny("n/a"),
    )
    print(f"  steps_taken={c.steps_taken}")
    print(f"  error={c.error}")
    print(f"  final_answer={c.final_answer}")

    # -----------------------------------------------------------------------
    # Unknown tool — kernel survives, agent sees an [error] tool message
    # -----------------------------------------------------------------------
    print()
    print("=== Run D: agent asks for a tool that isn't in the ToolSet ===")
    d = await run_agent(
        _OneShot("nonexistent_tool"),
        task="ghost tool",
        tools=tools,
        policy=compile_policy(PERMISSIVE),
        sinks=(stdout_sink(),),
        on_approval=auto_deny("n/a"),
    )
    print(f"  final_answer={d.final_answer}")
    print(f"  steps_taken={d.steps_taken}")
    print()
    print("Notice across the four runs:")
    print("  - Same agent class + same tools; only `policy` and `budget` differ.")
    print("  - The kernel held NOTHING between calls — there is no Runtime.")
    print("  - Budget exhaustion is a structured RunResult.error, not a crash.")
    print("  - Unknown tool produces `action.failed` and the run continues.")


if __name__ == "__main__":
    asyncio.run(main())
