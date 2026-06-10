"""
================================================================
EXAMPLE 08 — "Auto-fix SQL queries" (ADVANCED)
================================================================

SCENARIO:
    Multi-tenant SaaS. The assistant runs SQL. We want every UPDATE/DELETE
    to be scoped to the current tenant. Policy's TRANSFORM verdict rewrites
    the SQL transparently before it executes.

RUN WITH:
    python examples/08_sql_transform.py
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
    load_policy_file,
    run_agent,
    stdout_sink,
    tool,
)


@tool(reversible=True, scope=("db:read", "db:write"))
async def sql_exec(sql: str) -> dict:
    """Pretend SQL executor — echoes the query that would run."""
    return {"executed": sql, "rows_affected": 1}


class SQLAgent:
    def __init__(self):
        self._i = 0
        self._plan = [
            ToolCall("sql_exec", {"sql": "SELECT * FROM users LIMIT 10"}, call_id="c1"),
            ToolCall("sql_exec", {"sql": "DELETE FROM users"}, call_id="c2"),
            ToolCall(
                "sql_exec", {"sql": "UPDATE users SET active = 0 WHERE id = 42"}, call_id="c3"
            ),
            FinalAnswer(text="SELECT + bulk-DELETE-denied + scoped-UPDATE."),
        ]

    async def step(self, conv: tuple[Message, ...]):
        a = self._plan[self._i]
        self._i += 1
        return a


async def main() -> None:
    policy_path = Path(__file__).resolve().parent / "policies" / "sql-transform.yaml"
    result = await run_agent(
        SQLAgent(),
        task="Demonstrate SELECT, bulk-DELETE-denied, scoped-UPDATE",
        tools=ToolSet.from_functions(sql_exec),
        policy=load_policy_file(policy_path),
        sinks=(stdout_sink(),),
        on_approval=auto_deny("not used"),
    )
    print()
    print(f"Final: {result.final_answer}")


if __name__ == "__main__":
    asyncio.run(main())
