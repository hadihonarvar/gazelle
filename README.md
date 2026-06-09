# Lynx

**Make any AI agent safe and reliable enough to put in production.** Open-source Python runtime that wraps any agent (LangGraph, CrewAI, OpenAI Agents SDK, Anthropic Agent SDK, or a plain Python loop) and gives you three things every team currently rebuilds from scratch:

1. **Policy-gated execution** — every tool call passes through a declarative YAML policy engine. Dry-run, deny, transform, or require human approval.
2. **Durable execution** — every step is checkpointed before its side effect. Crash mid-run, resume exactly where you left off, no double-execution.
3. **Hash-chained audit log** — content-addressed, tamper-evident, regulator-grade trail of every decision and action.

> Think *Envoy + Temporal + OPA, but for AI agents.*

---

## Why

Agent reliability is the #1 unmet need in 2026 (Gartner: 40% of agentic AI projects will fail). Capabilities are up, reliability is lagging. Real incidents from the last 12 months:

- An AI agent **deleted a developer's entire `D:` drive** when asked to clear a cache folder.
- An AI agent **wiped a production AWS environment**, causing a 13-hour outage.
- Meta's AI safety director was unable to stop her own agent from **deleting her inbox**.
- An n8n v2.4.7→v2.6.3 upgrade silently **broke function-calling schemas** across the user base.

Every team building agents reinvents the same scaffolding: retry logic, dry-runs, approval flows, audit trails. **Lynx is the missing layer.**

---

## Quickstart (under 2 minutes)

```bash
pip install lynx-agent
lynx init
```

```python
# my_agent.py
import asyncio
from lynx import tool, runtime, ToolCall, FinalAnswer, Message

@tool(cost="low", reversible=False, scope=["filesystem:write"])
async def shell(cmd: str) -> str:
    proc = await asyncio.create_subprocess_shell(
        cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    out, err = await proc.communicate()
    return (out + err).decode()

@shell.shadow
async def _shell_shadow(cmd: str) -> dict:
    return {"would_run": cmd}

class MyAgent:
    """Replace with any LLM-backed agent."""
    async def step(self, conversation):
        # Pretend the LLM proposed a dangerous command
        return ToolCall(tool="shell", args={"cmd": "rm -rf /"}, call_id="c1")

async def main():
    result = await runtime.run(
        MyAgent(),
        task="clean up the workspace",
        policy="./policy.yaml",
    )
    print(result.status, result.final_answer)

asyncio.run(main())
```

```bash
$ python my_agent.py
$ lynx ps                    # list runs
$ lynx trace <run_id>        # see every step + policy decision
$ lynx audit verify <run_id> # verify the hash chain
```

The default policy will **deny** the `rm -rf /` and feed the denial back to the agent as a tool result, so the agent can retry with something safer.

---

## How it works

```
                ┌────────────────────────────────────────────────┐
                │  Agent (LangGraph / CrewAI / SDK / any)        │
                └──────────────────┬─────────────────────────────┘
                                   │ proposed tool call
                                   ▼
              ╔════════════════════════════════════════════════╗
              ║                  AGENT RUNTIME                 ║
              ║  ┌────────────┐  ┌────────────┐  ┌──────────┐  ║
              ║  │  Scheduler │→ │ Policy PDP │→ │ Mediator │  ║
              ║  │ (durable)  │  │  (pure)    │  │  (PEP)   │  ║
              ║  └────────────┘  └────────────┘  └──────────┘  ║
              ║          ↓             ↓              ↓        ║
              ║  ┌──────────────────────────────────────────┐  ║
              ║  │      SQLite journal + audit chain        │  ║
              ║  └──────────────────────────────────────────┘  ║
              ╚════════════════════════════════════════════════╝
                                   │ approved + recorded
                                   ▼
              ┌────────────────────────────────────────────────┐
              │ Real world (shell, browser, DB, AWS, etc.)     │
              └────────────────────────────────────────────────┘
```

Every action passes through the **Mediator**. The PDP returns one of five verdicts (`allow`, `deny`, `dry_run`, `approve_required`, `transform`). The Mediator dispatches accordingly. Before any side effect, a checkpoint is written. Every step emits a hash-chained audit event.

---

## Policy example

```yaml
# policy.yaml
version: 1
defaults:
  on_missing_shadow: approve_required
  on_no_match: deny

rules:
  - id: read-only-allow
    match: { declared.scope.contains_any: ["filesystem:read", "net:read"] }
    decision: allow

  - id: shell-rm-rf-root
    match:
      tool: shell
      args.cmd.matches: '^\s*rm\s+(-[rRf]+\s+)+/(\s|$)'
    decision: deny
    reason: "rm -rf / is never allowed"

  - id: prod-mutations-need-approval
    match:
      context.environment: prod
      declared.scope.contains_any: ["filesystem:write", "db:write", "cloud:write"]
    decision: approve_required
    approvers: ["@oncall"]

  - id: irreversible-dry-run-first
    match: { declared.reversible: false }
    decision: dry_run
```

