"""
================================================================
EXAMPLE 16 — "Cross-process approval pattern (mocked)" (ADVANCED)
================================================================

SCENARIO:
    The FAQ + integration cookbook show the Slack approval pattern as
    pseudocode. This example demonstrates the *runtime contract* with a
    real asyncio mock: the handler blocks on an `asyncio.Event`, and a
    sidecar task simulates a human clicking "approve" half a second later.

    The `run_agent` loop blocks on the handler exactly as it would for a
    real Slack handler that's awaiting a webhook. The mediator enforces
    the rule's `timeout_seconds`, so a hanging handler can never hang the
    run forever.

WHAT THIS EXAMPLE SHOWS:
    - `callback_approval(fn)` wrapping any async callable
    - The handler waiting on an out-of-band signal (`asyncio.Event`)
    - `timeout_seconds` enforcement (the rule says 10s; the human clicks
      in 0.5s, so the run succeeds; flip the sleep and the run denies)
    - `approval.requested` / `approval.granted` audit events

RUN WITH:
    python examples/16_async_approval.py
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from lynx import (
    ApprovalDecision,
    ApprovalRequest,
    FinalAnswer,
    Message,
    ToolCall,
    ToolSet,
    callback_approval,
    callback_sink,
    compile_policy,
    run_agent,
    stdout_sink,
    tool,
)


@tool(reversible=False, scope=("money:transfer",))
async def issue_refund(customer_id: str, amount_usd: float) -> dict:
    return {"refunded": amount_usd, "to": customer_id}


@issue_refund.shadow
async def _refund_shadow(customer_id: str, amount_usd: float) -> dict:
    return {"would_refund": amount_usd}


POLICY = """
version: 1
defaults: { on_no_match: deny }
rules:
  - id: refunds-need-approval
    priority: 100
    match: { tool: issue_refund }
    decision: approve_required
    approvers: ["sre-oncall"]
    timeout_seconds: 10
    reason: "Refunds require a human signoff."
"""


# ---------------------------------------------------------------------------
# Mocked "Slack" — a queue the bot reads from + an asyncio.Event the human
# trips when they click. In production this is a webhook / Slack reaction /
# whatever your system uses.
# ---------------------------------------------------------------------------


@dataclass
class _PendingApproval:
    decided: asyncio.Event
    granted: bool = False
    approver: str = ""


_pending: dict[str, _PendingApproval] = {}


async def slack_like_handler(req: ApprovalRequest) -> ApprovalDecision:
    """Real-world equivalent: post a message to Slack, return after the
    button-click webhook delivers a decision."""
    pa = _PendingApproval(decided=asyncio.Event())
    _pending[req.correlation_id] = pa

    print(f"  [bot]  posting approval for {req.request.tool!r} args={dict(req.request.args)}")
    print("  [bot]  waiting for human (timeout enforced by the mediator)")

    # The mediator wraps this `await` in `asyncio.wait_for(..., timeout_seconds)`.
    # If the human takes too long, the wait_for raises and we never reach the
    # ApprovalDecision below — the mediator converts that into a deny.
    await pa.decided.wait()

    return ApprovalDecision(
        granted=pa.granted,
        approver=pa.approver,
        reason="" if pa.granted else "human refused",
    )


async def fake_human_clicking(delay_seconds: float, approve: bool):
    """Sidecar task: pretend the on-call clicks the Slack button."""
    await asyncio.sleep(delay_seconds)
    if not _pending:
        return
    cid, pa = next(iter(_pending.items()))
    pa.granted = approve
    pa.approver = "alice@oncall"
    pa.decided.set()
    print(f"  [human] clicked {'APPROVE' if approve else 'DENY'} after {delay_seconds}s")
    del _pending[cid]


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------


class _Agent:
    def __init__(self):
        self._plan = [
            ToolCall("issue_refund", {"customer_id": "C-42", "amount_usd": 75.0}, call_id="c1"),
            FinalAnswer(text="Refund processed."),
        ]
        self._i = 0

    async def step(self, conv: tuple[Message, ...]):
        a = self._plan[self._i]
        self._i += 1
        return a


async def main() -> None:
    events: list[str] = []

    async def watch(event):
        if event.kind.startswith("approval."):
            events.append(event.kind)

    # Kick off the "human" alongside the run. They'll click APPROVE in 0.5s.
    # Try `delay_seconds=15, approve=False` to watch the 10s timeout convert
    # to an automatic deny without anyone clicking anything.
    human = asyncio.create_task(fake_human_clicking(delay_seconds=0.5, approve=True))

    result = await run_agent(
        _Agent(),
        task="approve a refund",
        tools=ToolSet.from_functions(issue_refund),
        policy=compile_policy(POLICY),
        sinks=(stdout_sink(), callback_sink(watch)),
        on_approval=callback_approval(slack_like_handler),
    )

    await human

    print()
    print(f"Final answer: {result.final_answer}")
    print(f"Approval events observed: {events}")
    print()
    print("Try this:")
    print("  - Change `delay_seconds` above to 15 (greater than the rule's 10s")
    print("    timeout). The mediator will auto-deny without anyone clicking.")


if __name__ == "__main__":
    asyncio.run(main())
