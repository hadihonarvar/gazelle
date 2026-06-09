"""End-to-end: run the scripted ScriptedAgent against the runtime and check
that policy enforcement, journaling, and audit chain all work.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from lynx import FinalAnswer, Message, ToolCall, tool
from lynx.core.mediator import get_registry
from lynx.core.types import RunStatus
from lynx.policy import compile_policy
from lynx.runtime import Runtime
from lynx.stores.sqlite import SQLiteStore


@pytest.fixture
def fresh_runtime(tmp_path):
    """Fresh store + policy + freshly-registered tools for each test."""
    get_registry().clear()

    @tool(cost="low", reversible=True, scope=["filesystem:read"])
    async def list_dir(path: str = ".") -> list[str]:
        return sorted(p.name for p in Path(path).iterdir())

    @tool(cost="low", reversible=True, scope=["compute:read"])
    async def shell(cmd: str) -> str:
        proc = await asyncio.create_subprocess_shell(
            cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        out, err = await proc.communicate()
        return (out + err).decode()

    @shell.shadow
    async def _shell_shadow(cmd: str) -> dict:
        return {"would_run": cmd}

    store = SQLiteStore(tmp_path / "state.db")
    bundle = compile_policy(
        """
version: 1
defaults:
  on_no_match: allow
rules:
  - id: deny-rm-root
    match:
      tool: shell
      args.cmd.matches: '^rm -rf /'
    decision: deny
    reason: rm -rf / is denied
        """
    )
    yield Runtime(store=store, policy=bundle)
    get_registry().clear()


class ScriptedAgent:
    def __init__(self):
        self._i = 0
        self._plan = [
            ToolCall(tool="list_dir", args={"path": "."}, call_id="c1"),
            ToolCall(tool="shell", args={"cmd": "rm -rf /"}, call_id="c2"),
            ToolCall(tool="shell", args={"cmd": "echo hi"}, call_id="c3"),
            FinalAnswer(text="done"),
        ]

    async def step(self, conversation: list[Message]):
        action = self._plan[self._i]
        self._i += 1
        return action


async def test_end_to_end_runs_with_denial(fresh_runtime):
    agent = ScriptedAgent()
    result = await fresh_runtime.run(
        agent=agent,
        task="demo",
        principal={"kind": "user", "id": "tester"},
    )
    assert result.status == RunStatus.SUCCEEDED, f"error: {result.error}"
    assert result.final_answer == "done"

    steps = fresh_runtime.get_steps(result.run_id)
    assert len(steps) == 3  # 3 tool calls, final answer doesn't produce a step

    # The middle step (rm -rf /) was denied
    deny_step = steps[1]
    assert deny_step.decision is not None
    assert deny_step.decision.verdict.value == "deny"

    # The others succeeded
    assert steps[0].decision is not None and steps[0].decision.verdict.value == "allow"
    assert steps[2].decision is not None and steps[2].decision.verdict.value == "allow"


async def test_audit_chain_verifies(fresh_runtime):
    agent = ScriptedAgent()
    result = await fresh_runtime.run(
        agent=agent,
        task="demo",
        principal={"kind": "user", "id": "tester"},
    )
    assert result.status == RunStatus.SUCCEEDED, f"error: {result.error}"

    ok, err = fresh_runtime.verify_audit(result.run_id)
    assert ok, f"audit chain broken: {err}"

    chain = fresh_runtime.audit_chain(result.run_id)
    kinds = [e.kind for e in chain]
    assert "run.started" in kinds
    assert "policy.evaluated" in kinds
    assert "action.denied" in kinds
    assert "run.succeeded" in kinds
