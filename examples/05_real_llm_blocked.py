"""
================================================================
EXAMPLE 05 — "A real AI brain hits the wall" (MORE COMPLEX)
================================================================

SCENARIO:
    Uses a REAL LLM (Claude or GPT) as the driver. Policy still gates.
    Set ANTHROPIC_API_KEY or OPENAI_API_KEY first.

RUN WITH:
    export ANTHROPIC_API_KEY=...    # or OPENAI_API_KEY=...
    python examples/05_real_llm_blocked.py
"""

from __future__ import annotations

import asyncio
import os

from lynx import (
    ToolSet,
    auto_deny,
    compile_policy,
    run_agent,
    stdout_sink,
    tool,
)


@tool(reversible=True, scope=("compute:exec",))
async def shell(cmd: str) -> str:
    """Run a shell command."""
    proc = await asyncio.create_subprocess_shell(
        cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    out, err = await proc.communicate()
    return (out + err).decode().strip() or "(no output)"


POLICY = """
version: 1
defaults: { on_no_match: deny }
rules:
  - id: block-rm-rf-root
    priority: 100
    match: { tool: shell, args.cmd.matches: '^\\s*rm\\s+(-[rRf]+\\s+)+/(\\s|$)' }
    decision: deny
    reason: rm -rf / is hard-blocked
  - id: allow-reads
    priority: 50
    match: { tool: shell, args.cmd.matches: '^(ls|cat|head|tail|find|du|stat)\\s' }
    decision: allow
"""


async def main() -> None:
    tools = ToolSet.from_functions(shell)

    if os.getenv("ANTHROPIC_API_KEY"):
        from lynx.adapters.anthropic_sdk import ClaudeAgent

        agent = ClaudeAgent(
            tools=tools,
            model="claude-opus-4-7",
            system="You are a careful sysadmin. Inspect freely, modify nothing.",
        )
        provider = "Anthropic Claude"
    elif os.getenv("OPENAI_API_KEY"):
        from lynx.adapters.openai_sdk import OpenAIAgent

        agent = OpenAIAgent(
            tools=tools,
            model="gpt-5",
            system="You are a careful sysadmin. Inspect freely, modify nothing.",
        )
        provider = "OpenAI GPT"
    else:
        print("Set ANTHROPIC_API_KEY or OPENAI_API_KEY.")
        return

    print(f"Using: {provider}")
    result = await run_agent(
        agent,
        task="Inspect /tmp without modifying anything; summarize when done.",
        tools=tools,
        policy=compile_policy(POLICY),
        sinks=(stdout_sink(),),
        on_approval=auto_deny("not configured"),
    )
    print()
    print(f"Final: {result.final_answer}")


if __name__ == "__main__":
    asyncio.run(main())
