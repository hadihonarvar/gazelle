"""Tests for the subprocess sandbox mode."""

from __future__ import annotations

import sys

import pytest

from gazelle.sandbox import SandboxError, run_in_subprocess

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


@pytest.mark.skipif(sys.platform == "win32", reason="signal/timeout semantics differ on Windows")
async def test_subprocess_enforces_timeout():
    with pytest.raises(SandboxError, match="timeout"):
        await run_in_subprocess(_slow, {}, timeout_seconds=0.5)
