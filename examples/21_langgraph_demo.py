"""
================================================================
EXAMPLE 21 — "LangGraph wrapped by Lynx" (INTEGRATIONS)
================================================================

SCENARIO:
    LangGraph users get policy mediation + audit by wrapping their
    compiled graph in `LangGraphAgent`. The graph's `ToolNode` calls
    surface as `ToolCall`s; Lynx mediates them; the result is fed back
    into the graph's `messages` channel.

WHAT THIS EXAMPLE SHOWS:
    - Wiring a minimal compiled LangGraph state graph through
      `LangGraphAgent`
    - The same `run_agent(...)` boundary you use everywhere else
    - The graph receiving the tool result message just as it would
      from a native `ToolNode`

REQUIRES:
    pip install lynx-agent[langgraph]
    pip install langchain-core

RUN WITH:
    python examples/21_langgraph_demo.py
"""

from __future__ import annotations

import asyncio
import sys
from typing import Annotated, TypedDict

from lynx import (
    ToolSet,
    auto_deny,
    compile_policy,
    run_agent,
    stdout_sink,
    tool,
)

try:
    from langchain_core.messages import AIMessage, BaseMessage, ToolMessage
    from langgraph.graph import END, START, StateGraph
    from langgraph.graph.message import add_messages

    from lynx.adapters.langgraph_adapter import LangGraphAgent
except ImportError as exc:
    sys.exit(
        "LangGraph deps missing. Install with:\n"
        "  pip install lynx-agent[langgraph]\n"
        "  pip install langchain-core\n"
        f"({exc})"
    )


# ---------------------------------------------------------------------------
# A tiny tool — Lynx mediates this through policy
# ---------------------------------------------------------------------------


@tool(reversible=True, scope=("compute:read",))
async def get_user(user_id: str) -> dict:
    """Look up a user by ID."""
    return {"id": user_id, "name": "Alice", "verified": True}


POLICY = """
version: 1
defaults: { on_no_match: deny }
rules:
  - id: allow-reads
    match: { declared.scope.contains: "compute:read" }
    decision: allow
"""


# ---------------------------------------------------------------------------
# A minimal LangGraph: one node emits a tool call, another finalizes
# ---------------------------------------------------------------------------


class GraphState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]


def call_tool(state: GraphState) -> GraphState:
    # First time we're called, the user message is the only thing in state.
    # Emit an AIMessage with a tool_call.
    if not any(isinstance(m, ToolMessage) for m in state["messages"]):
        return {
            "messages": [
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "get_user",
                            "args": {"user_id": "U-1"},
                            "id": "tc-1",
                        }
                    ],
                )
            ]
        }
    return {"messages": []}


def finalize(state: GraphState) -> GraphState:
    # After Lynx returns the tool result, summarize and stop.
    last = next(
        (m for m in reversed(state["messages"]) if isinstance(m, ToolMessage)),
        None,
    )
    text = f"got tool result: {last.content if last else '(missing)'}"
    return {"messages": [AIMessage(content=text)]}


def route_after_call(state: GraphState):
    if any(isinstance(m, ToolMessage) for m in state["messages"]):
        return "finalize"
    return END


def route_after_finalize(state: GraphState):
    return END


async def main() -> None:
    graph = StateGraph(GraphState)
    graph.add_node("call_tool", call_tool)
    graph.add_node("finalize", finalize)
    graph.add_edge(START, "call_tool")
    graph.add_conditional_edges("call_tool", route_after_call)
    graph.add_conditional_edges("finalize", route_after_finalize)

    compiled = graph.compile()
    agent = LangGraphAgent(compiled_graph=compiled)

    tools = ToolSet.from_functions(get_user)
    result = await run_agent(
        agent,
        task="look up user U-1",
        tools=tools,
        policy=compile_policy(POLICY),
        sinks=(stdout_sink(),),
        on_approval=auto_deny("not configured"),
    )
    print()
    print(f"Final answer: {result.final_answer}")
    print()
    print("Notice:")
    print("  - LangGraphAgent ran ONE graph step at a time")
    print("  - When call_tool emitted an AIMessage with tool_calls,")
    print("    Lynx mediated it through the policy (allow)")
    print("  - The ToolMessage was added back to the graph's messages list")
    print("  - finalize then ran with that ToolMessage in state and produced")
    print("    the final AIMessage Lynx returns as the FinalAnswer")


if __name__ == "__main__":
    asyncio.run(main())
