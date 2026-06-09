# Data Model Spec

The six core types. Everything else in the system is a function over these.

---

## Identifiers

All IDs are **ULIDs** (26 chars, lexicographically sortable, time-prefixed). Prefix by entity:

- `T-01HFXY...` Task
- `R-01HFXY...` Run
- `S-01HFXY...` Step
- `A-01HFXY...` ApprovalRequest
- `E-01HFXY...` AuditEvent

The prefix is purely human-friendly; the kernel never parses it.

---

## Type 1: `Task`

The user's stated goal. Created once, may have many `Run`s if retried.

```python
@dataclass(frozen=True, slots=True)
class Task:
    id: str
    goal: str                       # natural-language objective
    created_at: datetime
    created_by: Principal
    policy_bundle_id: str           # hash of the compiled policy at task-creation time
    budget: Budget
    metadata: dict[str, Any] = field(default_factory=dict)
```

**Invariants:**
- `id` is immutable.
- `policy_bundle_id` is pinned at creation — policy changes mid-run do not affect in-flight tasks.
- `budget` is a hard cap; the scheduler enforces it.

**Lifecycle:**
- Created → spawns Run(s) → terminal when last Run is terminal.

---

## Type 2: `Run`

One execution attempt of a `Task`. Has a state machine.

```python
class RunStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"            # waiting for human approval
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"

@dataclass
class Run:
    id: str
    task_id: str
    status: RunStatus
    started_at: datetime
    ended_at: datetime | None
    resume_token: str | None     # populated when PAUSED
    last_step_seq: int           # for resume + idempotency
    error: str | None
```

**Status transitions:**

```
PENDING → RUNNING → SUCCEEDED
                 → FAILED
                 → PAUSED → RUNNING (resume)
                         → CANCELLED
                 → CANCELLED
```

**Invariants:**
- `last_step_seq` is monotonically increasing.
- Only `PAUSED` runs may have a non-null `resume_token`.
- `ended_at` is set iff status is terminal (SUCCEEDED/FAILED/CANCELLED).

---

## Type 3: `Step`

One iteration of the agent loop: a model call producing an action, the decision about that action, and the outcome.

```python
@dataclass
class Step:
    id: str
    run_id: str
    seq: int                         # 0-indexed, monotonic within run
    model_call: ModelCall | None     # None for resumed/synthetic steps
    action: ActionRequest | None     # None if the model produced a final answer
    decision: Decision | None
    result: ActionResult | None
    checkpoint_blob: bytes           # serialized state after this step
    started_at: datetime
    ended_at: datetime
```

**Step lifecycle (sub-states, not persisted as a field but visible in journal events):**

1. `proposed` — model produced an action, mediator hasn't decided yet
2. `decided` — decision recorded
3. `executing` — action in flight
4. `completed` — result recorded, checkpoint saved

The journal records each transition as an `AuditEvent`. The persisted `Step` only stores the final state plus the checkpoint.

**Invariants:**
- `seq` is unique per `run_id`.
- If `decision.verdict == "deny"`, then `result is None` and the model loop continues with a denial message.
- Checkpoint is written **before** `result.ok = true` is committed (so crash recovery never double-executes a successful action).

---

## Type 4: `ActionRequest`

A *proposed* tool invocation. The Mediator receives this from the adapter, asks the PDP for a Decision, and routes accordingly.

```python
@dataclass(frozen=True, slots=True)
class ActionRequest:
    tool: str                        # registered tool name, e.g. "shell"
    args: dict[str, Any]             # JSON-serializable
    declared: ToolMetadata           # cost, reversibility, scope, blast_radius hint
    context: ExecutionContext        # principal, env, run_id, step_seq, workspace
    idempotency_key: str             # H(run_id || seq || tool || canonical(args))
```

