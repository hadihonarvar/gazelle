"""
================================================================
EXAMPLE 11 — "Lynx behind Flask" (INTEGRATION)
================================================================

SCENARIO:
    Same as example 09 but for Flask. Flask is sync so we wrap with
    asyncio.run inside the view. Note that asyncio.run() spins up and tears
    down a fresh event loop per request — fine for a demo, but for
    production prefer an async framework (FastAPI, Quart) or a worker
    that keeps a loop hot.

REQUIRES:
    pip install flask

RUN WITH:
    # File-path form (the digit-prefixed filename is not importable as a
    # Python module, so the dotted --app form does NOT work):
    flask --app examples/11_flask_service.py run --debug
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

try:
    from flask import Flask, jsonify, request
except ImportError as exc:
    raise SystemExit("This example requires flask: pip install flask") from exc

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
    return {"refunded": amount_usd, "to": customer_id}


@refund_customer.shadow
async def _refund_shadow(customer_id: str, amount_usd: float, reason: str) -> dict:
    return {"would_refund": amount_usd}


class ScriptedRefund:
    def __init__(self, customer_id, amount_usd, reason):
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


def create_app() -> Flask:
    app = Flask(__name__)
    policy_path = Path(__file__).resolve().parent / "policies" / "refund.yaml"
    app.config["TOOLS"] = ToolSet.from_functions(get_customer, refund_customer)
    app.config["POLICY"] = load_policy_file(policy_path)
    return app


app = create_app()


@app.post("/agent/run")
def run_endpoint() -> Any:
    body = request.get_json() or {}
    for required in ("customer_id", "amount_usd", "reason"):
        if required not in body:
            return jsonify({"error": f"missing field: {required}"}), 400

    events_count = 0
    denials: list[dict[str, Any]] = []

    async def collect(ev):
        nonlocal events_count
        events_count += 1
        if ev.kind == "action.denied":
            denials.append({"seq": ev.seq, "reason": ev.body.get("reason", "")})

    async def go():
        return await run_agent(
            ScriptedRefund(body["customer_id"], float(body["amount_usd"]), body["reason"]),
            task=f"Refund {body['customer_id']}",
            tools=app.config["TOOLS"],
            policy=app.config["POLICY"],
            sinks=(callback_sink(collect),),
            on_approval=auto_approve(approver="api"),
        )

    result = asyncio.run(go())
    payload = {
        "correlation_id": result.correlation_id,
        "final_answer": result.final_answer,
        "error": result.error,
        "steps_taken": result.steps_taken,
        "events_count": events_count,
        "denials": denials,
    }
    status = 403 if denials else 200
    return jsonify(payload), status


@app.get("/")
def root() -> Any:
    return jsonify({"service": "Lynx Flask demo"})
