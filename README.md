# Lynx

**A stateless, type-safe policy kernel for AI agent tool calls.**

Pure functions over immutable values. No database. No globals. No leaks. Five verdicts. Streaming events to user-owned sinks.

```python
from lynx import (
    FinalAnswer, Message, ToolCall, ToolSet, tool,
    compile_policy, run_agent, stdout_sink, auto_deny,
)

@tool(reversible=False, scope=("filesystem:write",))
async def shell(cmd: str) -> str:
    proc = await asyncio.create_subprocess_shell(cmd, ...)
    return (await proc.communicate())[0].decode()

result = await run_agent(
    my_agent,
    task="clean up old logs",
    tools=ToolSet.from_functions(shell),
    policy=compile_policy(open("policy.yaml").read()),
    sinks=(stdout_sink(),),
    on_approval=auto_deny("no approvals configured"),
)
# result: { correlation_id, final_answer, error, steps_taken, bundle_id }
# Lynx holds NOTHING. No DB. No state. No leaks.
```

## What v2 does

- **Policy-gated execution** at the tool-call boundary. Five verdicts: `allow / deny / dry_run / approve_required / transform`.
- **Streaming events** to your sinks. We never store events — your sink can buffer, write to disk, ship to OTel, post to a webhook, whatever you choose.
- **Pure functions everywhere.** The kernel is one function: `run_agent(agent, task, *, tools, policy, sinks, on_approval, ...)`. No `Runtime` class. No singleton.
- **Immutable values.** Every public type is `frozen=True, slots=True`. Mutation raises at runtime; `mypy --strict` catches it at write time.
- **No globals.** No tool registry, no broker, no module-level state. ToolSet is built explicitly at call site.
- **Hot-reloadable policy.** Because we hold no state.

## What v2 does NOT do

- **No durability layer** — that's [Temporal](https://temporal.io). v2 does not survive a process restart.
- **No audit storage** — your sink decides where events go. We never open a file.
- **No prompt filtering** — that's [NeMo Guardrails](https://github.com/NVIDIA/NeMo-Guardrails) or [Guardrails AI](https://github.com/guardrails-ai/guardrails).
- **No cluster orchestration** — that's [Temporal](https://temporal.io) or [Inngest](https://www.inngest.com).
- **No agent framework** — that's [LangGraph](https://langchain-ai.github.io/langgraph/) / [CrewAI](https://www.crewai.com); we wrap them via adapters.

## Install

```bash
pip install lynx-agent                    # core (3 deps)
pip install lynx-agent[anthropic]         # Claude adapter
pip install lynx-agent[openai]            # GPT adapter
pip install lynx-agent[langgraph]
pip install lynx-agent[crewai]
pip install lynx-agent[mcp]
```

## Quickstart

```bash
pip install lynx-agent
lynx init           # writes one file: policy.yaml
python examples/01_hello_allow.py
```

## How it works

```
                ┌────────────────────────────────────────────┐
                │  Agent (any framework)                     │
                └──────────────────┬─────────────────────────┘
                                   │  ToolCall
                                   ▼
              ╔═══════════════════════════════════════════╗
              ║  run_agent (pure function)                ║
              ║   1. PDP evaluates → Decision             ║
              ║   2. Mediator dispatches by verdict       ║
              ║   3. Sinks called with each AuditEvent    ║
              ║   4. Approval handler called sync if needed║
              ╚═══════════════════════════════════════════╝
                                   │ side effect
                                   ▼
                ┌────────────────────────────────────────────┐
                │  Real world                                │
                └────────────────────────────────────────────┘
```

Each agent step:
1. Build `ActionRequest` from the agent's `ToolCall`
2. `evaluate(policy, request, context)` returns a `Decision` (pure function)
3. `mediate(request, decision, tools, on_approval)` dispatches
4. Each step emits a few events; sinks consume them
5. Result is appended to a new `conversation` tuple; old tuple is freed

## Policy YAML — unchanged from v1

```yaml
version: 1
defaults:
  on_no_match: deny
  on_missing_shadow: approve_required

rules:
  - id: block-rm-rf-root
    match:
      tool: shell
      args.cmd.matches: '^\s*rm\s+(-[rRf]+\s+)+/(\s|$)'
    decision: deny
    reason: "rm -rf / is hard-blocked"

  - id: writes-need-approval
    match:
      declared.scope.contains: filesystem:write
    decision: approve_required
    approvers: ["sre-oncall"]
```

Or in Python:

```python
from lynx.policy import deny

def block_paths_outside_workspace(req, ctx):
    if req.tool != "shell":
        return None
    if path_escapes(req.args["cmd"], ctx.workspace):
        return deny("path escapes workspace")
    return None

bundle = compile_policy(
    yaml_source,
    python_rules=(block_paths_outside_workspace,),
)
```

