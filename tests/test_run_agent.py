"""Integration tests for ``run_agent`` — the v2 public entry point."""

from __future__ import annotations

import io
import json
from typing import Any

from lynx import (
    FinalAnswer,
    Message,
    ToolCall,
    ToolSet,
    auto_approve,
    auto_deny,
    callback_sink,
    compile_policy,
    jsonl_sink,
    noop_sink,
    run_agent,
    tool,
)

# --- tools --------------------------------------------------------------


@tool(reversible=True, scope=("compute:exec",))
async def echo(msg: str) -> str:
    """Echo a message."""
    return msg


@tool(reversible=False, scope=("filesystem:write",))
async def dangerous(cmd: str) -> str:
    """Pretend to do something dangerous."""
    return f"did: {cmd}"


@dangerous.shadow
async def _dangerous_shadow(cmd: str) -> dict[str, Any]:
    return {"would_do": cmd}


# --- agents -------------------------------------------------------------


class _ScriptedAgent:
    def __init__(self, *actions):
        self._actions = list(actions)

    async def step(self, conversation: tuple[Message, ...]):
        return self._actions.pop(0)


# --- tests --------------------------------------------------------------


async def test_run_agent_returns_minimal_result() -> None:
    policy = compile_policy("version: 1\ndefaults: { on_no_match: allow }\nrules: []")
    tools = ToolSet.from_functions(echo)
    agent = _ScriptedAgent(
        ToolCall(tool="echo", args={"msg": "hi"}, call_id="c1"),
        FinalAnswer(text="done"),
    )
    result = await run_agent(
        agent,
        task="say hi",
        tools=tools,
        policy=policy,
        on_approval=auto_deny("no approvals"),
    )
    assert result.final_answer == "done"
    assert result.error is None
    assert result.steps_taken == 1
    assert result.correlation_id  # uuid
    assert result.bundle_id == policy.id


async def test_run_agent_blocks_dangerous_with_deny_policy() -> None:
    policy = compile_policy(
        """
version: 1
defaults: { on_no_match: allow }
rules:
  - id: block-dangerous
    match: { tool: dangerous }
    decision: deny
    reason: no dangerous allowed
        """
    )
    tools = ToolSet.from_functions(dangerous, echo)
    agent = _ScriptedAgent(
        ToolCall(tool="dangerous", args={"cmd": "rm"}, call_id="c1"),
        FinalAnswer(text="adapted"),
    )
    result = await run_agent(
        agent,
        task="try dangerous",
        tools=tools,
        policy=policy,
        on_approval=auto_deny("no"),
    )
    assert result.final_answer == "adapted"


async def test_run_agent_dry_runs_through_shadow() -> None:
    policy = compile_policy(
        """
version: 1
defaults: { on_no_match: allow }
rules:
  - id: dry-run-dangerous
    match: { tool: dangerous }
    decision: dry_run
        """
    )
    tools = ToolSet.from_functions(dangerous)
    seen_events = []

    async def collector(ev):
        seen_events.append(ev)

    agent = _ScriptedAgent(
        ToolCall(tool="dangerous", args={"cmd": "rm /"}, call_id="c1"),
        FinalAnswer(text="ok"),
    )
    await run_agent(
        agent,
        task="dry run",
        tools=tools,
        policy=policy,
        sinks=(callback_sink(collector),),
        on_approval=auto_deny("no"),
    )
    assert any("action.dry_run" in ev.kind for ev in seen_events)


async def test_run_agent_calls_on_approval_handler() -> None:
    policy = compile_policy(
        """
version: 1
defaults: { on_no_match: deny }
rules:
  - id: approve-dangerous
    match: { tool: dangerous }
    decision: approve_required
        """
    )
    tools = ToolSet.from_functions(dangerous)

    handler_was_called = False

    async def approve_once(req):
        nonlocal handler_was_called
        handler_was_called = True
        from lynx import ApprovalDecision

        return ApprovalDecision(granted=True, approver="test")

    from lynx.approvals import callback_approval

    agent = _ScriptedAgent(
        ToolCall(tool="dangerous", args={"cmd": "x"}, call_id="c1"),
        FinalAnswer(text="done"),
    )
    result = await run_agent(
        agent,
        task="needs approval",
        tools=tools,
        policy=policy,
        on_approval=callback_approval(approve_once),
    )
    assert handler_was_called
    assert result.final_answer == "done"


async def test_run_agent_streams_events_to_sinks() -> None:
    policy = compile_policy("version: 1\ndefaults: { on_no_match: allow }\nrules: []")
    tools = ToolSet.from_functions(echo)
    buf = io.StringIO()
    agent = _ScriptedAgent(
        ToolCall(tool="echo", args={"msg": "hi"}, call_id="c1"),
        FinalAnswer(text="done"),
    )
    await run_agent(
        agent,
        task="streaming",
        tools=tools,
        policy=policy,
        sinks=(jsonl_sink(buf),),
        on_approval=auto_approve(),
    )
    lines = [line for line in buf.getvalue().split("\n") if line.strip()]
    kinds = [json.loads(line)["kind"] for line in lines]
    assert "run.started" in kinds
    assert "policy.evaluated" in kinds
    assert "run.succeeded" in kinds


async def test_run_agent_budget_steps() -> None:
    policy = compile_policy("version: 1\ndefaults: { on_no_match: allow }\nrules: []")
    tools = ToolSet.from_functions(echo)

    # Agent never finishes
    class NeverFinishes:
        async def step(self, conv):
            return ToolCall(tool="echo", args={"msg": "x"}, call_id="c")

    from lynx import Budget

    result = await run_agent(
        NeverFinishes(),
        task="loop",
        tools=tools,
        policy=policy,
        budget=Budget(steps=3, duration_seconds=10),
        on_approval=auto_approve(),
    )
    assert result.error is not None
    assert "budget exhausted" in result.error
    assert result.steps_taken == 3


async def test_run_agent_unknown_tool_doesnt_crash() -> None:
    policy = compile_policy("version: 1\ndefaults: { on_no_match: allow }\nrules: []")
    tools = ToolSet.from_functions(echo)
    agent = _ScriptedAgent(
        ToolCall(tool="nonexistent_tool", args={}, call_id="c1"),
        FinalAnswer(text="adapted"),
    )
    result = await run_agent(
        agent,
        task="bad tool",
        tools=tools,
        policy=policy,
        sinks=(noop_sink(),),
        on_approval=auto_deny("no"),
    )
    # Should recover gracefully — final answer reached
    assert result.final_answer == "adapted"