```python
@dataclass(frozen=True, slots=True)
class ToolMetadata:
    cost: Literal["low", "medium", "high"]
    reversible: bool
    scope: tuple[str, ...]           # e.g. ("filesystem:write", "net:egress")
    blast_radius_hint: int | None    # optional pre-execution estimate
    has_shadow: bool                 # whether dry-run is supported

@dataclass(frozen=True, slots=True)
class ExecutionContext:
    principal: Principal             # who the agent is acting as
    environment: str                 # e.g. "dev", "staging", "prod"
    workspace: str                   # absolute path; tools relative to this
    run_id: str
    step_seq: int
    timestamp: datetime
    extra: dict[str, Any] = field(default_factory=dict)
```

**Invariants:**
- `idempotency_key` is deterministic — same `(run_id, seq, tool, args)` always produces the same key.
- `context.timestamp` is set by the kernel, not the tool.

---

## Type 5: `Decision`

The PDP's verdict on an `ActionRequest`. Pure output of policy evaluation.

```python
class Verdict(StrEnum):
    ALLOW = "allow"
    DENY = "deny"
    DRY_RUN = "dry_run"
    APPROVE_REQUIRED = "approve_required"
    TRANSFORM = "transform"

@dataclass(frozen=True, slots=True)
class Decision:
    verdict: Verdict
    reason: str                      # human-readable, shown to user + model
    matched_rules: tuple[str, ...]   # rule IDs that fired
    approvers: tuple[str, ...] = ()  # if APPROVE_REQUIRED
    transform_args: dict[str, Any] | None = None  # if TRANSFORM
    timeout_seconds: int | None = None            # if APPROVE_REQUIRED
```

**Semantics:**
- `ALLOW` → execute as-is
- `DENY` → do not execute; feed reason back to the model
- `DRY_RUN` → call `tool.shadow()`; result is the preview, not the real effect
- `APPROVE_REQUIRED` → suspend run; emit ApprovalRequest; resume on approval, deny on timeout
- `TRANSFORM` → execute with `transform_args` instead of original args

The Mediator interprets the verdict. The PDP never executes.

---

## Type 6: `AuditEvent`

The append-only, hash-chained, optionally signed record of *everything*. The source of truth for compliance, replay, and debugging.

```python
@dataclass(frozen=True, slots=True)
class AuditEvent:
    id: str                          # = sha256(prev || canonical_json(body))
    prev: str                        # previous event's id; "0"*64 for genesis
    run_id: str
    seq: int                         # monotonic within run
    kind: str                        # see Event Kinds below
    timestamp: datetime
    body: dict[str, Any]             # event-specific payload
    signature: bytes | None = None   # only set when audit signing enabled
```

### Event Kinds

| Kind | When emitted |
|------|-------------|
| `run.started` | New Run created |
| `step.proposed` | Adapter submitted ActionRequest |
| `policy.evaluated` | PDP returned Decision |
| `approval.requested` | Verdict was APPROVE_REQUIRED |
| `approval.granted` | Human approved |
| `approval.denied` | Human denied or timed out |
| `action.dry_run` | Shadow execution started |
| `action.started` | Real execution started |
| `action.completed` | Execution returned result |
| `action.failed` | Execution raised |
| `checkpoint.written` | Step state persisted |
| `run.paused` | Run entered PAUSED |
| `run.resumed` | Run exited PAUSED |
| `run.succeeded` / `run.failed` / `run.cancelled` | Terminal transition |

**Invariants:**
- `id` is content-addressed; recomputing it from `prev || canonical_json(body)` MUST equal the stored value. Mismatch = tamper detection.
- `prev` chains backwards to the genesis event of each Run. Verifier walks the chain.
- `canonical_json` uses RFC 8785 (JCS) — sorted keys, no whitespace, normalized numbers.

---

## Supporting Types

