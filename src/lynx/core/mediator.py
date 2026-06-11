"""Action Mediator (PEP) — v2.

Pure async function. Takes a request, decision, the toolset, and an approval
handler. Returns an ``ActionResult``. No globals. No store. No broker.
"""

from __future__ import annotations

import asyncio
import time
import traceback
from collections.abc import Mapping
from typing import TYPE_CHECKING

from lynx.core.types import (
    ActionRequest,
    ActionResult,
    ApprovalRequest,
    Decision,
    ToolSet,
    Verdict,
)

if TYPE_CHECKING:
    from lynx.approvals import ApprovalHandler

__all__ = ["mediate"]


# Default cap for an approve_required step when the rule doesn't specify one.
# Picks an aggressive value because hanging-forever is the worst outcome.
_DEFAULT_APPROVAL_TIMEOUT_SECONDS = 1800


async def mediate(
    request: ActionRequest,
    decision: Decision,
    tools: ToolSet,
    on_approval: ApprovalHandler,
) -> ActionResult:
    """Dispatch one action under the verdict's rules.

    Behavior by verdict:
      * ALLOW             → call the real tool with request.args
      * DENY              → return a failed ActionResult with the deny reason
      * DRY_RUN           → call the shadow function; return preview
      * APPROVE_REQUIRED  → call on_approval(...) with the rule's timeout;
                            on grant → execute as ALLOW; on deny / timeout /
                            handler exception → return a failed ActionResult.
      * TRANSFORM         → call the real tool with decision.transform_args
                            (which must be a Mapping)

    On a tool raising an exception, the result has ok=False with a structured
    error string. The kernel never crashes due to a misbehaving tool, a
    misbehaving approval handler, or a malformed transform.
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
        timeout = decision.timeout_seconds or _DEFAULT_APPROVAL_TIMEOUT_SECONDS
        try:
            approval = await asyncio.wait_for(on_approval(req), timeout=timeout)
        except TimeoutError:
            return ActionResult(
                ok=False,
                error=f"denied: approval handler timed out after {timeout}s",
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            return ActionResult(
                ok=False,
                error=f"denied: approval handler raised {type(exc).__name__}: {exc}",
            )
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
        if not isinstance(decision.transform_args, Mapping):
            # Compile-time validation should make this unreachable for YAML
            # rules; Python rules can still produce this footgun.
            return ActionResult(
                ok=False,
                error=(
                    "transform decision missing transform_args (must be a Mapping). "
                    "Refusing to fall through to original args."
                ),
            )
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
    override_args: Mapping[str, str] | Mapping[str, object] | None = None,
) -> ActionResult:
    tool = tools.get(request.tool)
    args: Mapping[str, object] = (
        override_args if override_args is not None else dict(request.args)
    )
    started = time.perf_counter()
    try:
        value = await tool.fn(**args)
        return ActionResult(
            ok=True,
            value=value,
            duration_ms=int((time.perf_counter() - started) * 1000),
        )
    except asyncio.CancelledError:
        raise
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
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        return ActionResult(
            ok=False,
            error=f"{type(exc).__name__}: {exc}",
            duration_ms=int((time.perf_counter() - started) * 1000),
        )
