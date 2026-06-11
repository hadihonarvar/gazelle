"""
================================================================
EXAMPLE 14 — "All three transform ops: set / append / delete" (ADVANCED)
================================================================

SCENARIO:
    The `transform` verdict has three operations — only `append` is shown
    in 08_sql_transform. This example exercises all three in one policy:

      - SET    : replace a value entirely
      - APPEND : string-concatenate (the SQL-injection-of-policy classic)
      - DELETE : drop a key from args

    Each operation rewrites the args BEFORE the tool runs; the tool sees
    the rewritten dict.

WHAT THIS EXAMPLE SHOWS:
    - `decision: transform` with `set: <literal>`
    - `decision: transform` with `append: " ..."`
    - `decision: transform` with `delete: true`
    - The transform `jsonpath` is NOT real JSONPath — only `$.args.<key>`
      top-level rewrites are supported

RUN WITH:
    python examples/14_transform_ops.py
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

# What the tool actually sees becomes the demo's evidence:
seen_args: list[dict] = []


@tool(reversible=True, scope=("db:write",))
async def db_update(table: str, sql: str = "", debug: bool = False) -> str:
    """Record what we were called with so the demo can prove the rewrite."""
    seen_args.append({"table": table, "sql": sql, "debug": debug})
    return f"executed against {table}"


POLICY = """
version: 1
defaults: { on_no_match: deny }
rules:
  # 1. SET: any call to db_update against 'audit_log' is forcibly redirected
  #    to a quarantine table.
  - id: quarantine-audit-log-writes
    priority: 100
    match:
      tool: db_update
      args.table: audit_log
    decision: transform
    transform:
      jsonpath: "$.args.table"
      set: "audit_log_quarantine"
    reason: "Writes to audit_log are redirected to a quarantine table."

  # 2. APPEND: any UPDATE/DELETE sql gets a tenant filter appended.
  - id: scope-mutations-to-tenant
    priority: 90
    match:
      tool: db_update
      args.sql.matches: '(?i)^(UPDATE|DELETE)\\b'
    decision: transform
    transform:
      jsonpath: "$.args.sql"
      append: " AND tenant_id = 'TENANT-ALICE'"
    reason: "Tenant isolation enforced on UPDATE/DELETE."

  # 3. DELETE: the `debug` flag is dropped before the tool runs.
  - id: strip-debug-flag
    priority: 80
    match: { tool: db_update, args.debug: true }
    decision: transform
    transform:
      jsonpath: "$.args.debug"
      delete: true
    reason: "Debug flag stripped in policy-gated execution."

  - id: fallback-allow-db-update
    priority: 10
    match: { tool: db_update }
    decision: allow
"""


class _ScriptedAgent:
    def __init__(self):
        self._plan = [
            # SET: redirects table audit_log -> audit_log_quarantine
            ToolCall("db_update", {"table": "audit_log", "sql": "INSERT ..."}, call_id="c1"),
            # APPEND: WHERE tenant filter appended to sql
            ToolCall(
                "db_update",
                {"table": "orders", "sql": "UPDATE orders SET status='shipped'"},
                call_id="c2",
            ),
            # DELETE: debug=True stripped before call
            ToolCall(
                "db_update",
                {"table": "orders", "sql": "SELECT 1", "debug": True},
                call_id="c3",
            ),
            FinalAnswer(text="three operations applied"),
        ]
        self._i = 0

    async def step(self, conv: tuple[Message, ...]):
        action = self._plan[self._i]
        self._i += 1
        return action


async def main() -> None:
    result = await run_agent(
        _ScriptedAgent(),
        task="exercise all three transform ops",
        tools=ToolSet.from_functions(db_update),
        policy=compile_policy(POLICY),
        sinks=(stdout_sink(),),
        on_approval=auto_deny("not used"),
    )
    print()
    print(f"Final answer: {result.final_answer}")
    print()
    print("Args the tool actually received (proves the rewrite happened):")
    for i, args in enumerate(seen_args, start=1):
        print(f"  call {i}: {args}")
    print()
    print("Expected:")
    print("  call 1: table redirected to 'audit_log_quarantine'  (SET)")
    print("  call 2: sql has ' AND tenant_id = ...' suffix       (APPEND)")
    print("  call 3: no 'debug' key in args                      (DELETE)")


if __name__ == "__main__":
    asyncio.run(main())
