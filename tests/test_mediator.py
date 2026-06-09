"""Tests for the Action Mediator (PEP).

Covers each verdict dispatch path: allow, deny, dry_run, transform, and the
approval-pending branch.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from lynx import tool
from lynx.core.mediator import (
    ApprovalPending,
    ToolDenied,
    get_broker,
    get_registry,
    mediate,
)
from lynx.core.policy import allow, approve_required, deny, dry_run, transform
from lynx.core.types import ActionRequest, ExecutionContext, Principal, ToolMetadata


def _ctx() -> ExecutionContext:
    return ExecutionContext(
        principal=Principal(kind="user", id="t"),
        environment="dev",
        workspace="/tmp",
        run_id="R-test",
        step_seq=0,
        timestamp=datetime.now(UTC),
    )


@pytest.fixture
def registered():
    get_registry().clear()

    @tool(cost="low", reversible=False, scope=["filesystem:write"])
    async def write_thing(path: str, content: str) -> str:
        return f"wrote {len(content)} bytes to {path}"

    @write_thing.shadow
    async def _write_thing_shadow(path: str, content: str) -> dict:
        return {"would_write": path, "bytes": len(content)}

    yield write_thing
    get_registry().clear()


def _req(args: dict, *, reversible: bool = False, has_shadow: bool = True) -> ActionRequest:
    return ActionRequest.build(
        tool="write_thing",
        args=args,
        declared=ToolMetadata(
            cost="low",
            reversible=reversible,
            scope=("filesystem:write",),
            has_shadow=has_shadow,
        ),
        context=_ctx(),
    )


# --- allow / deny ---------------------------------------------------------


async def test_allow_executes_tool(registered):
    request = _req({"path": "/tmp/x", "content": "hi"})
    decision = allow()
    result = await mediate(request, decision)
    assert result.ok is True
    assert "wrote 2 bytes" in result.value


async def test_deny_raises_tooldenied(registered):
    request = _req({"path": "/tmp/x", "content": "hi"})
    decision = deny("nope")
    with pytest.raises(ToolDenied) as excinfo:
        await mediate(request, decision)
    assert "nope" in str(excinfo.value)


# --- dry_run --------------------------------------------------------------


async def test_dry_run_calls_shadow(registered):
    request = _req({"path": "/tmp/x", "content": "hello"})
    decision = dry_run()
    result = await mediate(request, decision)
    assert result.ok is True
    assert result.value["dry_run"] is True
    assert result.value["preview"]["bytes"] == 5


# --- approve_required -----------------------------------------------------


async def test_approve_required_raises_and_opens_approval(registered):
    request = _req({"path": "/tmp/x", "content": "hi"})
    decision = approve_required(approvers=("@oncall",), timeout_seconds=300)
    with pytest.raises(ApprovalPending) as excinfo:
        await mediate(request, decision)
    pending = get_broker().pending()
    assert any(p.id == excinfo.value.approval_id for p in pending)


# --- transform ------------------------------------------------------------


async def test_transform_uses_rewritten_args(registered, tmp_path):
    request = _req({"path": str(tmp_path / "out.txt"), "content": "AAA"})
    decision = transform(
        transform_args={"path": str(tmp_path / "out.txt"), "content": "BBB-rewritten"},
    )
    result = await mediate(request, decision)
    assert result.ok is True
    # The tool's return value reflects the rewritten content length.
    assert "wrote 13 bytes" in result.value


# --- tool error propagation ------------------------------------------------


async def test_tool_error_returns_failed_result():
    """Tool that raises should produce ok=False ActionResult, not propagate."""
    get_registry().clear()

    @tool(cost="low", reversible=True, scope=["compute:exec"])
    async def boom(why: str) -> str:
        raise RuntimeError(f"deliberate: {why}")

    request = ActionRequest.build(
        tool="boom",
        args={"why": "test"},
        declared=ToolMetadata(
            cost="low", reversible=True, scope=("compute:exec",), has_shadow=False
        ),
        context=_ctx(),
    )
    result = await mediate(request, allow())
    assert result.ok is False
    assert "RuntimeError" in (result.error or "")
    assert "deliberate: test" in (result.error or "")
    get_registry().clear()
