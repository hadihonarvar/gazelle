"""
================================================================
EXAMPLE 09 — "Lynx behind FastAPI" (ADVANCED)
================================================================

SCENARIO:
    Wrap run_agent() in a FastAPI endpoint. One ToolSet + PolicyBundle
    built at startup (immutable); each request creates a fresh agent and
    streams events to a per-request jsonl sink.

REQUIRES:
    pip install fastapi uvicorn

RUN WITH:
    uvicorn examples.09_fastapi_service:app --reload
    curl -X POST localhost:8000/agent/run \\
        -H 'content-type: application/json' \\
        -d '{"customer_id": "C-123", "amount_usd": 5, "reason": "1-day outage"}'
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

try:
    from fastapi import FastAPI
    from pydantic import BaseModel
except ImportError as exc:
    raise SystemExit(
        "This example requires fastapi + uvicorn: pip install fastapi uvicorn"
    ) from exc

from lynx import (
    FinalAnswer,
    Message,
    ToolCall,
    ToolSet,
    auto_approve,
    callback_sink,
    load_policy_file,
    run_agent,
    tool,
)


@tool(reversible=True, scope=("customer:read",))
async def get_customer(customer_id: str) -> dict:
    return {"id": customer_id, "name": "Alice"}


@tool(reversible=False, scope=("customer:write",))
async def refund_customer(customer_id: str, amount_usd: float, reason: str) -> dict:
    return {"refunded": amount_usd, "to": customer_id, "reason": reason}


@refund_customer.shadow
async def _refund_shadow(customer_id: str, amount_usd: float, reason: str) -> dict:
    return {"would_refund": amount_usd}


class ScriptedRefund:
    def __init__(self, customer_id: str, amount_usd: float, reason: str):
        self._i = 0
        self._plan = [
            ToolCall("get_customer", {"customer_id": customer_id}, call_id="c1"),
            ToolCall(
                "refund_customer",
                {"customer_id": customer_id, "amount_usd": amount_usd, "reason": reason},
                call_id="c2",
            ),
            FinalAnswer(text=f"Refund processed for {customer_id}."),
        ]

    async def step(self, conv: tuple[Message, ...]):
        a = self._plan[self._i]
        self._i += 1
        return a


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Build the immutable tools + policy once at startup
    policy_path = Path(__file__).resolve().parent / "policies" / "refund.yaml"
    app.state.tools = ToolSet.from_functions(get_customer, refund_customer)
    app.state.policy = load_policy_file(policy_path)
    yield


app = FastAPI(lifespan=lifespan, title="Lynx FastAPI demo")


class RunRequest(BaseModel):
    customer_id: str
    amount_usd: float
    reason: str


@app.post("/agent/run")
async def run_endpoint(req: RunRequest) -> dict[str, Any]:
    # Per-request: collect events; user's choice of where to put them
    events_seen: list[dict[str, Any]] = []

    async def collect(ev):
        events_seen.append({"kind": ev.kind, "seq": ev.seq})

    result = await run_agent(
        ScriptedRefund(req.customer_id, req.amount_usd, req.reason),
        task=f"Refund {req.customer_id}",
        tools=app.state.tools,
        policy=app.state.policy,
        sinks=(callback_sink(collect),),
        on_approval=auto_approve(approver="api"),
    )
    return {
        "correlation_id": result.correlation_id,
        "final_answer": result.final_answer,
        "error": result.error,
        "steps_taken": result.steps_taken,
        "events_count": len(events_seen),
    }


@app.get("/")
async def root():
    return {"service": "Lynx FastAPI demo", "tools": list(app.state.tools.names())}
