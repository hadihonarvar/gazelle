"""
================================================================
EXAMPLE 20 — "MCP tools via async-context-manager" (INTEGRATIONS)
================================================================

SCENARIO:
    The MCP adapter (`lynx.adapters.mcp.mcp_tools`) connects to an MCP
    server, discovers its tools, and yields them as an immutable
    `ToolSet`. The server runs as a child stdio process for the lifetime
    of the `async with` block — exit the block and the child is
    cleanly torn down.

    Defaults are conservative: every discovered MCP tool is marked
    `reversible=False` with scope `("mcp:tool",)`, so your policy must
    explicitly allow them before they can run.

WHAT THIS EXAMPLE SHOWS:
    - `async with mcp_tools(command) as remote: ...` pattern
    - Combining remote MCP tools with local Lynx-decorated tools via
      `.union(...)`
    - The policy-side allow rule that lets `mcp:tool`-scoped calls go
      through

REQUIRES:
    pip install lynx-agent[mcp]
    plus an MCP server to talk to. The simplest is the official
    filesystem server:
      pip install mcp-server-filesystem
    or any other stdio MCP server you have.

RUN WITH:
    python examples/20_mcp_tools.py /path/to/some/workspace
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

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

try:
    from lynx.adapters.mcp import mcp_tools
except ImportError as exc:
    sys.exit(f"MCP adapter not importable. Install with: pip install lynx-agent[mcp]\n({exc})")


# A local Lynx tool you'd union with the MCP server's tools.
@tool(reversible=True, scope=("compute:read",))
async def note(message: str) -> str:
    return f"note recorded: {message}"


# Permissive demo policy — real users should constrain MCP tools by name.
POLICY = """
version: 1
defaults: { on_no_match: deny }
rules:
  - id: allow-mcp-reads
    match: { declared.scope.contains: "mcp:tool" }
    decision: allow
  - id: allow-local-notes
    match: { tool: note }
    decision: allow
"""


class _ScriptedAgent:
    def __init__(self, mcp_tool_names: list[str]):
        self._plan: list = [
            ToolCall("note", {"message": "starting MCP demo"}, call_id="c0"),
        ]
        if mcp_tool_names:
            first = mcp_tool_names[0]
            self._plan.append(
                ToolCall(first, {}, call_id="c1"),  # call with no args; will likely fail
            )
        self._plan.append(FinalAnswer(text="MCP demo complete"))
        self._i = 0

    async def step(self, conv: tuple[Message, ...]):
        a = self._plan[self._i]
        self._i += 1
        return a


async def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python examples/20_mcp_tools.py <command>")
        print()
        print("Examples:")
        print("  # The official filesystem MCP server:")
        print(
            "  python examples/20_mcp_tools.py 'npx -y @modelcontextprotocol/server-filesystem .'"
        )
        print()
        print("  # Or any other stdio MCP server you have installed:")
        print("  python examples/20_mcp_tools.py 'python -m my_mcp_server'")
        return

    command = " ".join(sys.argv[1:])
    print(f"Connecting to MCP server: {command!r}")
    print()

    async with mcp_tools(command) as remote:
        print(f"Discovered {len(remote)} remote tools: {list(remote.names())[:5]}...")

        # Union with the local toolset.
        tools = remote.union(ToolSet.from_functions(note))

        result = await run_agent(
            _ScriptedAgent(list(remote.names())),
            task="MCP demo",
            tools=tools,
            policy=compile_policy(POLICY),
            sinks=(stdout_sink(),),
            on_approval=auto_deny("not configured"),
            workspace=str(Path.cwd()),
        )
        print()
        print(f"Final answer: {result.final_answer}")
        print()
        print("Notice:")
        print("  - The MCP server child process is kept alive by the `async with`")
        print("  - On exit, the stdio pipes + child process are cleanly torn down")
        print("  - Every MCP tool defaulted to `reversible=False` + scope 'mcp:tool'")
        print("    — that's why the policy needs an explicit allow rule")


if __name__ == "__main__":
    asyncio.run(main())
