# Agent Runtime — Execution Plan

The master plan that ties together the specs, the milestones, the build order, and what "done" looks like at each step. Read this first.

---

## What We're Building (1-paragraph reminder)

A framework-agnostic Python runtime that sits between any agent (LangGraph, CrewAI, OpenAI/Anthropic SDK, plain Python) and the real world. Every tool call passes through a chokepoint where it is **(1) checked against declarative policy, (2) executed durably with checkpointing, (3) recorded in a hash-chained audit log**. Open source core; commercial control plane later.

---

## North Star

A solo developer can:

```bash
$ pip install gazelle
$ gazelle init
$ python my_agent.py "clean up the cache folder"
[runtime] action shell("rm -rf /") → DENIED (irreversible, blast_radius=root)
[runtime] action shell("rm -rf ~/.cache") → DRY-RUN: 412 files
[runtime] approve? [y/N] y
[runtime] applied. task complete. trace: gazelle trace R-7f3a
```

…in under 5 minutes from install to "agent saved me from a `rm -rf /`."

If that demo lands, the project is alive.

---

## Decisions Already Made

| Decision | Choice | Why |
|----------|--------|-----|
| Language | **Python 3.11+** | Largest agent dev population. Every major SDK (OpenAI, Anthropic, Google ADK, LangGraph, CrewAI, MS Agent Framework) is Python-first. |
| Storage default | **SQLite** | Zero setup. Postgres swappable later via the same interface. |
| Policy language | **YAML + predicates + Python escape** | Three tiers, declarative-first, OPA-pattern. |
| Distribution | **PyPI package + CLI binary** | Match Python developer expectations. |
| License | **Apache 2.0** | Permissive but patent-protective; matches Temporal/OPA/Envoy norms. |
| Process model (MVP) | **Embedded library** | Sidecar/control-plane come later. Same kernel reused. |
| Async model | **asyncio** | All modern agent SDKs are async-first. |

---

## Milestones

### M1 — Specs (Day 1) ✅ this doc + 3 spec docs
- Execution plan (this file)
- Data model spec
- Policy language spec
- SDK + CLI spec

### M2 — Walking Skeleton (Day 1-2)
End-to-end minimum: `@tool` → propose → YAML allow/deny PDP → execute → SQLite journal → CLI `run` + `trace`. One example agent that proves the loop.

**Done when:** `gazelle run examples/hello.py` writes a checkpoint per step and a CLI `trace` command can replay it.

### M3 — Approvals + Audit Chain (Day 2-3)
- `approve_required` verdict
- CLI `gazelle approve <request-id>`
- Hash-chained jsonl audit log
- `gazelle audit verify <run-id>`

**Done when:** A denied action prompts for approval, and `audit verify` detects tampering if you manually edit the log.

### M4 — Dry-Run + Shadows (Day 3-4)
- `dry_run` verdict
- Shadow implementations: shell, filesystem, SQL, HTTP
- `transform` verdict + arg rewriting

**Done when:** A destructive shell command produces a preview without executing.

### M5 — Durability (Day 4-5)
- Crash-resume from checkpoint
- Idempotency keys
- `runtime.resume(token)` API + CLI

**Done when:** Killing the Python process mid-run, restarting, and calling `resume` continues exactly where it left off without re-executing the last action.

### M6 — Adapter (Day 5-6)
- First framework adapter: OpenAI Agents SDK
- Demonstration agent using the SDK + runtime

**Done when:** A real OpenAI Agents SDK agent runs through the runtime without code changes beyond `@runtime.tool` decoration.

### M7 — README + Quickstart (Day 6-7)
- README with the 5-minute install-to-demo flow
- Quickstart guide
- Contributing intro

**Done when:** A reader can go from `git clone` to a working agent with policy enforcement in under 10 minutes by reading the README alone.

---

## Build Order (and why)

