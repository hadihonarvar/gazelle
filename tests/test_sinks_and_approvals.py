"""Sinks + approval handler contract tests."""

from __future__ import annotations

import io
import json
from datetime import UTC, datetime

import pytest

from lynx import (
    ActionRequest,
    AuditEvent,
    Decision,
    ExecutionContext,
    Principal,
    ToolMetadata,
    Verdict,
    callback_sink,
    jsonl_sink,
    multi_sink,
    noop_sink,
    stdout_sink,
)
from lynx.approvals import (
    ApprovalRequest,
    auto_approve,
    auto_deny,
    callback_approval,
    cli_prompt_approval,
)


def _event(seq: int = 0, kind: str = "test") -> AuditEvent:
    return AuditEvent(
        correlation_id="corr-1",
        bundle_id="bundle-1",
        seq=seq,
        kind=kind,
        timestamp=datetime.now(UTC),
        body={"hello": "world"},
    )


def _approval_request() -> ApprovalRequest:
    req = ActionRequest(
        tool="shell",
        args={"cmd": "ls"},
        declared=ToolMetadata(cost="low", reversible=True, scope=()),
        context=ExecutionContext(
            principal=Principal(kind="user", id="t"),
            environment="dev",
            workspace=".",
            correlation_id="corr-1",
            step_seq=0,
            timestamp=datetime.now(UTC),
        ),
    )
    return ApprovalRequest(
        request=req, decision=Decision(verdict=Verdict.APPROVE_REQUIRED), correlation_id="corr-1"
    )


# ---------------------------------------------------------------------------
# Sinks
# ---------------------------------------------------------------------------


async def test_noop_sink_discards() -> None:
    sink = noop_sink()
    await sink(_event())  # Should not raise. No buffering.


async def test_stdout_sink_writes_to_stream() -> None:
    buf = io.StringIO()
    sink = stdout_sink(stream=buf)
    await sink(_event())
    out = buf.getvalue()
    assert "test" in out
    assert "corr-1"[:8] in out


async def test_jsonl_sink_writes_one_line_per_event() -> None:
    buf = io.StringIO()
    sink = jsonl_sink(buf)
    await sink(_event(seq=0))
    await sink(_event(seq=1))
    lines = buf.getvalue().strip().split("\n")
    assert len(lines) == 2
    rec0 = json.loads(lines[0])
    assert rec0["seq"] == 0
    assert rec0["kind"] == "test"
    assert rec0["correlation_id"] == "corr-1"


async def test_multi_sink_fans_out() -> None:
    a, b = io.StringIO(), io.StringIO()
    sink = multi_sink(stdout_sink(stream=a), stdout_sink(stream=b))
    await sink(_event())
    assert a.getvalue() == b.getvalue()
    assert a.getvalue()


async def test_multi_sink_swallows_individual_failures() -> None:
    async def failing(e: AuditEvent) -> None:
        raise RuntimeError("oops")

    good_buf = io.StringIO()
    sink = multi_sink(callback_sink(failing), stdout_sink(stream=good_buf))
    await sink(_event())  # should NOT raise
    assert good_buf.getvalue()


async def test_callback_sink_calls_provided_fn() -> None:
    seen: list[AuditEvent] = []

    async def collect(e: AuditEvent) -> None:
        seen.append(e)

    sink = callback_sink(collect)
    await sink(_event(seq=42))
    assert len(seen) == 1
    assert seen[0].seq == 42


# ---------------------------------------------------------------------------
# Approval handlers
# ---------------------------------------------------------------------------


async def test_auto_approve_grants() -> None:
    h = auto_approve(approver="alice")
    d = await h(_approval_request())
    assert d.granted is True
    assert d.approver == "alice"


async def test_auto_deny_refuses() -> None:
    h = auto_deny("locked")
    d = await h(_approval_request())
    assert d.granted is False
    assert d.reason == "locked"


async def test_cli_prompt_approval_yes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("builtins.input", lambda *a, **kw: "y")
    h = cli_prompt_approval(approver="hadi")
    d = await h(_approval_request())
    assert d.granted is True
    assert d.approver == "hadi"


async def test_cli_prompt_approval_no(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("builtins.input", lambda *a, **kw: "n")
    h = cli_prompt_approval(approver="hadi")
    d = await h(_approval_request())
    assert d.granted is False


async def test_callback_approval_passthrough() -> None:
    async def custom(req: ApprovalRequest):
        from lynx import ApprovalDecision

        return ApprovalDecision(granted=True, approver="custom")

    h = callback_approval(custom)
    d = await h(_approval_request())
    assert d.granted is True
    assert d.approver == "custom"
