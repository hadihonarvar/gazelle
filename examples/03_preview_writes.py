"""
================================================================
EXAMPLE 03 — "See it before it's real" (SIMPLE)
================================================================

SCENARIO:
    The assistant wants to write a file. We want a preview FIRST — what
    would be written, how many bytes, whether it would overwrite. The
    file system is untouched.

RUN WITH:
    python examples/03_preview_writes.py
"""

from __future__ import annotations

import asyncio
from pathlib import Path

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


@tool(reversible=False, scope=("filesystem:write",))
async def write_file(path: str, content: str) -> str:
    """Save text to a file. Irreversible — policy will dry-run it."""
    Path(path).write_text(content)
    return f"wrote {len(content)} bytes to {path}"


@write_file.shadow
async def _write_file_shadow(path: str, content: str) -> dict:
    p = Path(path)
    return {
        "would_write": path,
        "bytes": len(content.encode()),
        "would_overwrite": p.exists(),
        "preview": content[:120],
    }


POLICY = """
version: 1
defaults: { on_no_match: allow }
rules:
  - id: writes-dry-run
    match: { tool: write_file }
    decision: dry_run
    reason: preview before doing
"""


class LetterWriter:
    def __init__(self, target: Path):
        self.target = target
        self._i = 0
        self._plan = [
            ToolCall(
                tool="write_file",
                args={
                    "path": str(target),
                    "content": "Dear customer,\n\nThanks for your business!\n",
                },
                call_id="c1",
            ),
            FinalAnswer(text="Letter previewed; disk untouched."),
        ]

    async def step(self, conv: tuple[Message, ...]):
        a = self._plan[self._i]
        self._i += 1
        return a


async def main() -> None:
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "letter.txt"
        print(f"Target: {target}  exists? {target.exists()}")

        result = await run_agent(
            LetterWriter(target),
            task="Draft a letter",
            tools=ToolSet.from_functions(write_file),
            policy=compile_policy(POLICY),
            sinks=(stdout_sink(),),
            on_approval=auto_deny("no"),
        )

        print()
        print(f"Final: {result.final_answer}")
        print(f"target exists after run? {target.exists()}")
        if not target.exists():
            print("→ DRY-RUN WORKED: disk untouched, only a preview was shown.")


if __name__ == "__main__":
    asyncio.run(main())
