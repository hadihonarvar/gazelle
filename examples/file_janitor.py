"""Real-world demo: an agent tidies a workspace.

What this proves:
    * Real filesystem reads & writes happen on a real temp workspace.
    * The policy engine catches attempts to escape the workspace (DENY).
    * Writes inside the workspace are previewed first (DRY_RUN).
    * A dangerous shell command (rm -rf /) is hard-blocked (DENY).
    * The audit chain records every step, verifiable after the fact.

The "agent" is scripted so we can show every verdict cleanly. The plan
mirrors what a real LLM agent often does: tries an unsafe thing, gets
denied, retries safer.

Run with:
    .venv/bin/python examples/file_janitor.py
"""

from __future__ import annotations

import asyncio
import shutil
import tempfile
from pathlib import Path

from lynx import FinalAnswer, Message, ToolCall, runtime, tool
from lynx.core.mediator import get_registry


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@tool(cost="low", reversible=True, scope=["filesystem:read"])
async def list_dir(path: str) -> list[str]:
    """List the entries of a directory."""
    return sorted(p.name for p in Path(path).iterdir())


@tool(cost="low", reversible=True, scope=["filesystem:read"])
async def read_file(path: str) -> str:
    """Read a text file."""
    return Path(path).read_text()


@tool(cost="low", reversible=True, scope=["filesystem:read"])
async def stat_file(path: str) -> dict:
    """Return size + mtime for a file."""
    s = Path(path).stat()
    return {"size_bytes": s.st_size, "mtime": int(s.st_mtime)}


@tool(cost="medium", reversible=False, scope=["filesystem:write"])
async def write_file(path: str, content: str) -> str:
    """Create or overwrite a file. Irreversible — policy will dry-run first."""
    p = Path(path)
    p.write_text(content)
    return f"wrote {len(content)} bytes to {path}"


@write_file.shadow
async def _write_file_shadow(path: str, content: str) -> dict:
    p = Path(path)
    existed = p.exists()
    return {
        "would_write": path,
        "bytes": len(content),
        "would_overwrite": existed,
        "preview_first_120_chars": content[:120],
    }


@tool(cost="low", reversible=True, scope=["filesystem:write"])
async def delete_file(path: str) -> str:
    """Delete one file. (Reversible=True for the demo; in practice this would be False.)"""
    Path(path).unlink()
    return f"deleted {path}"


@tool(cost="medium", reversible=True, scope=["compute:exec"])
async def shell(cmd: str) -> str:
    """Run a shell command. Policy decides whether it's allowed."""
    proc = await asyncio.create_subprocess_shell(
        cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    out, err = await proc.communicate()
    return (out + err).decode().strip() or "(no output)"


# ---------------------------------------------------------------------------
# The scripted "agent"
# ---------------------------------------------------------------------------


class JanitorAgent:
    """A janitor agent that tries to tidy ``workspace``.

    Plays a fixed sequence of actions — chosen to show every relevant
    verdict against the janitor policy. A real LLM agent would pick this
    sequence dynamically.
    """

    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace
        self._step = 0
        self._plan = [
            # 1. See what's here  — ALLOW (read-only)
            ToolCall("list_dir", {"path": str(workspace)}, call_id="c1"),

            # 2. Read one file    — ALLOW (read-only)
            ToolCall("read_file", {"path": str(workspace / "README.md")}, call_id="c2"),

            # 3. Check size of an old log — ALLOW
            ToolCall("stat_file", {"path": str(workspace / "old.log")}, call_id="c3"),

            # 4. Try to write outside workspace — DENY (path escape)
            ToolCall(
                "write_file",
                {"path": "/etc/janitor-summary.md", "content": "found 3 files"},
                call_id="c4",
            ),

            # 5. Retry writing inside workspace — DRY_RUN (preview only)
            ToolCall(
                "write_file",
                {
                    "path": str(workspace / "SUMMARY.md"),
                    "content": "# Janitor summary\n\nCleaned 1 old log file.\n",
                },
                call_id="c5",
            ),

            # 6. Delete the old log — ALLOW (inside workspace)
            ToolCall("delete_file", {"path": str(workspace / "old.log")}, call_id="c6"),

            # 7. Try the catastrophic command — DENY (hard rule)
            ToolCall("shell", {"cmd": "rm -rf /"}, call_id="c7"),

            # 8. Done.
            FinalAnswer(
                text=(
                    "Done. Read README; previewed SUMMARY.md (dry-run); "
                    "deleted old.log; was blocked from writing /etc and from rm -rf /."
                )
            ),
        ]

    async def step(self, conversation: list[Message]):
        action = self._plan[self._step]
        self._step += 1
        return action


# ---------------------------------------------------------------------------
# Setup + main
# ---------------------------------------------------------------------------


def make_workspace() -> Path:
    """Create a real workspace with some files for the agent to operate on."""
    # Use a clearly non-system path so the demo runs identically on macOS + Linux.
    base = Path.cwd() / "demo-workspace"
    if base.exists():
        shutil.rmtree(base)
    base.mkdir(parents=True)
    (base / "README.md").write_text(
        "# Demo workspace\n\nThis is where the janitor agent operates.\n"
    )
    (base / "app.log").write_text("[2026-06-08] hello world\n[2026-06-08] still here\n")
    (base / "old.log").write_text("[2026-01-02] ancient logs that should be cleaned\n")
    return base


async def main() -> None:
    workspace = make_workspace()
    policy_path = Path(__file__).resolve().parent / "janitor-policy.yaml"

    print(f"Workspace: {workspace}")
    print("Before:", sorted(p.name for p in workspace.iterdir()))
    print()

    agent = JanitorAgent(workspace)
    result = await runtime.run(
        agent=agent,
        task=f"Tidy the workspace at {workspace}",
        policy=str(policy_path),
        budget={"steps": 20, "duration_seconds": 30},
        principal={"kind": "user", "id": "demo"},
        environment="dev",
        workspace=str(workspace),
    )

    print()
    print("─" * 70)
    print(f"  run_id:  {result.run_id}")
    print(f"  status:  {result.status}")
    print(f"  steps:   {result.steps}")
    print(f"  final:   {result.final_answer}")
    print("─" * 70)

    print()
    print("After: ", sorted(p.name for p in workspace.iterdir()))

    # Cleanup
    shutil.rmtree(workspace)

    print()
    print("Verify the audit chain:")
    print(f"  lynx trace {result.run_id}")
    print(f"  lynx audit verify {result.run_id}")


if __name__ == "__main__":
    asyncio.run(main())
