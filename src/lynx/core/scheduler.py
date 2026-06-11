"""Scheduler — v2.

A single pure-ish async function: ``run_agent``. No classes. No globals.
The agent step loop with policy enforcement and streaming audit events.
"""

from __future__ import annotations

import asyncio
import sys
import time
from collections.abc import Sequence
from typing import TYPE_CHECKING

from lynx.core.mediator import mediate
from lynx.core.policy import PolicyBundle, evaluate
from lynx.core.types import (
    ActionRequest,
    AuditEvent,
    Budget,
    ExecutionContext,
    FinalAnswer,
    Message,
    Principal,
    RunResult,
    ToolCall,
    ToolSet,
    new_correlation_id,
    now_utc,
)

if TYPE_CHECKING:
    from lynx.approvals import ApprovalHandler
    from lynx.sdk import Agent
    from lynx.sinks import Sink


__all__ = ["run_agent"]


async def run_agent(
    agent: Agent,
    task: str,
    *,
    tools: ToolSet,
    policy: PolicyBundle,
    sinks: Sequence[Sink] = (),
    on_approval: ApprovalHandler | None = None,
    budget: Budget = Budget(steps=50, duration_seconds=600),
    principal: Principal = Principal(kind="user", id="anonymous"),
    environment: str = "dev",
    workspace: str = ".",
    correlation_id: str | None = None,
) -> RunResult:
    """Run an agent through one task. Stateless.

    Args:
        agent:        Anything implementing ``async step(conversation) -> ToolCall | FinalAnswer``.
        task:         The user's goal — becomes the first user Message.
        tools:        Immutable ToolSet of @tool-decorated functions.
        policy:       Compiled PolicyBundle (use compile_policy / load_policy_file).
        sinks:        Iterable of Sink callables. Each event is fanned out.
        on_approval:  Sync handler for APPROVE_REQUIRED. Defaults to auto-deny.
        budget:       Hard caps on steps / duration / tokens.
        principal:    Who the agent is acting on behalf of.
        environment:  e.g. "dev" / "staging" / "prod" — policy can match on this.
        workspace:    Filesystem context the agent works in.
        correlation_id: Optional override; new UUID4 generated if None.

    Returns:
        ``RunResult`` with final_answer, error, steps_taken, correlation_id, bundle_id.

    No state is held after this function returns. Sinks are called as events
    happen and never buffered. The conversation is freed at function exit.
    """
    from lynx.approvals import auto_deny  # local import to avoid cycle

    on_approval = on_approval or auto_deny("no on_approval handler configured")
    cid = correlation_id or new_correlation_id()
    sinks_tuple: tuple[Sink, ...] = tuple(sinks)

    started_monotonic = time.monotonic()
    seq_counter = 0

    async def emit(kind: str, body_payload: dict) -> int:
        nonlocal seq_counter
        event = AuditEvent(
            correlation_id=cid,
            bundle_id=policy.id,
            seq=seq_counter,
            kind=kind,
            timestamp=now_utc(),
            body=body_payload,
        )
        seq_counter += 1
        if sinks_tuple:
            results = await asyncio.gather(
                *(s(event) for s in sinks_tuple),
                return_exceptions=True,
            )
            for sink_obj, outcome in zip(sinks_tuple, results, strict=True):
                if isinstance(outcome, BaseException):
                    # A sink failed. Don't let it kill the run, but don't be
                    # silent either — log to stderr so operators can see it.
                    sink_name = getattr(sink_obj, "__qualname__", repr(sink_obj))
                    print(
                        f"[lynx] sink {sink_name} failed on event "
                        f"{event.kind!r} seq={event.seq}: "
                        f"{type(outcome).__name__}: {outcome}",
                        file=sys.stderr,
                    )
        return event.seq

    await emit("run.started", {"task": task, "principal_id": principal.id})

    conversation: tuple[Message, ...] = (Message(role="user", content=task),)
    step_seq = 0

    while True:
        # ---- budget enforcement
        if budget.steps is not None and step_seq >= budget.steps:
            await emit("run.failed", {"reason": f"step budget {budget.steps} exhausted"})
            return RunResult(
                correlation_id=cid,
                bundle_id=policy.id,
                error=f"step budget exhausted ({budget.steps})",
                steps_taken=step_seq,
            )
        if (
            budget.duration_seconds is not None
            and time.monotonic() - started_monotonic >= budget.duration_seconds
        ):
            await emit("run.failed", {"reason": "duration budget exhausted"})
            return RunResult(
                correlation_id=cid,
                bundle_id=policy.id,
                error=f"duration budget exhausted ({budget.duration_seconds}s)",
                steps_taken=step_seq,
            )

        # ---- ask agent for next action
        try:
            action = await agent.step(conversation)
        except Exception as exc:
            await emit("run.failed", {"reason": f"agent.step raised: {exc!r}"})
            return RunResult(
                correlation_id=cid,
                bundle_id=policy.id,
                error=f"agent.step raised: {type(exc).__name__}: {exc}",
                steps_taken=step_seq,
            )

        if isinstance(action, FinalAnswer):
            await emit("run.succeeded", {"final_answer": action.text})
            return RunResult(
                correlation_id=cid,
                bundle_id=policy.id,
                final_answer=action.text,
                steps_taken=step_seq,
            )

        assert isinstance(action, ToolCall)

        # Always record the assistant's tool-call attempt FIRST so adapters
        # translating to provider-specific shapes (Anthropic tool_use blocks,
        # OpenAI tool_calls) emit a well-formed assistant→tool alternation.
        assistant_call_id = action.call_id or f"step_{step_seq}"
        conversation = (
            *conversation,
            Message(
                role="assistant",
                content="",
                name=action.tool,
                tool_call_id=assistant_call_id,
                tool_call_args=dict(action.args),
            ),
        )

        # ---- build the ActionRequest using tool's declared metadata
        try:
            tool_def = tools.get(action.tool)
        except KeyError:
            await emit(
                "step.proposed",
                {"seq": step_seq, "tool": action.tool, "args": dict(action.args)},
            )
            denial_msg = f"unknown tool: {action.tool!r}"
            await emit("action.failed", {"seq": step_seq, "reason": denial_msg})
            conversation = (
                *conversation,
                Message(
                    role="tool",
                    content=f"[error] {denial_msg}",
                    tool_call_id=assistant_call_id,
                    name=action.tool,
                ),
            )
            step_seq += 1
            continue

        request = ActionRequest(
            tool=action.tool,
            args=dict(action.args),
            declared=tool_def.metadata,
            context=ExecutionContext(
                principal=principal,
                environment=environment,
                workspace=workspace,
                correlation_id=cid,
                step_seq=step_seq,
                timestamp=now_utc(),
            ),
        )

        await emit(
            "step.proposed",
            {"seq": step_seq, "tool": request.tool, "args": dict(request.args)},
        )

        # ---- policy decision (pure function)
        decision = evaluate(policy, request, request.context)
        await emit(
            "policy.evaluated",
            {
                "seq": step_seq,
                "verdict": decision.verdict.value,
                "reason": decision.reason,
                "matched_rules": list(decision.matched_rules),
            },
        )

        # ---- mediate the action
        action_kind = "action.dry_run" if decision.verdict.value == "dry_run" else "action.started"
        await emit(action_kind, {"seq": step_seq, "verdict": decision.verdict.value})

        if decision.verdict.value == "approve_required":
            await emit(
                "approval.requested",
                {"seq": step_seq, "approvers": list(decision.approvers)},
            )

        result = await mediate(request, decision, tools, on_approval)

        if decision.verdict.value == "approve_required":
            await emit(
                "approval.granted" if result.ok else "approval.denied",
                {
                    "seq": step_seq,
                    "ok": result.ok,
                    "error": result.error,
                },
            )

        if result.ok:
            completed_kind = (
                "action.dry_run_completed"
                if decision.verdict.value == "dry_run"
                else "action.completed"
            )
            await emit(
                completed_kind,
                {"seq": step_seq, "duration_ms": result.duration_ms},
            )
            tag = "[dry_run]" if decision.verdict.value == "dry_run" else "[ok]"
            conversation = (
                *conversation,
                Message(
                    role="tool",
                    content=f"{tag} {result.value}",
                    tool_call_id=assistant_call_id,
                    name=request.tool,
                ),
            )
        else:
            # Map verdict → audit event kind so downstream consumers can
            # bucket denials separately from tool failures.
            if decision.verdict.value == "deny":
                fail_kind = "action.denied"
                tag = "[denied]"
            elif decision.verdict.value == "approve_required":
                fail_kind = "action.denied"
                tag = "[denied]"
            else:
                fail_kind = "action.failed"
                tag = "[error]"
            await emit(fail_kind, {"seq": step_seq, "reason": result.error})
            conversation = (
                *conversation,
                Message(
                    role="tool",
                    content=f"{tag} {result.error}",
                    tool_call_id=assistant_call_id,
                    name=request.tool,
                ),
            )

        step_seq += 1
