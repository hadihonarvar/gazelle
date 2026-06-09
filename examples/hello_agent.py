"""End-to-end example: a tiny scripted agent that proves the runtime works.

Run with:

    cd gazelle/
    pip install -e .
    gazelle init
    python examples/hello_agent.py

What it demonstrates:
    - @tool decoration with reversible=False and a .shadow twin
    - A "dangerous" rm -rf attempt → DENIED by default policy
    - A safe `ls` → ALLOWED
    - A controlled `touch` in workspace → DRY_RUN first under default policy
    - Final answer + full audit chain available via `gazelle trace`
"""

from __future__ import annotations

import asyncio
import shlex
import subprocess
from pathlib import Path

from gazelle import (
    FinalAnswer,
    Message,
    ToolCall,
    runtime,
    tool,
)


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@tool(
    cost="low",
    reversible=False,
    scope=["filesystem:write"],
    blast_radius_hint=lambda cmd: 100 if "rm" in cmd else 1,
)
async def shell(cmd: str) -> str:
    """Run a shell command and return stdout/stderr."""
    proc = await asyncio.create_subprocess_shell(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    out, err = await proc.communicate()
    return (out + err).decode().strip() or "(no output)"


@shell.shadow
async def _shell_shadow(cmd: str) -> dict:
    return {
        "would_run": cmd,
        "tokens": shlex.split(cmd),
        "note": "no real execution — dry-run preview",
    }


@tool(cost="low", reversible=True, scope=["filesystem:read"])
async def list_dir(path: str = ".") -> list[str]:
    """List entries of a directory."""
    return sorted(p.name for p in Path(path).iterdir())


# ---------------------------------------------------------------------------
# A scripted agent. In reality this would be an LLM; for the demo it's
# deterministic so we can show the policy outcomes clearly.
# ---------------------------------------------------------------------------


class ScriptedAgent:
    """Plays a fixed sequence of actions, then returns a final answer."""

    def __init__(self) -> None:
        self._step = 0
        self._plan = [
            ToolCall(tool="list_dir", args={"path": "."}, call_id="c1"),
            ToolCall(tool="shell", args={"cmd": "rm -rf /"}, call_id="c2"),
            ToolCall(tool="shell", args={"cmd": "echo hello world"}, call_id="c3"),
            FinalAnswer(
                text="Demo complete. The runtime denied 'rm -rf /' and allowed safe commands."
            ),
        ]

    async def step(self, conversation: list[Message]):
        if self._step >= len(self._plan):
            return FinalAnswer(text="Out of plan.")
        action = self._plan[self._step]
        self._step += 1
        return action


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def main() -> None:
    project_dir = Path(__file__).resolve().parent.parent
    policy_path = project_dir / "policy.yaml"
    if not policy_path.exists():
        # Use the default policy embedded in the CLI
        from gazelle.cli.main import _DEFAULT_POLICY

        policy_path.write_text(_DEFAULT_POLICY)
        print(f"Wrote default policy to {policy_path}")

    agent = ScriptedAgent()
    result = await runtime.run(
        agent=agent,
        task="Demonstrate policy-gated tool execution",
        policy=str(policy_path),
        budget={"steps": 10, "duration_seconds": 30},
        principal={"kind": "user", "id": "hadi"},
        environment="dev",
        workspace=str(project_dir),
    )

    print("─" * 60)
    print(f"run_id: {result.run_id}")
    print(f"status: {result.status}")
    print(f"steps:  {result.steps}")
    print(f"final:  {result.final_answer}")
    print("─" * 60)
    print("Try:")
    print(f"  gazelle trace {result.run_id}")
    print(f"  gazelle audit verify {result.run_id}")


if __name__ == "__main__":
    asyncio.run(main())
