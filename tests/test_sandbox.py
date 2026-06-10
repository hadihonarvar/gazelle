"""Sandbox tests — kept as in v1 (subprocess sandbox is unchanged).

POSIX-only (resource module unavailable on Windows); skipped there.
"""

from __future__ import annotations

import sys

import pytest

pytestmark = pytest.mark.skipif(
    sys.platform == "win32",
    reason="Subprocess sandbox uses POSIX resource limits.",
)

from lynx.sandbox import SandboxError, run_in_subprocess  # noqa: E402


async def _identity(x: int) -> int:
    return x * 2


async def _crash(why: str) -> str:
    raise RuntimeError(why)


async def _slow() -> str:
    import time

    time.sleep(10)
    return "should not be reached"


async def test_subprocess_runs_simple_function() -> None:
    out = await run_in_subprocess(_identity, {"x": 21})
    assert out == 42


async def test_subprocess_raises_on_tool_exception() -> None:
    with pytest.raises(SandboxError):
        await run_in_subprocess(_crash, {"why": "boom"})


async def test_subprocess_enforces_timeout() -> None:
    with pytest.raises(SandboxError, match="timeout"):
        await run_in_subprocess(_slow, {}, timeout_seconds=0.5)