```python
@dataclass(frozen=True, slots=True)
class Principal:
    kind: Literal["user", "service", "agent"]
    id: str                          # email, service account, agent name
    name: str | None = None

@dataclass(frozen=True, slots=True)
class Budget:
    usd: float | None = None
    duration_seconds: int | None = None
    tokens: int | None = None
    steps: int | None = None

@dataclass(frozen=True, slots=True)
class ModelCall:
    provider: str                    # "openai", "anthropic", "google", ...
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    duration_ms: int
    prompt_hash: str                 # for replay determinism check

@dataclass(frozen=True, slots=True)
class ActionResult:
    ok: bool
    value: Any | None = None         # tool return value (must be JSON-serializable)
    error: str | None = None
    duration_ms: int = 0
    side_effects: list[str] = field(default_factory=list)  # tool-reported, e.g. ["wrote 3 files"]
```

---

## Relationships at a Glance

```
Task ──1:N──► Run ──1:N──► Step ──0..1──► ActionRequest
                            │                    │
                            │                    ▼
                            │              Decision (from PDP)
                            │                    │
                            ▼                    ▼
                       Checkpoint           ActionResult
                            │
                            ▼
                  AuditEvent (many per Step, chained)
```

---

## Persistence Layout (SQLite, MVP)

```sql
CREATE TABLE tasks (
  id              TEXT PRIMARY KEY,
  goal            TEXT NOT NULL,
  created_at      TEXT NOT NULL,           -- ISO 8601 UTC
  created_by      TEXT NOT NULL,           -- JSON Principal
  policy_bundle_id TEXT NOT NULL,
  budget          TEXT NOT NULL,           -- JSON
  metadata        TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE runs (
  id              TEXT PRIMARY KEY,
  task_id         TEXT NOT NULL REFERENCES tasks(id),
  status          TEXT NOT NULL,
  started_at      TEXT NOT NULL,
  ended_at        TEXT,
  resume_token    TEXT,
  last_step_seq   INTEGER NOT NULL DEFAULT -1,
  error           TEXT
);
CREATE INDEX runs_status ON runs(status);

CREATE TABLE steps (
  id              TEXT PRIMARY KEY,
  run_id          TEXT NOT NULL REFERENCES runs(id),
  seq             INTEGER NOT NULL,
  model_call      TEXT,                    -- JSON ModelCall
  action          TEXT,                    -- JSON ActionRequest
  decision        TEXT,                    -- JSON Decision
  result          TEXT,                    -- JSON ActionResult
  checkpoint_blob BLOB NOT NULL,
  started_at      TEXT NOT NULL,
  ended_at        TEXT NOT NULL,
  UNIQUE (run_id, seq)
);

CREATE TABLE audit_events (
  id              TEXT PRIMARY KEY,        -- sha256 hex
  prev            TEXT NOT NULL,
  run_id          TEXT NOT NULL,
  seq             INTEGER NOT NULL,
  kind            TEXT NOT NULL,
  timestamp       TEXT NOT NULL,
  body            TEXT NOT NULL,           -- canonical JSON
  signature       BLOB,
  UNIQUE (run_id, seq)
);
CREATE INDEX audit_events_run ON audit_events(run_id, seq);

CREATE TABLE approval_requests (
  id              TEXT PRIMARY KEY,
  run_id          TEXT NOT NULL,
  step_seq        INTEGER NOT NULL,
  action          TEXT NOT NULL,           -- JSON ActionRequest
  decision        TEXT NOT NULL,           -- JSON Decision
  status          TEXT NOT NULL,           -- pending/granted/denied/timeout
  approvers       TEXT NOT NULL,           -- JSON list
  granted_by      TEXT,
  resolved_at     TEXT,
  expires_at      TEXT
);
```

SQLite uses WAL mode for concurrent reads while a writer is active.

---

## What the data model does NOT include

- **Conversation history.** That's the agent framework's job. The runtime only sees ActionRequests and decisions.
- **Tool definitions.** Tools are registered via Python decorators; the type-checked metadata is in `ToolMetadata`.
- **Approval transport.** ApprovalRequest is a record; how the human is *notified* (CLI, webhook, Slack) is the transport's concern.
- **Metrics / cost analytics.** Derived from AuditEvents at query time. No separate "metrics" table.

These are deliberate cuts to keep the model small.
