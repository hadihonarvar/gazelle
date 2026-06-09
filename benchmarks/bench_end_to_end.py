"""End-to-end overhead benchmark: how much does Lynx add per step?

Compares:
  - Naked agent loop: agent.step → tool.fn → repeat
  - Lynx: agent.step → ActionRequest → PDP → mediator → tool.fn → checkpoint → audit

Reports overhead in microseconds per step.
"""

from __future__ import annotations

import asyncio
import tempfile
import time
from pathlib import Path

from lynx import FinalAnswer, Message, ToolCall, tool
from lynx.core.mediator import get_registry
from lynx.policy import compile_policy
from lynx.runtime import Runtime
from lynx.stores.sqlite import SQLiteStore


STEPS = 50


@tool(cost="low", reversible=True, scope=["compute:exec"])
async def noop(value: int) -> int:
    return value + 1


class _BenchAgent:
    def __init__(self):
        self._i = 0

    async def step(self, conversation):
        if self._i >= STEPS:
            return FinalAnswer(text="done")
        i = self._i
        self._i += 1
        return ToolCall("noop", {"value": i}, call_id=f"c{i}")


async def bench_lynx() -> tuple[float, int]:
    with tempfile.TemporaryDirectory() as tmp:
        store = SQLiteStore(Path(tmp) / "state.db")
        bundle = compile_policy("version: 1\ndefaults: { on_no_match: allow }\nrules: []")
        runtime = Runtime(store=store, policy=bundle)

        start = time.perf_counter()
        result = await runtime.run(
            agent=_BenchAgent(),
            task="bench",
            principal={"kind": "user", "id": "bench"},
        )
        elapsed = time.perf_counter() - start
        return elapsed, result.steps


async def bench_naked() -> tuple[float, int]:
    """No Lynx — just call the tool directly each step."""
    agent = _BenchAgent()
    start = time.perf_counter()
    conv: list = [Message(role="user", content="bench")]
    n = 0
    while True:
        action = await agent.step(conv)
        if isinstance(action, FinalAnswer):
            break
        # call the tool directly
        await noop(**action.args)
        n += 1
    elapsed = time.perf_counter() - start
    return elapsed, n


async def main() -> None:
    get_registry().clear()
    # Re-register the noop tool (module-level decorator already did this on import).
    # We just need to make sure the registry isn't stale.
    from lynx.decorators import tool as _tool

    @_tool(cost="low", reversible=True, scope=["compute:exec"])
    async def noop(value: int) -> int:
        return value + 1

    lynx_elapsed, lynx_steps = await bench_lynx()
    naked_elapsed, naked_steps = await bench_naked()

    print(f"{'naked':>12}  {naked_elapsed * 1000:>10.2f}ms  {naked_elapsed / naked_steps * 1000:>10.3f}ms/step")
    print(f"{'lynx':>12}  {lynx_elapsed * 1000:>10.2f}ms  {lynx_elapsed / lynx_steps * 1000:>10.3f}ms/step")
    overhead_ms = (lynx_elapsed - naked_elapsed) / lynx_steps * 1000
    print(f"{'overhead':>12}  {overhead_ms:>10.3f}ms/step")


if __name__ == "__main__":
    asyncio.run(main())
