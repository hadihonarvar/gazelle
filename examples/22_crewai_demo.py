"""
================================================================
EXAMPLE 22 — "CrewAI wrapped by Lynx" (INTEGRATIONS)
================================================================

SCENARIO:
    CrewAI orchestrates a multi-agent crew internally via `kickoff()`.
    `CrewAIAgent` is a single-shot wrapper: the first `step()` runs the
    whole crew and returns the result as `FinalAnswer`; subsequent
    `step()` calls return the cached answer.

    Lynx's per-tool mediation cannot reach inside the crew's internal
    orchestration. For per-tool policy enforcement, prefer wrapping each
    of your CrewAI tools as a Lynx `@tool` and bundling them into a
    `ToolSet` directly. Use `CrewAIAgent` only when you need the full
    crew orchestration but still want the run boundary + audit trail.

WHAT THIS EXAMPLE SHOWS:
    - Wrapping a CrewAI `Crew` in `CrewAIAgent`
    - The crew's final answer surfacing as Lynx's `FinalAnswer`
    - Why CrewAIAgent is single-shot — the docstring's tradeoff,
      made explicit

REQUIRES:
    pip install lynx-agent[crewai]

RUN WITH:
    python examples/22_crewai_demo.py
"""

from __future__ import annotations

import asyncio
import sys

from lynx import (
    ToolSet,
    auto_deny,
    compile_policy,
    run_agent,
    stdout_sink,
)

try:
    from crewai import Agent as CrewAgent
    from crewai import Crew, Task

    from lynx.adapters.crewai_adapter import CrewAIAgent
except ImportError as exc:
    sys.exit(f"CrewAI not importable. Install with: pip install lynx-agent[crewai]\n({exc})")


POLICY = "version: 1\ndefaults: { on_no_match: allow }\nrules: []"


async def main() -> None:
    # A tiny crew that doesn't need any tools — its kickoff returns a
    # short answer. Replace with your real CrewAI Crew.
    researcher = CrewAgent(
        role="Researcher",
        goal="Answer a single question with one sentence.",
        backstory="You are concise.",
        verbose=False,
        allow_delegation=False,
    )
    task = Task(
        description="What's the capital of France?",
        expected_output="One sentence.",
        agent=researcher,
    )
    crew = Crew(agents=[researcher], tasks=[task], verbose=False)

    agent = CrewAIAgent(crew=crew)

    # No tools needed — the crew handles its own. We still pass an empty
    # ToolSet so the run_agent boundary stays the same.
    result = await run_agent(
        agent,
        task="crewai demo",
        tools=ToolSet(),  # empty — the crew is self-contained
        policy=compile_policy(POLICY),
        sinks=(stdout_sink(),),
        on_approval=auto_deny("not used"),
    )
    print()
    print(f"Final answer: {result.final_answer}")
    print()
    print("Notice:")
    print("  - CrewAIAgent is SINGLE-SHOT — the crew's kickoff happens in")
    print("    the first step(), then the cached result is returned by any")
    print("    subsequent step(). The Lynx event loop ran exactly one mediation.")
    print("  - The crew's internal tool calls were NOT mediated by Lynx;")
    print("    that's the tradeoff this adapter makes vs. wrapping each tool")
    print("    individually.")


if __name__ == "__main__":
    asyncio.run(main())
