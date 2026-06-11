"""
================================================================
EXAMPLE 15 — "Custom SQLite audit sink + multi_sink resilience" (ADVANCED)
================================================================

SCENARIO:
    The library ships `jsonl_sink` and `stdout_sink`. Real services usually
    want their events in a database, an SIEM, an OTel pipeline, or
    something custom. There is no built-in `sqlite_sink` — you write your
    own (5–10 lines) using the `Sink` protocol.

    This example also demonstrates: when one sink in a `multi_sink`
    composition fails, the others keep working and the run completes
    successfully. The failure is reported to stderr (not silently
    swallowed) so operators can see it.

WHAT THIS EXAMPLE SHOWS:
    - A real custom sink against SQLite (you own the connection lifecycle)
    - `multi_sink(...)` fan-out with one good sink, one stdout sink, and
      one intentionally-broken sink — the run still finishes
    - `canonical_json` from `lynx.core.types` for stable serialization
    - Querying the audit DB after the run

RUN WITH:
    python examples/15_sqlite_sink.py
"""

from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path

from lynx import (
    FinalAnswer,
    Message,
    ToolCall,
    ToolSet,
    auto_deny,
    callback_sink,
    compile_policy,
    multi_sink,
    run_agent,
    stdout_sink,
    tool,
)
from lynx.core.types import canonical_json

DB_PATH = Path("audit_demo.sqlite")


# ---------------------------------------------------------------------------
# The sink — your code, your connection, your retention.
# ---------------------------------------------------------------------------


def make_sqlite_sink(conn: sqlite3.Connection):
    """Build a Sink closure that writes each event to the given connection.

    The connection is created once at startup and lives across all events
    — no reconnect per event. SQLite's driver is sync, so we wrap the write
    in `asyncio.to_thread` to keep the event loop responsive.
    """

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS events (
            correlation_id TEXT,
            bundle_id      TEXT,
            seq            INTEGER,
            kind           TEXT,
            ts             TEXT,
            body           TEXT,
            PRIMARY KEY (correlation_id, seq)
        )
        """
    )
    conn.commit()

    def _write(event):
        conn.execute(
            "INSERT OR REPLACE INTO events VALUES (?, ?, ?, ?, ?, ?)",
            (
                event.correlation_id,
                event.bundle_id,
                event.seq,
                event.kind,
                event.timestamp.isoformat(),
                canonical_json(dict(event.body)),
            ),
        )
        conn.commit()

    async def sqlite_sink(event):
        await asyncio.to_thread(_write, event)

    return sqlite_sink


# ---------------------------------------------------------------------------
# An intentionally-broken sink to prove the kernel keeps running
# ---------------------------------------------------------------------------


async def broken_sink(event):
    raise RuntimeError(f"this sink is intentionally broken on event {event.seq}")


# ---------------------------------------------------------------------------
# Toy agent + policy
# ---------------------------------------------------------------------------


@tool(reversible=True, scope=("compute:read",))
async def get_metric(name: str) -> float:
    return 42.0


class _Agent:
    def __init__(self):
        self._plan = [
            ToolCall("get_metric", {"name": "cpu"}, call_id="c1"),
            ToolCall("get_metric", {"name": "mem"}, call_id="c2"),
            FinalAnswer(text="collected metrics"),
        ]
        self._i = 0

    async def step(self, conv: tuple[Message, ...]):
        a = self._plan[self._i]
        self._i += 1
        return a


POLICY = "version: 1\ndefaults: { on_no_match: allow }\nrules: []"


async def main() -> None:
    # Clean slate so the demo is reproducible.
    if DB_PATH.exists():
        DB_PATH.unlink()

    conn = sqlite3.connect(DB_PATH)
    try:
        result = await run_agent(
            _Agent(),
            task="audit-to-sqlite demo",
            tools=ToolSet.from_functions(get_metric),
            policy=compile_policy(POLICY),
            # Three sinks; one broken. The run must still complete.
            sinks=(
                multi_sink(
                    stdout_sink(),
                    callback_sink(make_sqlite_sink(conn)),
                    callback_sink(broken_sink),
                ),
            ),
            on_approval=auto_deny("n/a"),
        )

        print()
        print(f"Final answer: {result.final_answer}")
        print(f"Run error:    {result.error}")
        print()

        rows = conn.execute(
            "SELECT seq, kind FROM events ORDER BY seq"
        ).fetchall()
        print(f"Rows in {DB_PATH}: {len(rows)}")
        for seq, kind in rows:
            print(f"  seq={seq:>2}  kind={kind}")
        print()
        print("Notice:")
        print("  - The 'broken' sink raised on every event but the run finished.")
        print("  - Its failures should have been printed to stderr (see above).")
        print("  - Every event still landed in SQLite via the good sink.")
    finally:
        # YOUR connection — YOU close it.
        conn.close()
        DB_PATH.unlink(missing_ok=True)


if __name__ == "__main__":
    asyncio.run(main())
