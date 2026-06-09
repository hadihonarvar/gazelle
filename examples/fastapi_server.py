"""FastAPI integration example.

A small refund-service HTTP API backed by a Lynx-gated agent.

Endpoints:
    POST /agent/run                  — synchronous: returns when the run finishes (or pauses for approval)
    GET  /agent/runs/{run_id}        — inspect a run's status
    GET  /agent/runs/{run_id}/audit  — verify the audit chain
    POST /agent/approvals/{aid}/approve  — approve a pending request and resume the run
    POST /agent/approvals/{aid}/deny     — deny and resume

Run with:
    pip install fastapi uvicorn
    uvicorn examples.fastapi_server:app --reload

Then try:
    curl -X POST localhost:8000/agent/run \\
        -H 'content-type: application/json' \\
        -d '{"customer_id": "C-123", "amount_usd": 5, "reason": "1-day outage"}'

This file is a self-contained reference — copy and adapt for your own service.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

try:
    from fastapi import FastAPI, HTTPException
    from pydantic import BaseModel
except ImportError as exc:
    raise SystemExit(
        "This example requires fastapi + uvicorn: pip install fastapi uvicorn"
    ) from exc

from lynx import FinalAnswer, Message, Runtime, ToolCall, tool
from lynx.core.mediator import get_registry
from lynx.policy import load_policy_file
from lynx.stores.sqlite import SQLiteStore


# ---------------------------------------------------------------------------
# Tools (registered at module import)
# ---------------------------------------------------------------------------


@tool(cost="low", reversible=True, scope=["customer:read"])
async def get_customer(customer_id: str) -> dict:
    fake_db = {
        "C-123": {"name": "Alice", "plan": "Pro"},
        "C-456": {"name": "Bob", "plan": "Team"},
        "C-789": {"name": "Carol", "plan": "Pro"},
    }
    return fake_db.get(customer_id, {"error": "not found"})


@tool(cost="medium", reversible=False, scope=["customer:write", "money:transfer"])
async def refund_customer(customer_id: str, amount_usd: float, reason: str) -> dict:
    return {"refunded": amount_usd, "to": customer_id, "reason": reason, "txn": "TXN-XYZ"}


@refund_customer.shadow
async def _refund_shadow(customer_id: str, amount_usd: float, reason: str) -> dict:
    return {"would_refund": amount_usd, "to": customer_id, "note": "DRY RUN — no money moved"}


# ---------------------------------------------------------------------------
# Agent — for demo we use a scripted one. Swap in ClaudeAgent for real LLM.
# ---------------------------------------------------------------------------


class ScriptedRefundAgent:
    def __init__(self, customer_id: str, amount_usd: float, reason: str):
        self._plan = [
            ToolCall("get_customer", {"customer_id": customer_id}, call_id="c1"),
            ToolCall("refund_customer",
                     {"customer_id": customer_id, "amount_usd": amount_usd, "reason": reason},
                     call_id="c2"),
            FinalAnswer(text=f"Processed refund for {customer_id}."),
        ]
        self._i = 0

    async def step(self, conversation: list[Message]):
        a = self._plan[self._i]
        self._i += 1
        return a


# ---------------------------------------------------------------------------
# App lifecycle: one Runtime singleton
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI):
    policy_path = Path(__file__).resolve().parent / "refund-policy.yaml"
    app.state.runtime = Runtime(
        store=SQLiteStore(Path(__file__).resolve().parent.parent / ".lynx" / "fastapi.db"),
        policy=load_policy_file(policy_path),
    )
    yield
    app.state.runtime.store.close()


app = FastAPI(lifespan=lifespan, title="Lynx FastAPI demo")


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


class RunRequest(BaseModel):
    customer_id: str
    amount_usd: float
    reason: str


@app.post("/agent/run")
async def run_agent(req: RunRequest) -> dict[str, Any]:
    """Run the agent synchronously. Returns when done OR paused for approval."""
    agent = ScriptedRefundAgent(req.customer_id, req.amount_usd, req.reason)
    result = await app.state.runtime.run(
        agent=agent,
        task=f"Refund {req.customer_id} ${req.amount_usd:.2f}",
        principal={"kind": "service", "id": "fastapi-demo"},
        environment="prod",
    )
    return {
        "run_id": result.run_id,
        "status": str(result.status),
        "final_answer": result.final_answer,
        "paused_approval_id": result.paused_approval_id,
    }


@app.get("/agent/runs/{run_id}")
async def get_run(run_id: str) -> dict[str, Any]:
    run = app.state.runtime.get_run(run_id)
    if run is None:
        raise HTTPException(404, detail=f"Run {run_id} not found")
    return {
        "run_id": run.id,
        "task_id": run.task_id,
        "status": str(run.status),
        "started_at": run.started_at.isoformat(),
        "ended_at": run.ended_at.isoformat() if run.ended_at else None,
        "last_step_seq": run.last_step_seq,
        "error": run.error,
    }


@app.get("/agent/runs/{run_id}/audit")
async def verify_audit(run_id: str) -> dict[str, Any]:
    ok, err = app.state.runtime.verify_audit(run_id)
    return {"chain_intact": ok, "error": err, "run_id": run_id}


class ApprovalAction(BaseModel):
    approver: str
    reason: str | None = None


@app.post("/agent/approvals/{approval_id}/approve")
async def approve(approval_id: str, body: ApprovalAction) -> dict[str, Any]:
    await app.state.runtime.approve(approval_id, approver=body.approver)
    approval = app.state.runtime.store.get_approval(approval_id)
    if approval is None:
        raise HTTPException(404, detail=f"Approval {approval_id} not found")

    # Re-run the agent to resume. In a real app you'd rebuild the agent the
    # same way it was constructed originally; we use the customer_id stored
    # in the action.
    action_args = approval.get("action", "{}")
    import json
    args = json.loads(action_args)["args"]
    agent = ScriptedRefundAgent(args["customer_id"], args["amount_usd"], args["reason"])

    result = await app.state.runtime.resume(
        agent=agent,
        run_id=approval["run_id"],
        approver=body.approver,
    )
    return {
        "run_id": result.run_id,
        "status": str(result.status),
        "final_answer": result.final_answer,
    }


@app.post("/agent/approvals/{approval_id}/deny")
async def deny(approval_id: str, body: ApprovalAction) -> dict[str, Any]:
    await app.state.runtime.deny(approval_id, approver=body.approver, reason=body.reason or "")
    return {"denied": True, "approval_id": approval_id}


@app.get("/")
async def root() -> dict[str, Any]:
    return {
        "service": "Lynx FastAPI demo",
        "endpoints": [
            "POST /agent/run",
            "GET  /agent/runs/{run_id}",
            "GET  /agent/runs/{run_id}/audit",
            "POST /agent/approvals/{approval_id}/approve",
            "POST /agent/approvals/{approval_id}/deny",
        ],
        "tools_registered": get_registry().names(),
    }