```
00-execution-plan.md  ─┐
01-data-model.md       │  M1: Specs first.  Locks the contracts before code.
02-policy-language.md  │
03-sdk-and-cli.md     ─┘
        │
        ▼
pyproject.toml + dirs     M2: Skeleton compiles + tests run.
        │
        ▼
core/types.py             Six core dataclasses. Nothing depends on them yet.
        │
        ▼
core/policy/*             Pure PDP.  Tested in isolation with fixtures.
        │
        ▼
core/mediator.py          PEP. Calls into PDP, dispatches verdicts.
        │
        ▼
stores/sqlite.py          Step journal + audit. Append-only.
core/audit.py
        │
        ▼
core/scheduler.py         The loop.  Glues everything above together.
        │
        ▼
sdk + cli                 Public surface.  Thin wrappers over scheduler.
        │
        ▼
examples/                 Prove the system works end-to-end.
        │
        ▼
README                    Sell the project.
```

The order is intentional: **specs lock the interface, pure code first, I/O last, public API last.** This is the order that minimizes refactors.

---

## "Done" Definitions

**Spec done** = another engineer can implement it without asking questions.

**Module done** = it has tests, mypy is clean, ruff is clean, and a usage example in its docstring works.

**Milestone done** = the "done when" sentence above is true and you can demo it without a script.

---

## Operating Principles

1. **Pure core, dirty edges.** `core/` has no I/O. Stores, adapters, transports do all the I/O. This is the most important architectural rule. Violate it and everything else gets harder.

2. **Tests at the type boundary.** A test that takes a `PolicyBundle` and an `ActionRequest` and asserts a `Decision` runs in microseconds with no setup. Most logic should be testable that way.

3. **YAML before Python.** Every config decision asks "can this be a YAML field?" before becoming a function.

4. **No premature backends.** SQLite covers the MVP. Postgres/NATS/S3 wait until someone needs them.

5. **The decorator stays tiny.** `@tool` should look effortless. Complexity hides in the kernel, never in the user-facing API.

6. **Fail loud, recover later.** Asserts and exceptions in the kernel are fine. Make bugs obvious; let the durability layer catch the user.

---

## Open Questions (to revisit, not block)

- Approval transport for v1: webhook vs Slack vs CLI-only? *(MVP: CLI only)*
- Audit signing in MVP: skip or include? *(MVP: include hash chain, defer HSM signing to v1)*
- Multi-process locking on SQLite store? *(MVP: WAL mode + single-writer assumption)*
- TypeScript SDK timing? *(After M6, separate effort)*

---

## Risks and Mitigations

| Risk | Mitigation |
|------|-----------|
| Framework adapters churn as SDKs evolve | Pin to specific SDK versions in tests; adapter contracts versioned |
| Async/sync interop pain with non-async agents | Provide `runtime.run_sync()` wrapper; document the async path as primary |
| Policy YAML grows into a DSL nobody can write | Lint + test commands from day 1; ship `policy lint` + `policy test fixtures/` |
| Performance: per-step DB writes add up | Single SQLite transaction per step with WAL; benchmark by M5; batch in M7+ if needed |
| Tool authors forget to write shadows | Default to `approve_required` when shadow missing; surface in `policy lint` |

---

## What's NOT in MVP (and that's OK)

- Postgres, NATS, S3 backends — interfaces only, not implementations
- gRPC sidecar mode — design the interface, defer impl
- Control plane / dashboards — commercial layer, comes after OSS traction
- LangGraph / CrewAI / Anthropic SDK adapters — only OpenAI Agents SDK in M6
- HSM-signed audit — hash chain only
- Hot policy reload — restart-to-reload is fine for MVP
- Web UI — CLI only

These are explicit cuts. Saying no to them is what makes the MVP shippable in a week.

---

## Next Step

Write the three spec docs (`01-data-model.md`, `02-policy-language.md`, `03-sdk-and-cli.md`). Then start the code at `core/types.py`.
