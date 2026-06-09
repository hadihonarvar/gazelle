"""Sandbox-isolation modes for tool execution.

A sandbox runs a `@tool(sandbox=...)` function in a contained environment.
The kernel still mediates and audits; the sandbox just bounds the blast
radius of the actual tool body.

Supported modes:

  - `"none"`        (default): in-process; no isolation. Fast, fine for trusted tools.
  - `"subprocess"`: fork a child Python interpreter with a stripped env and
                    optional ulimits. The tool function is shipped via pickle.
  - `"container"`:  reserved for v0.8 — runs the tool inside a one-shot
                    container with the workspace bind-mounted read-only by
                    default. Implementation hook only in v0.1.

The sandbox mode is part of `ToolMetadata` and surfaced to policy via
`declared.sandbox`, so policies can require sandboxing for specific scopes::

    rules:
      - id: untrusted-must-sandbox
        match:
          declared.scope.contains: "net:egress"
          declared.sandbox: "none"
        decision: deny
        reason: "Network tools must declare a sandbox"
"""

from __future__ import annotations

import asyncio
import json
import pickle
import sys
import tempfile
import textwrap
from collections.abc import Callable, Coroutine
from pathlib import Path
from typing import Any


class SandboxError(RuntimeError):
    pass


async def run_in_subprocess(
    fn: Callable[..., Coroutine[Any, Any, Any]],
    args: dict[str, Any],
    *,
    cpu_seconds: int = 30,
    max_memory_mb: int = 512,
    workspace: str | None = None,
    timeout_seconds: float = 60.0,
    env_allowlist: tuple[str, ...] = ("PATH", "HOME", "USER", "LANG", "LC_ALL"),
) -> Any:
    """Run `fn(**args)` in a fresh Python subprocess with limited resources.

    The function and args are pickled into a temp file; a small wrapper
    script imports the function, applies ulimits, awaits the result, and
    writes JSON back to stdout.

    Sync-tool functions are wrapped in asyncio.run. The sandbox imposes:
        * RLIMIT_CPU = cpu_seconds
        * RLIMIT_AS  = max_memory_mb (best effort; Linux only)
        * Working directory = workspace (if given)
        * Stripped environment (only env_allowlist passed through)
    """
    if not asyncio.iscoroutinefunction(fn):
        raise SandboxError("subprocess sandbox supports async tools only")

    import os

    with tempfile.TemporaryDirectory() as tmp:
        payload_path = Path(tmp) / "payload.pkl"
        result_path = Path(tmp) / "result.json"
        with payload_path.open("wb") as f:
            pickle.dump({"fn": fn, "args": args}, f)

        wrapper = textwrap.dedent(
            f"""
            import asyncio, json, pickle, resource, sys
            try:
                resource.setrlimit(resource.RLIMIT_CPU, ({cpu_seconds}, {cpu_seconds}))
            except Exception:
                pass
            try:
                resource.setrlimit(
                    resource.RLIMIT_AS,
                    ({max_memory_mb * 1024 * 1024}, {max_memory_mb * 1024 * 1024}),
                )
            except Exception:
                pass

            with open(r"{payload_path}", "rb") as f:
                payload = pickle.load(f)
            value = asyncio.run(payload["fn"](**payload["args"]))
            with open(r"{result_path}", "w") as f:
                json.dump({{"ok": True, "value": value}}, f, default=str)
            """
        )
        script = Path(tmp) / "wrapper.py"
        script.write_text(wrapper)

        env = {k: v for k, v in os.environ.items() if k in env_allowlist}
        # Propagate sys.path so pickled function references resolve.
        env["PYTHONPATH"] = os.pathsep.join(sys.path)
        proc = await asyncio.create_subprocess_exec(
            sys.executable,
            str(script),
            cwd=workspace or tmp,
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            _, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=timeout_seconds)
        except TimeoutError as exc:
            proc.kill()
            raise SandboxError(f"sandbox timeout after {timeout_seconds}s") from exc

        if proc.returncode != 0:
            stderr = stderr_b.decode()[-1000:]
            raise SandboxError(f"sandbox exited {proc.returncode}: {stderr}")

        try:
            with result_path.open() as f:
                data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError) as exc:
            raise SandboxError(f"sandbox produced no result: {exc}") from exc

        return data["value"]
