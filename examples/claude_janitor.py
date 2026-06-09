"""Real-world demo with a real Claude agent.

Like file_janitor.py, but the agent is Claude, not a scripted plan.

Set ANTHROPIC_API_KEY in your environment first.

Run with:
    .venv/bin/pip install anthropic    # if not already installed
    export ANTHROPIC_API_KEY=...
    .venv/bin/python examples/claude_janitor.py
"""

from __future__ import annotations

import asyncio
import os
import shutil
from pathlib import Path

from gazelle import runtime, tool
from gazelle.adapters.anthropic_sdk import ClaudeAgent


# ---------------------------------------------------------------------------
# Tools — same as file_janitor.py
# ---------------------------------------------------------------------------


@tool(cost="low", reversible=True, scope=["filesystem:read"])
async def list_dir(path: str) -> list[str]:
    """List entries in a directory."""
    return sorted(p.name for p in Path(path).iterdir())


@tool(cost="low", reversible=True, scope=["filesystem:read"])
async def read_file(path: str) -> str:
    """Read a text file."""
    return Path(path).read_text()


@tool(cost="medium", reversible=False, scope=["filesystem:write"])
async def write_file(path: str, content: str) -> str:
    """Create or overwrite a file."""
    Path(path).write_text(content)
    return f"wrote {len(content)} bytes to {path}"


@write_file.shadow
async def _write_file_shadow(path: str, content: str) -> dict:
    p = Path(path)
    return {
        "would_write": path,
        "bytes": len(content),
        "would_overwrite": p.exists(),
    }


@tool(cost="low", reversible=True, scope=["filesystem:write"])
async def delete_file(path: str) -> str:
    """Delete one file."""
    Path(path).unlink()
    return f"deleted {path}"


# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------


def make_workspace() -> Path:
    base = Path.cwd() / "demo-workspace"
    if base.exists():
        shutil.rmtree(base)
    base.mkdir(parents=True)
    (base / "README.md").write_text("# Demo workspace\n")
    (base / "app.log").write_text("[2026-06-08] recent log\n")
    (base / "old.log").write_text("[2026-01-02] should be cleaned up\n")
    return base


async def main() -> None:
    if not os.getenv("ANTHROPIC_API_KEY"):
        print("ERROR: set ANTHROPIC_API_KEY in env first.")
        return

    workspace = make_workspace()
    policy_path = Path(__file__).resolve().parent / "janitor-policy.yaml"

    print(f"Workspace: {workspace}")
    print(f"Before:    {sorted(p.name for p in workspace.iterdir())}")
    print()

    agent = ClaudeAgent(
        model="claude-opus-4-7",
        system=(
            "You are a careful file-system janitor. "
            f"Your workspace is {workspace}. "
            "Your job is to clean up old log files (more than 5 months old) "
            "and write a SUMMARY.md describing what you cleaned. "
            "Always check the directory first. Never operate outside the workspace."
        ),
    )

    result = await runtime.run(
        agent=agent,
        task=f"Clean up old logs in {workspace}, write SUMMARY.md when done.",
        policy=str(policy_path),
        budget={"steps": 15, "duration_seconds": 120, "usd": 1.0},
        principal={"kind": "user", "id": "demo"},
        environment="dev",
        workspace=str(workspace),
    )

    print("─" * 70)
    print(f"  run_id: {result.run_id}")
    print(f"  status: {result.status}")
    print(f"  steps:  {result.steps}")
    print(f"  final:  {result.final_answer}")
    print("─" * 70)
    print(f"After:    {sorted(p.name for p in workspace.iterdir()) if workspace.exists() else '(deleted)'}")
    print()
    print(f"  gazelle trace {result.run_id}")
    print(f"  gazelle audit verify {result.run_id}")


if __name__ == "__main__":
    asyncio.run(main())
