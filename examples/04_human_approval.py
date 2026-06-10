"""
================================================================
EXAMPLE 04 — "Big decisions need a human" (MORE COMPLEX)
================================================================

SCENARIO:
    The bot wants to wire money. The policy says: approve_required. The
    handler is called synchronously — `cli_prompt_approval` shows the
    proposal on stdin and waits for y/N.

    There is NO cross-process resume. The run blocks on the handler. If
    you need cross-process approval (Slack button), write your handler
    to do that wait — Lynx stays stateless.

RUN WITH:
    python examples/04_human_approval.py
    # type "y" + Enter to approve, anything else to deny
"""

from __future__ import annotations

import asyncio

from lynx import (
    FinalAnswer,
    Message,
    ToolCall,
    ToolSet,
    cli_prompt_approval,
    compile_policy,
    run_agent,
    stdout_sink,
    tool,
)


@tool(reversible=False, scope=("money:transfer",))
async def wire_transfer(to: str, amount_usd: float, memo: str) -> dict:
    """Wire money."""
    return {"to": to, "amount_usd": amount_usd, "memo": memo, "confirmation": "WIRE-1"}


@wire_transfer.shadow
async def _wire_shadow(to: str, amount_usd: float, memo: str) -> dict:
    return {"would_wire": amount_usd, "to": to, "memo": memo}


POLICY = """
version: 1
defaults: { on_no_match: deny }
rules:
  - id: wires-need-approval
    match: { tool: wire_transfer }
    decision: approve_required
"""


class WireAgent:
    """Conversation-aware: stops once it sees the result."""

    async def step(self, conv: tuple[Message, ...]):
        for m in conv:
            if m.role == "tool" and m.name == "wire_transfer":
                return FinalAnswer(text=f"Done. {m.content}")
        return ToolCall(
            tool="wire_transfer",
            args={
                "to": "ACME Corp",
                "amount_usd": 200.00,
                "memo": "Invoice INV-2026-06-001",
            },
            call_id="c1",
        )


async def main() -> None:
    result = await run_agent(
        WireAgent(),
        task="Pay the ACME invoice",
        tools=ToolSet.from_functions(wire_transfer),
        policy=compile_policy(POLICY),
        sinks=(stdout_sink(),),
        on_approval=cli_prompt_approval(approver="local-user"),
    )
    print()
    print(f"Final: {result.final_answer}")
    print(f"Error: {result.error}")


if __name__ == "__main__":
    asyncio.run(main())
