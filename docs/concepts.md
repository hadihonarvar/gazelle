# Concepts

Plain-language definitions of every Lynx term that appears in policies, code, or the CLI. Read this once and the rest of the docs make sense.

---

## Tool

A Python async function decorated with `@tool`. It does *one thing*: deletes a file, sends an HTTP request, queries a database. Tools declare three pieces of metadata that the policy engine reads:

```python
@tool(cost="low", reversible=False, scope=["filesystem:write"])
async def shell(cmd: str) -> str: ...
```

- **`cost`**: `"low" | "medium" | "high"` — for budget enforcement
- **`reversible`**: `bool` — `False` means undoing the side effect is impossible / expensive
- **`scope`**: tuple of free-form labels like `"filesystem:write"`, `"db:write"`, `"net:egress"` that policy rules can match on

A tool can also have a **`.shadow`** — a twin function that produces a preview without actually doing the thing. Used for `dry_run` verdicts.

## ActionRequest

What the agent *wants to do*. Built automatically by the scheduler when the agent proposes a `ToolCall`:

```
ActionRequest(tool="shell", args={"cmd": "rm -rf /"}, declared=<metadata>, context=<...>)
```

Nothing happens to the world until the policy decides what to do with the request.

## Verdict

The five possible outcomes of policy evaluation:

| Verdict | What it means | What the kernel does |
|---------|--------------|---------------------|
| **`allow`** | Run as proposed | Calls the real tool |
| **`deny`** | Refuse | Returns a structured denial to the agent ("you tried X, was denied because Y"); the agent can try a different approach |
| **`dry_run`** | Preview only | Calls `tool.shadow()` instead of `tool()`; the agent sees the preview as if it were the real result |
| **`approve_required`** | Wait for a human | Pauses the run, persists the request, emits an approval event; resumes when an approver grants it |
| **`transform`** | Run with different args | The kernel substitutes new args (e.g. add `WHERE tenant_id=X` to a SQL query) and runs the tool |

## Decision

The output of the policy engine. Pure data: a verdict + a human-readable reason + which rules matched + any extras (approvers, transform args).

## Policy

A YAML file. Says what to do for each kind of `ActionRequest`. Three tiers of expressiveness:

1. **Declarative YAML rules** — covers ~80% of cases
2. **Reusable named predicates** — for repeated patterns
3. **Python escape hatch** — `@policy.rule` for edge cases

```yaml
rules:
  - id: block-rm-root
    match:
      tool: shell
      args.cmd.matches: '^\s*rm\s+(-[rRf]+\s+)+/(\s|$)'
    decision: deny
    reason: "rm -rf / is hard-blocked"
```

Policies are **content-addressed**: the bundle gets a SHA hash at compile time. Tasks pin themselves to the bundle ID at creation, so policy changes don't affect runs already in flight.

## Run

One execution attempt of a `Task`. Has a state machine: `pending → running → (paused →) succeeded | failed | cancelled`.

A `Run` is identified by a ULID prefixed with `R-`. You'll see these in CLI output and audit exports.

## Step

One iteration of the agent loop:

```
model call → ActionRequest → policy → Decision → mediator → ActionResult → checkpoint
```

A `Step` has a sequence number (monotonic per run) and a checkpoint blob containing the conversation state. Crash recovery + idempotent resume work because every step writes a checkpoint *before* its side effect.

## Mediator (PEP — Policy Enforcement Point)

The chokepoint. Every action passes through it. Given a `Decision`, it dispatches:

- `allow` → calls the tool
- `deny` → raises `ToolDenied`
- `dry_run` → calls the tool's shadow
- `approve_required` → opens an approval and raises `ApprovalPending`
- `transform` → calls the tool with substituted args

## PDP (Policy Decision Point)

The pure function that turns `(PolicyBundle, ActionRequest, ExecutionContext)` into a `Decision`. No I/O, no network, no clocks. Deterministic. Replay-friendly.

## AuditEvent

One entry in the append-only, hash-chained audit log. Identified by `sha256(prev || canonical_json(body))`. Includes events like `run.started`, `step.proposed`, `policy.evaluated`, `action.completed`, `approval.granted`, `run.succeeded`.

You can verify the chain anytime: `lynx audit verify <run-id>`. Tampering — body changes, missing events, hash mismatches — is detectable.

## Approval

When the policy returns `approve_required`, the kernel:

1. Persists an `ApprovalRequest` to the store
2. Pauses the run
3. Returns control to the caller with a `paused_approval_id`

A human then calls `lynx approve <approval-id>` (or hits a webhook). When the agent is re-invoked with `runtime.resume(run_id)`, the approved action executes and the loop continues.

## Sandbox

Optional isolation for individual tools. Today: `none` (in-process) or `subprocess` (fresh Python interpreter, stripped env, ulimits, timeout). Container mode is planned for v0.8.

## Store

Where Lynx persists Tasks, Runs, Steps, AuditEvents, and Approvals. SQLite by default (zero infrastructure). Postgres for production. The interface is the same; swap via config.

## Agent

Anything that satisfies the `Agent` protocol — one method, `async def step(conversation: list[Message]) -> ToolCall | FinalAnswer`. The runtime drives the loop; the agent decides what to do next.

Built-in adapters wrap Anthropic, OpenAI, LangGraph, CrewAI, and MCP servers into this shape. Bring your own works too.

## Shadow

A side-effect-free twin of a tool. Returns a preview of what the action *would* do. Required when the PDP returns `dry_run`. Pre-built shadows ship for `shell`, `write_file`, `delete_file`, `sql`, `http`.

## Principal

Who the agent is acting on behalf of: `Principal(kind="user|service|agent", id="...")`. Policy rules can match on this; audit events include it.

## Budget

Hard caps the scheduler enforces: `usd`, `tokens`, `duration_seconds`, `steps`. Defaults are sane (50 steps, 600 seconds, no money cap).

## ExecutionContext

The per-action metadata passed to the PDP: `principal`, `environment` (`"dev" / "prod"`), `workspace`, `run_id`, `step_seq`, `timestamp`, plus an `extra` dict for operator-defined fields. Policy rules match on context fields too.

---

## How the pieces fit together

```
       Agent                         Real world
         │                                ▲
         │ ToolCall                       │ ActionResult
         ▼                                │
   ┌──────────────────────────────────────────────────────┐
   │  Scheduler                                           │
   │     │  build ActionRequest                           │
   │     ▼                                                │
   │  PDP  ──► Decision                                   │
   │     │                                                │
   │     ▼                                                │
   │  Mediator (PEP)                                      │
   │     │  allow / deny / dry_run / approve / transform  │
   │     ▼                                                │
   │  Tool function (in process or sandbox)               │
   │     │                                                │
   │     ▼                                                │
   │  Store: Step + Checkpoint + AuditEvent               │
   └──────────────────────────────────────────────────────┘
```

Three trust boundaries:

1. **Agent → ActionRequest** — agent is untrusted; the request shape is normalized so policy can reason about it
2. **PDP → Decision** — policy decides verdict from the request
3. **Mediator → Action** — the only place real-world side effects happen, and they only happen if the Decision was `allow` (or `dry_run` for shadows, or `transform` for rewritten args)

Read [`docs/threat-model.md`](threat-model.md) for the full STRIDE analysis.
