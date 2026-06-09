"""End-to-end overhead benchmark: how much does Gazelle add per step?

Compares:
  - Naked agent loop: agent.step → tool.fn → repeat
  - Gazelle: agent.step → ActionRequest → PDP → mediator → tool.fn → checkpoint → audit

Reports overhead in microseconds per step.
"""

from __future__ import annotations

import asyncio
import tempfile
import time
from pathlib import Path

from gazelle import FinalAnswer, Message, ToolCall, tool
from gazelle.core.mediator import get_registry
from gazelle.policy import compile_policy
from gazelle.runtime import Runtime
from gazelle.stores.sqlite import SQLiteStore


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


async def bench_gazelle() -> tuple[float, int]:
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
    """No Gazelle — just call the tool directly each step."""
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
    from gazelle.decorators import tool as _tool

    @_tool(cost="low", reversible=True, scope=["compute:exec"])
    async def noop(value: int) -> int:
        return value + 1

    gazelle_elapsed, gazelle_steps = await bench_gazelle()
    naked_elapsed, naked_steps = await bench_naked()

    print(f"{'naked':>12}  {naked_elapsed * 1000:>10.2f}ms  {naked_elapsed / naked_steps * 1000:>10.3f}ms/step")
    print(f"{'gazelle':>12}  {gazelle_elapsed * 1000:>10.2f}ms  {gazelle_elapsed / gazelle_steps * 1000:>10.3f}ms/step")
    overhead_ms = (gazelle_elapsed - naked_elapsed) / gazelle_steps * 1000
    print(f"{'overhead':>12}  {overhead_ms:>10.3f}ms/step")


if __name__ == "__main__":
    asyncio.run(main())
