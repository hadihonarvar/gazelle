"""Synchronous approval handlers.

When policy returns ``approve_required``, the kernel calls a configured
``ApprovalHandler``. The handler returns an ``ApprovalDecision``. If granted,
the action runs; if denied, the agent sees a denial. No queue. No broker.
No cross-process resume.

Cross-process approval is the user's concern: their handler can talk to
Slack, a database, a webhook — whatever. Lynx is stateless.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Protocol, runtime_checkable

from lynx.core.types import ApprovalDecision, ApprovalRequest

__all__ = [
    "ApprovalHandler",
    "auto_approve",
    "auto_deny",
    "callback_approval",
    "cli_prompt_approval",
]


@runtime_checkable
class ApprovalHandler(Protocol):
    """A callable that decides whether to grant or deny one approval."""

    async def __call__(self, req: ApprovalRequest) -> ApprovalDecision: ...


def auto_approve(approver: str = "auto") -> ApprovalHandler:
    """Approve every request. Useful in tests + lower environments."""

    async def handler(req: ApprovalRequest) -> ApprovalDecision:
        return ApprovalDecision(granted=True, approver=approver)

    return handler


def auto_deny(reason: str) -> ApprovalHandler:
    """Deny every request with the same reason. Safe default."""

    async def handler(req: ApprovalRequest) -> ApprovalDecision:
        return ApprovalDecision(granted=False, approver="system", reason=reason)

    return handler


def cli_prompt_approval(approver: str = "local") -> ApprovalHandler:
    """Prompt on stdin. ``y``/``yes`` → grant; anything else → deny.

    The blocking ``input()`` call runs in a worker thread so the event loop
    keeps spinning — sinks continue to drain and other approvals' timeouts
    keep ticking while a human is thinking.
    """

    async def handler(req: ApprovalRequest) -> ApprovalDecision:
        prompt = (
            f"\n→ APPROVAL REQUIRED\n"
            f"  tool:   {req.request.tool}\n"
            f"  args:   {dict(req.request.args)}\n"
            f"  reason: {req.decision.reason}\n"
            f"Approve? [y/N] "
        )
        ans = (await asyncio.to_thread(input, prompt)).strip().lower()
        granted = ans in {"y", "yes"}
        return ApprovalDecision(
            granted=granted,
            approver=approver,
            reason="" if granted else "denied by local user",
        )

    return handler


def callback_approval(
    fn: Callable[[ApprovalRequest], Awaitable[ApprovalDecision]],
) -> ApprovalHandler:
    """Adapt any async callable into an ``ApprovalHandler``."""
    return fn
