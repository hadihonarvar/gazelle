"""Action Mediator (PEP) — v2.

Pure async function. Takes a request, decision, the toolset, and an approval
handler. Returns an ``ActionResult``. No globals. No store. No broker.
"""

from __future__ import annotations

import time
import traceback

from lynx.core.types import (
    ActionRequest,
    ActionResult,
    ApprovalRequest,
    Decision,
    ToolSet,
    Verdict,
)

# ApprovalHandler is forward-declared here as a runtime-checkable Protocol-ish
# Callable. We import the type lazily to avoid a circular dependency.

__all__ = ["mediate"]


async def mediate(
    request: ActionRequest,
    decision: Decision,
    tools: ToolSet,
    on_approval: object,  # ApprovalHandler — see lynx.approvals
) -> ActionResult:
    """Dispatch one action under the verdict's rules.

    Behavior by verdict:
      * ALLOW             → call the real tool with request.args
      * DENY              → return a failed ActionResult with the deny reason
      * DRY_RUN           → call the shadow function; return preview
      * APPROVE_REQUIRED  → call on_approval(...) synchronously; act accordingly
      * TRANSFORM         → call the real tool with decision.transform_args

    On a tool raising an exception, the result has ok=False with a structured
    error string. The kernel never crashes due to a misbehaving tool.
    """
    if decision.verdict == Verdict.DENY:
        return ActionResult(
            ok=False, error=f"denied: {decision.reason or 'Policy denied this action'}"
        )

    if decision.verdict == Verdict.APPROVE_REQUIRED:
        req = ApprovalRequest(
            request=request,
            decision=decision,
            correlation_id=request.context.correlation_id,
        )
        approval = await on_approval(req)  # type: ignore[misc]
        if not approval.granted:
            return ActionResult(
                ok=False,
                error=(
                    f"denied: approval refused by {approval.approver}"
                    + (f" — {approval.reason}" if approval.reason else "")
                ),
            )
        # Granted — fall through and execute as if ALLOW
        return await _execute_real(request, tools)

    if decision.verdict == Verdict.DRY_RUN:
        return await _execute_shadow(request, tools)

    if decision.verdict == Verdict.TRANSFORM:
        return await _execute_real(request, tools, override_args=decision.transform_args)

    # ALLOW
    return await _execute_real(request, tools)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _execute_real(
    request: ActionRequest,
    tools: ToolSet,
    *,
    override_args: object | None = None,
) -> ActionResult:
    tool = tools.get(request.tool)
    args = override_args if override_args is not None else dict(request.args)
    started = time.perf_counter()
    try:
        value = await tool.fn(**args)  # type: ignore[misc]
        return ActionResult(
            ok=True,
            value=value,
            duration_ms=int((time.perf_counter() - started) * 1000),
        )
    except Exception as exc:
        return ActionResult(
            ok=False,
            error=f"{type(exc).__name__}: {exc}\n{traceback.format_exc()[-500:]}",
            duration_ms=int((time.perf_counter() - started) * 1000),
        )


async def _execute_shadow(request: ActionRequest, tools: ToolSet) -> ActionResult:
    tool = tools.get(request.tool)
    if tool.shadow_fn is None:
        return ActionResult(
            ok=False,
            error=f"tool {request.tool!r} has no shadow; cannot dry-run",
        )
    started = time.perf_counter()
    try:
        value = await tool.shadow_fn(**dict(request.args))
        return ActionResult(
            ok=True,
            value={"dry_run": True, "preview": value},
            duration_ms=int((time.perf_counter() - started) * 1000),
        )
    except Exception as exc:
        return ActionResult(
            ok=False,
            error=f"{type(exc).__name__}: {exc}",
            duration_ms=int((time.perf_counter() - started) * 1000),
        )