Three layers, increasing expressiveness:
1. **YAML rules** — 80% of cases
2. **Predicates** — reusable named patterns
3. **Python escape hatch** — `@policy.rule` for edge cases

See `docs/02-policy-language.md` for the full grammar.

---

## CLI

```
lynx init                    # set up a project
lynx run <script>            # run an agent script
lynx ps                      # list recent runs
lynx trace <run-id>          # step-by-step trace
lynx approvals               # list pending approvals
lynx approve <approval-id>   # approve a pending request
lynx audit verify <run-id>   # verify the hash chain
lynx audit export <run-id>   # emit jsonl for compliance
lynx policy lint             # validate policy.yaml
lynx policy bundle-id        # content-addressed bundle ID
```

---

## Repo layout

```
lynx/
├── docs/
│   ├── 00-execution-plan.md      ← read first
│   ├── 01-data-model.md
│   ├── 02-policy-language.md
│   └── 03-sdk-and-cli.md
├── src/lynx/
│   ├── core/                     ← pure kernel, no I/O
│   │   ├── types.py
│   │   ├── policy.py             ← PDP
│   │   ├── mediator.py           ← PEP
│   │   └── scheduler.py          ← step loop
│   ├── stores/                   ← pluggable I/O
│   │   └── sqlite.py
│   ├── cli/main.py
│   ├── decorators.py             ← @tool, @shadow
│   ├── policy.py                 ← top-level re-exports
│   ├── runtime.py                ← public Runtime facade
│   └── sdk.py                    ← Agent protocol + Message types
├── tests/
├── examples/
│   └── hello_agent.py
└── pyproject.toml
```

**Architectural rule:** `core/` has zero I/O. All I/O lives in `stores/`, `adapters/`, and `cli/`. This is why the PDP runs in microseconds, why tests are flake-free, and why upgrading from SQLite to Postgres to a gRPC sidecar is a deployment change, not a rewrite.

---

## Roadmap

- **v0.1 (this release)** — MVP: SQLite, YAML policy, allow/deny/approve/dry_run/transform, audit chain, CLI, scripted agent example.
- **v0.5** — Crash-resume durability, shadow library (shell, SQL, HTTP, AWS), `replay --edit`.
- **v1.0** — LangGraph / CrewAI / OpenAI Agents SDK / MCP adapters; Postgres store; webhook & Slack approval transports; gRPC sidecar mode; HSM-signed audit.
- **v1.5** — Control plane: multi-tenant policy distribution, dashboards, cross-run analytics, governance. (Commercial layer.)

See `docs/00-execution-plan.md` for the week-by-week plan.

---

## Performance

| What | Number |
|------|--------|
| Policy evaluation (typical, ≤100 rules) | ~100 µs / call |
| Policy evaluation (worst case, 1000 rules) | ~1 ms / call |
| End-to-end overhead per step | ~3 ms (SQLite-bound) |
| Test suite | 57 tests in 1.1 s |

For real agents where each step is a 500 ms – 5 s LLM call, Lynx's overhead is under 1%. Reproducible numbers in [`benchmarks/`](benchmarks/README.md).

---

## Documentation

Start here if you're new:

| Doc | What it answers |
|-----|----------------|
| [Why Lynx](docs/why-lynx.md) | When should I use this? When shouldn't I? |
| [Getting started](docs/getting-started.md) | 5-minute walkthrough from install to first denial |
| [Concepts](docs/concepts.md) | Vocabulary: Tool, Policy, Verdict, Run, AuditEvent |
| [Policy cookbook](docs/cookbook.md) | Copy-pasteable rules for common patterns |
| [FAQ](docs/faq.md) | Common first-time questions |

Reference docs:

| Doc | What it covers |
|-----|----------------|
| [Data model](docs/01-data-model.md) | The six core types + SQLite schema |
| [Policy language](docs/02-policy-language.md) | Full YAML grammar + predicates + Python escape hatch |
| [SDK + CLI](docs/03-sdk-and-cli.md) | The public Python API + every CLI command |
| [Threat model](docs/threat-model.md) | STRIDE analysis + guarantees + non-goals |
| [How v0.1 was built](docs/00-execution-plan.md) | The MVP execution plan (historical) |

Examples:

| Demo | What it shows |
|------|--------------|
| [`hello_agent.py`](examples/hello_agent.py) | Minimal scripted agent — the smallest end-to-end loop |
| [`file_janitor.py`](examples/file_janitor.py) | Real filesystem demo: allow / deny / dry_run with real files |
| [`refund_agent.py`](examples/refund_agent.py) | Customer-support refund agent — demonstrates `approve_required` |
| [`claude_janitor.py`](examples/claude_janitor.py) | Real Claude agent driving the file demo |
| [`openai_janitor.py`](examples/openai_janitor.py) | Same demo, OpenAI GPT |
| [`fastapi_server.py`](examples/fastapi_server.py) | Drop-in FastAPI integration |

See [`examples/README.md`](examples/README.md) for the full index + how to run them.

---

## Status

Alpha. APIs may change before v1.0. Use in production at your own risk; report issues liberally.

---

## License

Apache 2.0.
