"""
================================================================
EXAMPLE 17 — "Built-in shadow helpers" (ADVANCED)
================================================================

SCENARIO:
    Examples 03 and 06 write their own `.shadow` twin inline. For common
    side-effect categories (filesystem, HTTP, shell, SQL), Lynx ships
    pre-built shadow functions you can attach directly to your tool with
    `@your_tool.shadow`.

WHAT THIS EXAMPLE SHOWS:
    - `write_file_shadow`        - structural preview of a write
    - `shell_shadow`             - parses the command, identifies probable
                                   destructive tokens + network egress
    - `http_shadow`              - parses URL + headers (auth headers
                                   redacted); flags destructive methods
    - `sql_shadow`               - identifies the operation, tables, and
                                   warns on UPDATE/DELETE without WHERE

    Each helper is a pure function returning a dict. You can plug them in
    via `@tool.shadow` directly, or wrap them if you want to customize.

RUN WITH:
    python examples/17_shadow_helpers.py
"""

from __future__ import annotations

import asyncio
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
from lynx.shadows.filesystem import write_file_shadow
from lynx.shadows.http import http_shadow
from lynx.shadows.shell import shell_shadow
from lynx.shadows.sql import sql_shadow

# ---------------------------------------------------------------------------
# Tools with their .shadow set to the pre-built helpers
# ---------------------------------------------------------------------------


@tool(reversible=False, scope=("filesystem:write",))
async def write_file(path: str, content: str) -> str:
    Path(path).write_text(content)
    return f"wrote {path}"


@write_file.shadow
async def _write_file_shadow(path: str, content: str):
    return await write_file_shadow(path=path, content=content)


@tool(reversible=False, scope=("compute:exec",))
async def shell(cmd: str) -> str:
    return f"would exec {cmd}"


@shell.shadow
async def _shell_shadow(cmd: str):
    return await shell_shadow(cmd=cmd)


@tool(reversible=False, scope=("net:egress",))
async def http_request(method: str, url: str, headers: dict | None = None, body: str = "") -> str:
    return f"would {method} {url}"


@http_request.shadow
async def _http_request_shadow(method: str, url: str, headers: dict | None = None, body: str = ""):
    return await http_shadow(method=method, url=url, headers=headers, body=body)


@tool(reversible=False, scope=("db:write",))
async def sql_exec(query: str) -> str:
    return f"would execute {query}"


@sql_exec.shadow
async def _sql_exec_shadow(query: str):
    return await sql_shadow(query=query)


# ---------------------------------------------------------------------------
# Policy: route everything to dry_run so all four shadows run
# ---------------------------------------------------------------------------


POLICY = """
version: 1
defaults: { on_no_match: deny }
rules:
  - id: dry-run-all
    match: { declared.reversible: false }
    decision: dry_run
"""


class _Agent:
    def __init__(self):
        self._plan = [
            ToolCall("write_file", {"path": "demo.txt", "content": "hello world"}, call_id="c1"),
            ToolCall("shell", {"cmd": "rm -rf /tmp/junk; curl https://api.example.com"}, call_id="c2"),
            ToolCall(
                "http_request",
                {
                    "method": "POST",
                    "url": "https://api.example.com/charge",
                    "headers": {"Authorization": "Bearer SECRET", "X-Trace": "abc"},
                    "body": '{"amount": 100}',
                },
                call_id="c3",
            ),
            ToolCall(
                "sql_exec",
                {"query": "DELETE FROM users WHERE email LIKE '%@test.com%'"},
                call_id="c4",
            ),
            FinalAnswer(text="four shadows demonstrated"),
        ]
        self._i = 0

    async def step(self, conv: tuple[Message, ...]):
        a = self._plan[self._i]
        self._i += 1
        return a


async def main() -> None:
    result = await run_agent(
        _Agent(),
        task="exercise four pre-built shadows",
        tools=ToolSet.from_functions(write_file, shell, http_request, sql_exec),
        policy=compile_policy(POLICY),
        sinks=(stdout_sink(),),
        on_approval=auto_deny("not used"),
    )
    print()
    print(f"Final answer: {result.final_answer}")
    print()
    print("Notice in the audit above:")
    print("  - write_file_shadow:  reported `would_write` + content size")
    print("  - shell_shadow:        flagged `destructive_tokens=[rm]` + "
          "`network_egress=True`")
    print("  - http_shadow:         `Authorization` header was redacted")
    print("  - sql_shadow:          warned about DELETE without restrictive WHERE")
    print()
    print("All four are real side-effect previews — no file written, no HTTP")
    print("call made, no SQL executed.")


if __name__ == "__main__":
    asyncio.run(main())
