# Concepts

Vocabulary for Lynx v2 in one page.

---

## Tool

An async function decorated with `@tool`. Attaches metadata via `__lynx_meta__`. Does not register globally.

```python
@tool(reversible=False, scope=("filesystem:write",))
async def shell(cmd: str) -> str: ...
```

A tool can have a `.shadow` twin — same signature, no side effects, used when policy returns `dry_run`.

## ToolSet

An immutable, explicit collection of tools. Built at the call site.

```python
tools = ToolSet.from_functions(shell, write_file, delete_file)
```

Operations return new ToolSets: `.with_tool(...)`, `.without_tool(...)`, `.union(...)`. Never mutated.

## ActionRequest

The agent's proposed tool call, normalized for policy evaluation. Frozen.

## Verdict

The five possible policy outcomes:

| Verdict | What the kernel does |
|---------|---------------------|
| `allow` | Calls the real tool function |
| `deny` | Returns a denial; agent sees `[denied]` as a tool result |
| `dry_run` | Calls the tool's `.shadow` twin; returns preview as the result |
| `approve_required` | Calls `on_approval(req)`; runs the action if granted |
| `transform` | Runs the tool with rewritten arguments |

## Decision

Frozen dataclass returned by the PDP. Includes the verdict, reason, matched rule IDs, and optional approvers / timeout / transform_args.

## Policy

A YAML document plus optional Python rules, compiled into a `PolicyBundle`. The bundle has a content-addressed `id` (sha256-prefix of canonical JSON of its rules). Pass to `run_agent` for the kernel to consult.

## PolicyBundle

Frozen, immutable. The `id` is a deterministic hash; equal bundles have equal IDs. Surfaced in every event for attestation.

## PDP

The Policy Decision Point: `evaluate(bundle, request, context) -> Decision`. Pure function. Same inputs → same Decision. No I/O.

## Mediator

The Policy Enforcement Point: `mediate(request, decision, tools, on_approval) -> ActionResult`. Pure async function that dispatches by verdict.

## Run

Conceptually, one execution of `run_agent`. Not a stored entity — there is no `Run` class in v2. Each call generates a `correlation_id` (UUID4) that ties all its events together.

## RunResult

Minimal frozen dataclass returned by `run_agent`:

```python
@dataclass(frozen=True, slots=True)
class RunResult:
    correlation_id: str
    bundle_id: str
    final_answer: str | None
    error: str | None
    steps_taken: int
```

No history. No event list. No persistent state.

## Sink

A callable taking one `AuditEvent` at a time. Lynx never buffers; sinks are fired per event.

```python
async def my_sink(event: AuditEvent) -> None: ...
```

Built-in: `stdout_sink`, `jsonl_sink`, `noop_sink`, `multi_sink`, `callback_sink`.

## ApprovalHandler

A callable taking one `ApprovalRequest` and returning an `ApprovalDecision`. Called synchronously by the kernel when policy returns `approve_required`.

```python
async def my_handler(req: ApprovalRequest) -> ApprovalDecision: ...
```

Built-in: `auto_approve`, `auto_deny`, `cli_prompt_approval`, `callback_approval`.

## AuditEvent

What the sinks receive. Frozen. Minimal.

```python
@dataclass(frozen=True, slots=True)
class AuditEvent:
    correlation_id: str       # UUID4 grouping events from one run
    bundle_id: str            # policy hash in effect
    seq: int                  # monotonic within the run
    kind: str                 # "step.proposed" / "policy.evaluated" / ...
    timestamp: datetime
    body: Mapping[str, Any]
```

No hash chain. No content addressing. Your sink decides retention.

## Event kinds

| Kind | When emitted |
|------|-------------|
| `run.started` | At the start of `run_agent` |
| `step.proposed` | Agent returned a `ToolCall` |
| `policy.evaluated` | PDP returned a Decision |
| `action.started` | Real tool about to run (allow / transform / approval-granted) |
| `action.dry_run` | Shadow about to run |
| `action.completed` | Tool returned ok |
| `action.failed` | Tool raised or denial |
| `action.denied` | Policy denial path |
| `approval.requested` | `approve_required` verdict |
| `approval.granted` | Handler returned `granted=True` |
| `approval.denied` | Handler returned `granted=False` |
| `run.succeeded` | Agent returned FinalAnswer |
| `run.failed` | Budget exhausted / agent.step raised |

## Principal

Frozen. Who the agent is acting on behalf of.

```python
Principal(kind="user" | "service" | "agent", id="...", name="...")
```

## Budget

Frozen. Hard caps the kernel enforces.

```python
Budget(steps=50, duration_seconds=600, usd=..., tokens=...)
```

## ExecutionContext

Frozen. Set by the kernel for each step:

```python
ExecutionContext(principal, environment, workspace, correlation_id, step_seq, timestamp, extra)
```

Policy rules can match on any field via `context.<field>`.

## Agent protocol

The single contract every agent must satisfy:

```python
class Agent(Protocol):
    async def step(self, conversation: tuple[Message, ...]) -> ToolCall | FinalAnswer: ...
```

The runtime never mutates the conversation; each step rebinds the tuple. No buffer is held outside the function.

## How the pieces fit

```
       Agent                              Real world
         │                                    ▲
         │ ToolCall                           │ ActionResult
         ▼                                    │
   ┌──────────────────────────────────────────────────────┐
   │  run_agent (single pure async function)             │
   │      build ActionRequest                            │
   │            ▼                                         │
   │      PDP → Decision           (pure)                │
   │            ▼                                         │
   │      Mediator (PEP)            (pure async)         │
   │            ▼  emit events                            │
   │      Sinks: stdout / jsonl / OTel / yours            │
   └──────────────────────────────────────────────────────┘
```

No `Runtime` class. No `Scheduler` class. No `ApprovalBroker`. No globals.
