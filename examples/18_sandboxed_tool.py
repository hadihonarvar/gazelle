"""
================================================================
EXAMPLE 18 — "Subprocess sandbox — best-effort resource caps" (ADVANCED)
================================================================

SCENARIO:
    Some tools you can't fully trust to be well-behaved — even your own.
    `lynx.sandbox.run_in_subprocess` runs a tool body in a fresh Python
    interpreter with best-effort POSIX resource limits and a wall-clock
    timeout. The kernel still mediates and audits; the sandbox just
    bounds the blast radius of a runaway tool.

    **This is NOT a security boundary.** It will not contain an
    adversary. See `src/lynx/sandbox.py` for the full list of what it
    does and does not isolate.

WHAT THIS EXAMPLE SHOWS:
    - Wrapping a tool body in `run_in_subprocess` so a runaway tool
      cannot exhaust the parent process's CPU or memory
    - The wall-clock timeout firing cleanly (subprocess killed + reaped;
      no zombies, no leaked pipes)
    - `SandboxError` surfacing as a normal Python exception you can
      catch — the kernel sees it as an action.failed

RUN WITH:
    python examples/18_sandboxed_tool.py
"""

from __future__ import annotations

import asyncio
import time

from lynx import (
    FinalAnswer,
    Message,
    ToolCall,
    ToolSet,
    auto_deny,
    compile_policy,
    run_agent,
    stdout_sink,
    tool,
)
from lynx.sandbox import SandboxError, run_in_subprocess

# ---------------------------------------------------------------------------
# A function we want to run sandboxed. It must be importable (no closures
# / lambdas) because the sandbox pickles it across the process boundary.
# ---------------------------------------------------------------------------


async def _heavy_compute(n: int) -> int:
    """Pretend to do CPU work for `n` iterations."""
    total = 0
    for i in range(n):
        total += i * i
    return total


async def _runaway_compute(n: int) -> int:
    """Burn CPU forever — the timeout below saves the parent."""
    while True:
        for i in range(n):
            _ = i * i


# ---------------------------------------------------------------------------
# Tools — each wraps a sandboxed call.
# ---------------------------------------------------------------------------


@tool(reversible=True, scope=("compute:exec",))
async def safe_compute(n: int) -> int:
    """Bounded by 5 cpu-seconds, 256 MB, 5 wall-clock seconds."""
    return await run_in_subprocess(
        _heavy_compute,
        args={"n": n},
        cpu_seconds=5,
        max_memory_mb=256,
        timeout_seconds=5.0,
    )


@tool(reversible=True, scope=("compute:exec",))
async def killed_by_timeout(n: int) -> str:
    """Demonstrates timeout enforcement — should always raise SandboxError."""
    try:
        await run_in_subprocess(
            _runaway_compute,
            args={"n": n},
            cpu_seconds=10,
            max_memory_mb=128,
            timeout_seconds=1.0,  # 1 second wall clock — will fire
        )
        return "(unexpectedly completed)"
    except SandboxError as exc:
        return f"sandbox killed me as expected: {exc}"


POLICY = "version: 1\ndefaults: { on_no_match: allow }\nrules: []"


class _Agent:
    def __init__(self):
        self._plan = [
            ToolCall("safe_compute", {"n": 100_000}, call_id="c1"),
            ToolCall("killed_by_timeout", {"n": 1_000_000}, call_id="c2"),
            FinalAnswer(text="sandbox demo complete"),
        ]
        self._i = 0

    async def step(self, conv: tuple[Message, ...]):
        a = self._plan[self._i]
        self._i += 1
        return a


async def main() -> None:
    t0 = time.monotonic()
    result = await run_agent(
        _Agent(),
        task="run two sandboxed tools",
        tools=ToolSet.from_functions(safe_compute, killed_by_timeout),
        policy=compile_policy(POLICY),
        sinks=(stdout_sink(),),
        on_approval=auto_deny("not used"),
    )
    elapsed = time.monotonic() - t0
    print()
    print(f"Final answer: {result.final_answer}")
    print(f"Total wall clock: {elapsed:.2f}s — the timeout fired cleanly.")
    print()
    print("Notice:")
    print("  - safe_compute completed in a child interpreter with caps applied")
    print("  - killed_by_timeout's child was killed after ~1s and REAPED")
    print("    (no zombies, no leaked stdout/stderr pipes — that's a recent fix)")
    print("  - The SandboxError surfaced as a tool return value the agent could see")


if __name__ == "__main__":
    asyncio.run(main())
