"""
================================================================
EXAMPLE 26 — "The executor seam: bring your own sandbox" (ADVANCED)
================================================================

SCENARIO:
    Policy decides WHETHER an action runs. The executor seam decides WHERE
    and HOW. By default, approved tools run in-process (same as always).
    Pass an Executor and every approved action — allow, transform,
    approval-granted — flows through your code instead: a subprocess, a
    Docker container, a cloud sandbox.

    Lynx ships the seam plus two executors (inline, subprocess-with-rlimits)
    and a per-tool router. Real isolation is YOURS to plug in — Python has
    no reliable in-language sandbox, so Lynx never pretends to be one.

WHAT THIS EXAMPLE SHOWS:
    - A custom Executor in ~6 lines (here: logs + tags every execution —
      stand-in for your Docker/E2B/gVisor wrapper)
    - route_executor: tools declare @tool(isolation="...") and run on
      different executors; undeclared tools take the default route
    - Fail-closed routing: a tool asking for an isolation level you didn't
      provide does NOT silently run on the host
    - Dry-runs bypass the seam (shadows are side-effect-free by contract)

RUN WITH:
    python examples/26_executor_seam.py
"""

from __future__ import annotations

import asyncio

from lynx import (
    ActionRequest,
    ActionResult,
    FinalAnswer,
    Message,
    ToolCall,
    ToolDef,
    ToolSet,
    compile_policy,
    inline_executor,
    route_executor,
    run_agent,
    tool,
)

# on_missing_shadow: allow — this demo's irreversible tools have no shadows
# and we want them to reach the EXECUTOR, which is the layer on display here.
POLICY = "version: 1\ndefaults: { on_no_match: allow, on_missing_shadow: allow }\nrules: []"


# ---------------------------------------------------------------------------
# Tools — the isolation= hint is how a tool asks for a specific executor.
# ---------------------------------------------------------------------------


@tool(reversible=True, scope=("compute:read",))
async def get_time() -> str:
    return "2026-06-11T12:00:00Z"


@tool(reversible=False, scope=("compute:exec",), isolation="container")
async def run_code(snippet: str) -> str:
    # Imagine this is LLM-generated code. You do NOT want it in-process.
    return f"(pretend output of {snippet!r})"


@tool(reversible=False, scope=("compute:exec",), isolation="microvm")
async def run_untrusted_binary(path: str) -> str:
    return f"(pretend ran {path})"


# ---------------------------------------------------------------------------
# A custom executor — the shape of your Docker/E2B/gVisor wrapper.
# One async callable: (request, tool) -> ActionResult. That's the seam.
# ---------------------------------------------------------------------------


def fake_container_executor() -> object:
    async def execute(request: ActionRequest, tool_def: ToolDef) -> ActionResult:
        # A real one would: docker run --rm --network=none -v workspace:...
        # and marshal request.args in / the result out. ~20 lines total —
        # see docs/integration-cookbook.md for a real Docker recipe.
        print(f"    [container] spinning up for {tool_def.name}({dict(request.args)})")
        value = await tool_def.fn(**dict(request.args))  # pretend it's inside
        return ActionResult(ok=True, value=f"[from container] {value}")

    return execute


class Scripted:
    def __init__(self, *actions):
        self._actions = list(actions)

    async def step(self, conv: tuple[Message, ...]):
        return self._actions.pop(0)


async def main() -> None:
    policy = compile_policy(POLICY)
    tools = ToolSet.from_functions(get_time, run_code, run_untrusted_binary)

    # The router: plain tools run inline; "container" tools run in the
    # (fake) container; note there is NO route for "microvm".
    executor = route_executor(
        {
            None: inline_executor(),
            "container": fake_container_executor(),
        }
    )

    agent = Scripted(
        ToolCall(tool="get_time", args={}, call_id="c1"),
        ToolCall(tool="run_code", args={"snippet": "print(1+1)"}, call_id="c2"),
        ToolCall(tool="run_untrusted_binary", args={"path": "/tmp/x"}, call_id="c3"),
        FinalAnswer(text="done — see what ran where"),
    )

    print("=" * 64)
    print("One run, three tools, three different execution destinations")
    print("=" * 64)

    seen = []

    async def sink(event):
        if event.kind in ("action.completed", "action.failed"):
            seen.append(event)

    result = await run_agent(
        agent,
        task="demo the seam",
        tools=tools,
        policy=policy,
        sinks=(sink,),
        executor=executor,
    )

    print(f"\n  final: {result.final_answer}")
    print("\n  What happened:")
    print("  - get_time            -> default route (inline, in-process)")
    print("  - run_code            -> 'container' route (your sandbox)")
    print("  - run_untrusted_binary-> isolation='microvm' has NO route:")
    print("                           failed CLOSED — it never ran on the host.")
    failed = [e for e in seen if e.kind == "action.failed"]
    print(f"\n  audit: {len(seen)} action outcomes, {len(failed)} failed-closed")
    if failed:
        print(f"  reason: {failed[0].body['reason'][:80]}")


if __name__ == "__main__":
    asyncio.run(main())
