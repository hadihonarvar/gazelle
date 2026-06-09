"""Tests for the subprocess sandbox mode.

The subprocess sandbox uses POSIX ``resource.setrlimit`` for CPU and memory
caps; that module is unavailable on Windows. A Windows implementation will
need job objects + the Windows-specific resource quota APIs and lands in a
later milestone. For now the whole module is skipped on Windows.
"""

from __future__ import annotations

import sys

import pytest

# Sandbox feature is POSIX-only at the moment — skip the whole module on Windows.
pytestmark = pytest.mark.skipif(
    sys.platform == "win32",
    reason="Subprocess sandbox uses POSIX resource limits; Windows port deferred to v0.8.",
)

from lynx.sandbox import SandboxError, run_in_subprocess  # noqa: E402

# Subprocess sandboxing depends on the function being picklable. Module-level
# functions work; lambdas and locally-defined functions do not. Define here.


async def _identity(x: int) -> int:
    return x * 2


async def _crash(why: str) -> str:
    raise RuntimeError(why)


async def _slow() -> str:
    import time

    time.sleep(10)
    return "should not be reached"


async def test_subprocess_runs_simple_function():
    out = await run_in_subprocess(_identity, {"x": 21})
    assert out == 42


async def test_subprocess_raises_on_tool_exception():
    with pytest.raises(SandboxError):
        await run_in_subprocess(_crash, {"why": "boom"})


async def test_subprocess_enforces_timeout():
    with pytest.raises(SandboxError, match="timeout"):
        await run_in_subprocess(_slow, {}, timeout_seconds=0.5)
