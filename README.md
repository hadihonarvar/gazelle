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
├── examples/                    ← 12 numbered examples + framework integrations
│   ├── 01_hello_allow.py ... 10_devops_assistant.py
│   ├── 11_flask_service.py
│   ├── 12_django_service.py
│   └── policies/                ← multi-rule YAMLs used by examples 07/08/10
├── benchmarks/
└── pyproject.toml
```

**Architectural rule:** `core/` has zero I/O. All I/O lives in `stores/`, `adapters/`, and `cli/`. This is why the PDP runs in microseconds, why tests are flake-free, and why upgrading from SQLite to Postgres to a gRPC sidecar is a deployment change, not a rewrite.

---

## Roadmap

**Shipped in v1.0** (current release):
- Core kernel: policy PDP, action mediator, scheduler with pre-execution checkpointing
- All five verdicts: allow / deny / dry_run / approve_required / transform
- Hash-chained, tamper-evident audit log with `lynx audit verify`
- Stores: SQLite (default), Postgres (production)
- Adapters: Anthropic Claude, OpenAI, LangGraph, CrewAI, MCP
- Shadow library: shell, filesystem, SQL, HTTP
- Subprocess sandbox with POSIX rlimits
- Crash-resume + approval-resume
- Prometheus + OpenTelemetry hooks
- Full CLI + 12 examples + STRIDE threat model

**On the table for v1.x** (no firm dates):
- `lynx replay <run-id> --from-step N --edit` for run inspection
- Container sandbox mode (the v1.0 sandbox is POSIX-subprocess only)
- Webhook + Slack approval transports
- gRPC sidecar mode for non-Python apps
- HSM-signed audit events (current chain is hash-only)
- Control-plane / multi-tenant dashboards (probably commercial)

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
| [How v1.0 was built](docs/00-execution-plan.md) | The execution plan that got us to v1.0 (historical) |

Examples — a learning path of 12. Each lead with a plain-language SCENARIO so the use case is clear:

| # | Demo | What it shows |
|---|------|--------------|
| 01 | [`01_hello_allow.py`](examples/01_hello_allow.py) | Smallest possible loop. ALLOW verdict. |
| 02 | [`02_block_dangerous.py`](examples/02_block_dangerous.py) | Block `rm -rf /` before it can run. DENY verdict. |
| 03 | [`03_preview_writes.py`](examples/03_preview_writes.py) | See a file's contents BEFORE saving. DRY_RUN verdict. |
| 04 | [`04_human_approval.py`](examples/04_human_approval.py) | Pause for human sign-off on irreversible actions. |
| 05 | [`05_real_llm_blocked.py`](examples/05_real_llm_blocked.py) | Real Claude / GPT agent gated by Lynx. |
| 06 | [`06_compliance_audit.py`](examples/06_compliance_audit.py) | Hash-chain verification + tamper detection. |
| 07 | [`07_refund_workflow.py`](examples/07_refund_workflow.py) | Multi-tier refund rules (allow / approve / deny). |
| 08 | [`08_sql_transform.py`](examples/08_sql_transform.py) | TRANSFORM verdict auto-injects `tenant_id` into SQL. |
| 09 | [`09_fastapi_service.py`](examples/09_fastapi_service.py) | Drop-in FastAPI integration. |
| 10 | [`10_devops_assistant.py`](examples/10_devops_assistant.py) | All five verdicts in one realistic DevOps scenario. |
| 11 | [`11_flask_service.py`](examples/11_flask_service.py) | Same as 09 but Flask (sync via `runtime.run_sync`). |
| 12 | [`12_django_service.py`](examples/12_django_service.py) | Same as 09 but Django (async views, 4.1+). |

See [`examples/README.md`](examples/README.md) for the full index + how to run them.

---

## Status

**v1.0 — public API committed.** SemVer from here: minor versions add features, patch versions fix bugs, major versions are reserved for breaking changes with documented deprecation cycles. Internal modules (`lynx.core.*`) are not part of the public API and may change in any minor release.

Production-ready for the documented scope (SQLite store, all five adapters, subprocess sandbox, hash-chained audit). See [`CHANGELOG.md`](CHANGELOG.md) for the full v1.0 surface area covered by the SemVer commitment.

---

## License

Apache 2.0.
