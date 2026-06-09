"""Microbenchmark for the Policy Decision Point.

Measures decision latency as a function of rule count. PDP is pure so this
is the cleanest measurement of kernel overhead.

Run with:
    python benchmarks/bench_pdp.py
"""

from __future__ import annotations

import time
from datetime import datetime, timezone

from lynx.core.policy import compile_policy, evaluate
from lynx.core.types import (
    ActionRequest,
    ExecutionContext,
    Principal,
    ToolMetadata,
)


def _ctx() -> ExecutionContext:
    return ExecutionContext(
        principal=Principal(kind="user", id="bench"),
        environment="dev",
        workspace="/tmp",
        run_id="R-bench",
        step_seq=0,
        timestamp=datetime.now(timezone.utc),
    )


def _req(tool: str = "shell") -> ActionRequest:
    return ActionRequest.build(
        tool=tool,
        args={"cmd": "ls"},
        declared=ToolMetadata(cost="low", reversible=True, scope=("compute:exec",)),
        context=_ctx(),
    )


def _make_policy_yaml(n_rules: int) -> str:
    rules = "\n".join(
        f"""  - id: rule-{i}
    match:
      tool: shell
      args.cmd.matches: '^cmd-{i}'
    decision: deny"""
        for i in range(n_rules)
    )
    return f"""
version: 1
defaults: {{ on_no_match: allow }}
rules:
{rules}
"""


def bench(n_rules: int, iterations: int = 50_000) -> float:
    bundle = compile_policy(_make_policy_yaml(n_rules))
    ctx = _ctx()
    req = _req()
    start = time.perf_counter()
    for _ in range(iterations):
        evaluate(bundle, req, ctx)
    elapsed = time.perf_counter() - start
    per_call_us = (elapsed / iterations) * 1_000_000
    return per_call_us


def main() -> None:
    print(f"{'rules':>8}  {'µs/call':>10}  {'calls/sec':>12}")
    print("-" * 36)
    for n in [0, 10, 50, 100, 250, 500, 1000]:
        per = bench(n)
        print(f"{n:>8}  {per:>10.2f}  {1_000_000 / per:>12,.0f}")


if __name__ == "__main__":
    main()