## Sinks — the audit replacement

```python
from lynx import stdout_sink, jsonl_sink, multi_sink

# Pretty-print + persist to jsonl in one go
with open("audit.jsonl", "a") as f:
    sink = multi_sink(stdout_sink(), jsonl_sink(f))
    await run_agent(..., sinks=(sink,))
# File is yours. You close it. You rotate it. You ship it where you want.
```

Built-in sinks:

| Sink | What it does |
|------|-------------|
| `stdout_sink(stream=...)` | Pretty-print events |
| `jsonl_sink(handle)` | One JSON line per event |
| `noop_sink()` | Discard (for tests) |
| `multi_sink(*sinks)` | Fan out concurrently |
| `callback_sink(fn)` | Wrap any async callable |

Write your own — it's just `async def __call__(event: AuditEvent) -> None`.

## Approvals — synchronous handlers

```python
from lynx import cli_prompt_approval, callback_approval, ApprovalDecision

# Built-in: prompt on stdin
await run_agent(..., on_approval=cli_prompt_approval())

# Or bring your own
async def slack_approval(req):
    msg = await slack.post(f"Approve {req.request.tool}?")
    button = await slack.wait_for_click(msg, timeout=3600)
    return ApprovalDecision(granted=button == "approve", approver=button.user)

await run_agent(..., on_approval=callback_approval(slack_approval))
```

The `run_agent` call blocks on the handler. No queue. No broker. No cross-process resume. Your handler decides how to wait.

## Examples

| # | File | What it shows |
|---|------|--------------|
| 01 | [`01_hello_allow.py`](examples/01_hello_allow.py) | Smallest possible run |
| 02 | [`02_block_dangerous.py`](examples/02_block_dangerous.py) | DENY for `rm -rf /` |
| 03 | [`03_preview_writes.py`](examples/03_preview_writes.py) | DRY_RUN with file shadow |
| 04 | [`04_human_approval.py`](examples/04_human_approval.py) | Sync approval via stdin |
| 05 | [`05_real_llm_blocked.py`](examples/05_real_llm_blocked.py) | Real Claude / GPT |
| 06 | [`06_streaming_to_jsonl.py`](examples/06_streaming_to_jsonl.py) | Audit replacement: jsonl sink |
| 07 | [`07_refund_workflow.py`](examples/07_refund_workflow.py) | Multi-tier refund rules |
| 08 | [`08_sql_transform.py`](examples/08_sql_transform.py) | TRANSFORM verdict |
| 09 | [`09_fastapi_service.py`](examples/09_fastapi_service.py) | FastAPI integration |
| 10 | [`10_devops_assistant.py`](examples/10_devops_assistant.py) | All five verdicts |
| 11 | [`11_flask_service.py`](examples/11_flask_service.py) | Flask integration |
| 12 | [`12_django_service.py`](examples/12_django_service.py) | Django integration |

## CLI — five commands

```
lynx --version
lynx init                        # writes policy.yaml (only)
lynx run <script>                # runs an async main()
lynx policy lint                 # validates a YAML
lynx policy bundle-id            # content-addressed ID
```

## Migrating from v1.x

v1's `Runtime`, `runtime.run/resume/approve/deny`, SQLite store, audit chain, and approval broker are all gone. Replace:

| v1 | v2 |
|----|-----|
| `runtime.run(agent, task=...)` | `run_agent(agent, task, tools=..., policy=..., sinks=..., on_approval=...)` |
| `runtime.resume(run_id)` | Doesn't exist — restart is restart. Pause in your handler instead. |
| `runtime.approve(approval_id)` | Doesn't exist — handler returns `ApprovalDecision` synchronously |
| `runtime.audit_chain(run_id)` | Doesn't exist — wire `jsonl_sink` or your own sink |
| `get_registry()` | Doesn't exist — `ToolSet.from_functions(*decorated_fns)` |
| `enable_otel()` | Will land as `otel_sink(tracer)` in v2.1 |
| `lynx ps / trace / audit / resume / approvals` | All gone — your sink owns the story |

If you need any of those primitives, **pin v1.0.x:**

```bash
pip install "lynx-agent<2.0"
```

v1 will keep getting security fixes per the SECURITY.md policy.

## Status

**v2.0 — public API committed.** SemVer from here. Production-ready for the documented scope.

## Design

- [`docs/v2-rfc.md`](docs/v2-rfc.md) — the formal RFC this implementation follows
- [`docs/concepts.md`](docs/concepts.md) — vocabulary
- [`docs/cookbook.md`](docs/cookbook.md) — policy patterns
- [`docs/faq.md`](docs/faq.md) — common questions

## License

Apache 2.0.
