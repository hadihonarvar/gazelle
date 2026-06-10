# SDK and CLI Spec

The surface area users actually touch. Goal: a developer can be productive in 5 minutes without reading docs.

---

## Design rules

1. **The decorator is the front door.** `@runtime.tool` should look unsurprising and add zero friction.
2. **One concept per name.** `run`, `resume`, `replay`, `approve` — each does one thing.
3. **Async first, sync wrappers second.** Modern SDKs are async; we follow.
4. **CLI mirrors the Python API.** Whatever you can do in code, you can do from the shell.

---

## Public Python API

```python
# lynx/__init__.py
from lynx.runtime import Runtime, runtime         # global singleton + class
from lynx.decorators import tool, shadow
from lynx.policy import deny, allow, dry_run, approve_required, transform, rule
from lynx.types import (
    Task, Run, Step,
    ActionRequest, Decision, ActionResult, AuditEvent,
    Principal, Budget, ToolMetadata, ExecutionContext,
    Verdict, RunStatus,
)
```

### `@tool` — declare a callable as agent-invocable

```python
from lynx import tool

@tool(
    cost="low",
    reversible=False,
    scope=["filesystem:write"],
    blast_radius_hint=lambda cmd: estimate_files_affected(cmd),
)
async def shell(cmd: str) -> str:
    """Run a shell command and return stdout."""
    proc = await asyncio.create_subprocess_shell(
        cmd, stdout=PIPE, stderr=PIPE
    )
    out, err = await proc.communicate()
    return out.decode()
```

**Decorator parameters:**

| Param | Type | Required? | Notes |
|-------|------|-----------|-------|
| `cost` | `"low" | "medium" | "high"` | yes | Used for budget policies and prioritization |
| `reversible` | `bool` | yes | If False and no shadow, default is `approve_required` |
| `scope` | `list[str]` | yes | Free-form labels; common ones: `filesystem:read/write`, `db:read/write`, `net:egress`, `cloud:write` |
| `blast_radius_hint` | `Callable[..., int] | int | None` | no | Static int or function over args; called *before* execution |
| `name` | `str` | no | Defaults to function `__name__` |
| `description` | `str` | no | Defaults to docstring; passed to LLM as tool description |

### `@shadow` — dry-run twin

```python
@shell.shadow
async def _shell_shadow(cmd: str) -> dict:
    return {
        "would_run": cmd,
        "estimated_blast_radius": estimate_files_affected(cmd),
    }
```

When the PDP returns `dry_run`, the mediator calls `tool.shadow(**args)` instead of `tool(**args)`. The shadow's return value is what the agent sees as if it were the real result.

### `runtime.run` — durable, policy-gated execution

```python
result = await runtime.run(
    agent,                          # any object with .step(messages) -> ToolCall | FinalAnswer
    task="Refactor src/auth.py to use async",
    policy="./policy.yaml",
    budget={"usd": 5, "duration_seconds": 1800, "steps": 50},
    workspace="/Users/hadi/proj",
    environment="dev",
    principal={"kind": "user", "id": "hadi"},
)
print(result.final_answer)
print(result.run_id)               # for trace/replay later
```

Synchronous wrapper:

```python
result = runtime.run_sync(agent, task="...", policy="...")
```

### `runtime.resume` — continue a paused run

```python
result = await runtime.resume(resume_token="R-01HF...:T-tok")
```

### `runtime.replay` — debug or re-execute a past run

```python
# Inspect only
async for step in runtime.replay(run_id="R-01HF...", execute=False):
    print(step.seq, step.action, step.decision)

# Re-execute from a given step with edits
new_result = await runtime.replay(
    run_id="R-01HF...",
    from_step=8,
    edit={"args": {"cmd": "ls -la"}},
    execute=True,
)
```

### `runtime.approve` — resolve an approval request

```python
await runtime.approve(request_id="A-01HF...", approver="hadi")
await runtime.deny(request_id="A-01HF...", approver="hadi", reason="No.")
```

### `runtime.list_runs` / `runtime.get_run` / `runtime.get_steps`

Read-only queries used by the CLI and any future UI.

---

## Agent contract

