"""
================================================================
EXAMPLE 07 — "Customer support, real-world rules" (ADVANCED)
================================================================

SCENARIO:
    Three customers, three policy outcomes:
      - C-789 (fraud watchlist):  DENY
      - C-456 (medium refund):    APPROVE_REQUIRED (auto-approved here)
      - C-123 (small refund):     ALLOW

    Each is a separate run_agent() call — no shared state between runs.

RUN WITH:
    python examples/07_refund_workflow.py
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from lynx import (
    FinalAnswer,
    Message,
    ToolCall,
    ToolSet,
    auto_approve,
    load_policy_file,
    run_agent,
    stdout_sink,
    tool,
)

CUSTOMERS = {
    "C-123": {"name": "Alice"},
    "C-456": {"name": "Bob"},
    "C-789": {"name": "Carol"},  # on fraud watchlist
}


@tool(reversible=True, scope=("customer:read",))
async def get_customer(customer_id: str) -> dict:
    return CUSTOMERS.get(customer_id, {"error": "not found"})


@tool(reversible=False, scope=("customer:write", "money:transfer"))
async def refund_customer(customer_id: str, amount_usd: float, reason: str) -> dict:
    return {"refunded": amount_usd, "to": customer_id, "reason": reason, "txn": "TXN-XYZ"}


@refund_customer.shadow
async def _refund_shadow(customer_id: str, amount_usd: float, reason: str) -> dict:
    return {"would_refund": amount_usd, "to": customer_id}


class RefundAgent:
    SCENARIOS = {
        "C-789": (5000.0, "customer demanded compensation"),
        "C-456": (200.0, "month-long outage credit"),
        "C-123": (1.63, "1-day outage refund"),
    }

    def __init__(self, customer_id: str):
        amount, reason = self.SCENARIOS[customer_id]
        self._i = 0
        self._plan = [
            ToolCall("get_customer", {"customer_id": customer_id}, call_id="c1"),
            ToolCall(
                "refund_customer",
                {"customer_id": customer_id, "amount_usd": amount, "reason": reason},
                call_id="c2",
            ),
            FinalAnswer(text=f"Processed ticket for {customer_id}."),
        ]

    async def step(self, conv: tuple[Message, ...]):
        a = self._plan[self._i]
        self._i += 1
        return a


async def run_one(customer_id: str, tools, policy) -> None:
    name = CUSTOMERS[customer_id]["name"]
    print(f"\n=== Ticket for {customer_id} ({name}) ===")
    result = await run_agent(
        RefundAgent(customer_id),
        task=f"Process refund for {customer_id}",
        tools=tools,
        policy=policy,
        sinks=(stdout_sink(),),
        on_approval=auto_approve(approver="supervisor-auto"),
    )
    print(f"  Final: {result.final_answer}")
    if result.error:
        print(f"  Error: {result.error}")


async def main() -> None:
    policy_path = Path(__file__).resolve().parent / "policies" / "refund.yaml"
    policy = load_policy_file(policy_path)
    tools = ToolSet.from_functions(get_customer, refund_customer)
    for cid in ("C-789", "C-456", "C-123"):
        await run_one(cid, tools, policy)


if __name__ == "__main__":
    asyncio.run(main())
