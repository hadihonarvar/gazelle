"""
================================================================
EXAMPLE 02 — "Block the catastrophic command" (SIMPLE)
================================================================

SCENARIO:
    The assistant proposes `rm -rf /` (somehow). Without Lynx that runs.
    With Lynx, one YAML rule denies it at the kernel — the syscall never
    happens. The denial is fed back to the agent, which can retry safer.

RUN WITH:
    python examples/02_block_dangerous.py
"""

from __future__ import annotations

import asyncio

from lynx import (
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


@tool(reversible=True, scope=("compute:exec",))
async def shell(cmd: str) -> str:
    """Run a shell command. Marked reversible only for demo simplicity."""
    proc = await asyncio.create_subprocess_shell(
        cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    out, err = await proc.communicate()
    return (out + err).decode().strip() or "(no output)"


POLICY = """
version: 1
defaults: { on_no_match: allow }
rules:
  - id: block-rm-rf-root
    match:
      tool: shell
      args.cmd.matches: '^\\s*rm\\s+(-[rRf]+\\s+)+/(\\s|$)'
    decision: deny
    reason: "rm -rf / is hard-blocked"
"""


class CarelessAgent:
    """Tries one safe command, one dangerous one, then finishes."""

    def __init__(self):
        self._i = 0
        self._plan = [
            ToolCall(tool="shell", args={"cmd": "ls /tmp"}, call_id="c1"),
            ToolCall(tool="shell", args={"cmd": "rm -rf /"}, call_id="c2"),
            FinalAnswer(text="Tried safe + dangerous; dangerous was blocked."),
        ]

    async def step(self, conv: tuple[Message, ...]):
        action = self._plan[self._i]
        self._i += 1
        return action


async def main() -> None:
    result = await run_agent(
        CarelessAgent(),
        task="Demonstrate denial",
        tools=ToolSet.from_functions(shell),
        policy=compile_policy(POLICY),
        sinks=(stdout_sink(),),
        on_approval=auto_deny("no"),
    )
    print()
    print(f"Final: {result.final_answer}")


if __name__ == "__main__":
    asyncio.run(main())