The runtime wraps an `agent` object that exposes a single method:

```python
class Agent(Protocol):
    async def step(self, conversation: list[Message]) -> AgentAction:
        """Produce the next action given the conversation so far.

        Returns either ToolCall(tool, args) or FinalAnswer(text).
        """
```

This is the lowest common denominator — every framework can be wrapped into this shape with a small adapter. Direct users can implement it themselves in 10 lines.

```python
class SimpleAgent:
    def __init__(self, llm, tools):
        self.llm = llm
        self.tools = tools

    async def step(self, conversation):
        response = await self.llm.complete(
            messages=conversation,
            tools=self.tools,
        )
        if response.tool_call:
            return ToolCall(tool=response.tool_call.name,
                            args=response.tool_call.args)
        return FinalAnswer(text=response.content)
```

Adapters for LangGraph, CrewAI, OpenAI Agents SDK live in `lynx/adapters/` and conform to the same `Agent` protocol.

---

## CLI

Installed as `lynx` on PATH.

### Project setup

```
lynx init [--dir .]
```
Creates:
- `policy.yaml` with safe defaults
- `.lynx/state.db` (SQLite)
- `.lynx/audit/` (jsonl directory)
- `lynx.toml` config file

### Running

```
lynx run <python-file> [--task "..."] [--policy ./policy.yaml] [--env dev]
```

Equivalent to importing the file, finding the `agent` and calling `runtime.run(agent, task=...)`.

### Inspecting

```
lynx ps                          # active + recent runs
lynx trace <run-id>              # step-by-step trace
lynx audit verify <run-id>       # check hash chain
lynx audit export <run-id> > audit.jsonl
```

### Approvals + Resume

```
lynx approvals                            # list pending
lynx approve <approval-id> [--approver ...]
lynx deny <approval-id> [--approver ...] [--reason ...]
lynx resume <run-id> <script>             # resume a paused run after approval
```

### Policy

```
lynx policy lint [policy.yaml]            # compile-check the policy file
lynx policy bundle-id [policy.yaml]       # print content-addressed bundle ID
```

### Version

```
lynx --version
```

### On the v1.x roadmap (not yet implemented)

| Command | What it'd do |
|---------|-------------|
| `lynx replay <run-id> --from-step N --edit ...` | Re-execute from any past step with optional edits |
| `lynx show <run-id>` | Full run details (status, principal, task, error) |
| `lynx trace <run-id> --tail` | Follow a running run live |
| `lynx policy show` | Pretty-print the compiled bundle |
| `lynx policy test fixtures/` | Run fixture-based policy tests |
| `lynx config` | Show effective config (env vars overlaid on toml) |
| `lynx db migrate` | Apply schema migrations across backend changes |

---

## Exit codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | User error (bad args, missing files) |
| 2 | Policy denied the action / run |
| 3 | Budget exhausted |
| 4 | Approval timeout |
| 5 | Crash / unhandled exception |
| 6 | Audit chain integrity failure |

CI-friendly: `lynx run` returns 2 if any action was denied; 3 if budget was hit; 0 only on clean success.

---

## Config file (`lynx.toml`)

```toml
[storage]
type = "sqlite"
path = ".lynx/state.db"

[audit]
path = ".lynx/audit/"
signing = "none"           # or "hsm" later

[policy]
path = "./policy.yaml"
include_python = ["./policy_rules.py"]

[runtime]
default_environment = "dev"
default_workspace = "."
log_level = "info"

[approvals]
transport = "cli"          # or "webhook" / "slack" later
default_timeout_seconds = 1800
```

Every value can be overridden by env var: `AGENT_RUNTIME_STORAGE_PATH`, etc.

---

## What the SDK deliberately does NOT do

- **No conversation management.** The agent owns its own conversation buffer.
- **No prompt templating.** Bring your own.
- **No retry/backoff for LLM calls.** That's the adapter's problem.
- **No cost calculation for tool results.** Costs are declared in `@tool`, summed by the kernel.
- **No automatic tool generation from OpenAPI/MCP.** Adapters do that; the SDK accepts already-wrapped tools.

These cuts keep the SDK at one job: making the *runtime* easy to use.
