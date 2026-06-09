"""Customer-support refund agent demo.

Demonstrates approve_required (medium refunds) and deny (fraud watchlist + over cap).
The audit log produced is exactly what SOC 2 / finance auditors want.

Two modes:
    DEFAULT: scripted agent — three customers with three different outcomes.
             Runs offline, no API key needed.

    With ANTHROPIC_API_KEY set: swap in ClaudeAgent and let the LLM decide.

Run with:
    python examples/refund_agent.py
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

from gazelle import FinalAnswer, Message, ToolCall, runtime, tool

# ---------------------------------------------------------------------------
# Fake database (in real life: Stripe + your CRM)
# ---------------------------------------------------------------------------

CUSTOMERS = {
    "C-123": {"name": "Alice",  "plan": "Pro",   "monthly_usd": 49},
    "C-456": {"name": "Bob",    "plan": "Team",  "monthly_usd": 199},
    "C-789": {"name": "Carol",  "plan": "Pro",   "monthly_usd": 49},   # on fraud watchlist
}

# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@tool(cost="low", reversible=True, scope=["customer:read"])
async def get_customer(customer_id: str) -> dict:
    """Look up a customer profile."""
    return CUSTOMERS.get(customer_id, {"error": "not found"})


@tool(cost="medium", reversible=False, scope=["customer:write", "money:transfer"])
async def refund_customer(customer_id: str, amount_usd: float, reason: str) -> dict:
    """Issue a refund. IRREVERSIBLE — policy gates this hard."""
    # In real life: stripe.Refund.create(...)
    return {"refunded": amount_usd, "to": customer_id, "reason": reason, "txn": "TXN-XYZ"}


@refund_customer.shadow
async def _refund_shadow(customer_id: str, amount_usd: float, reason: str) -> dict:
    return {
        "would_refund": amount_usd,
        "to": customer_id,
        "reason": reason,
        "note": "DRY RUN — no money moved",
    }


# ---------------------------------------------------------------------------
# A scripted agent — replace with ClaudeAgent for a real demo.
# ---------------------------------------------------------------------------


class ScriptedRefundAgent:
    """Three customers, three intended refunds. Each tests a different rule."""

    SCENARIOS = {
        "C-789": (5000.0, "customer demanded compensation"),   # fraud watchlist → DENY
        "C-456": (200.0, "month-long outage credit"),          # medium → APPROVE_REQUIRED
        "C-123": (1.63, "1-day outage"),                       # small → ALLOW
    }

    def __init__(self, customer_id: str):
        self.customer_id = customer_id
        amount, reason = self.SCENARIOS[customer_id]
        self._plan = [
            ToolCall("get_customer", {"customer_id": customer_id}, call_id="c1"),
            ToolCall("refund_customer",
                     {"customer_id": customer_id, "amount_usd": amount, "reason": reason},
                     call_id="c2"),
            FinalAnswer(text=f"Processed ticket for {customer_id}."),
        ]
        self._i = 0

    async def step(self, conversation: list[Message]):
        a = self._plan[self._i]
        self._i += 1
        return a


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def run_one(customer_id: str) -> None:
    print(f"\n=== Processing ticket for {customer_id} ({CUSTOMERS[customer_id]['name']}) ===")
    policy = Path(__file__).resolve().parent / "refund-policy.yaml"
    result = await runtime.run(
        agent=ScriptedRefundAgent(customer_id),
        task=f"Process refund ticket for customer {customer_id}",
        policy=str(policy),
        principal={"kind": "service", "id": "support-bot"},
        environment="prod",
    )
    print(f"  run_id:  {result.run_id}")
    print(f"  status:  {result.status}")
    if result.paused_approval_id:
        print(f"  PAUSED:  gazelle approve {result.paused_approval_id}")
    print(f"  final:   {result.final_answer}")
    print(f"  trace:   gazelle trace {result.run_id}")


async def main() -> None:
    print("Gazelle refund-agent demo. No real money moves.")
    if os.getenv("ANTHROPIC_API_KEY"):
        print("(ANTHROPIC_API_KEY found — for a real LLM demo, swap in ClaudeAgent.)")
    for cid in ("C-789", "C-456", "C-123"):
        await run_one(cid)


if __name__ == "__main__":
    asyncio.run(main())
