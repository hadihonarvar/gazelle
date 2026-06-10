# Changelog

All notable changes to Lynx will be documented here. Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versioning follows [SemVer](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- (nothing yet)

## [2.0.0] — 2026-06-10

**Breaking rewrite.** Lynx becomes a stateless, type-safe policy kernel. Pure functions over immutable values. No SQLite. No globals. No leaks. v1.0.x is preserved on PyPI for users who need durability + audit storage.

### Identity (changed)

> v1: "Policy + durable execution + hash-chained audit at the tool-call boundary."
> v2: "**A stateless, type-safe policy kernel for AI agent tool calls.** Pure functions. Streaming events. No DB."

### Public API

#### Added
- `run_agent(agent, task, *, tools, policy, sinks, on_approval, ...)` — the single entry point. Pure async function.
- `ToolSet` — immutable mapping built from `@tool`-decorated functions; `ToolSet.from_functions(*fns)`, `.with_tool(...)`, `.union(...)`.
- `Sink` protocol + `stdout_sink`, `jsonl_sink`, `noop_sink`, `multi_sink`, `callback_sink`.
- `ApprovalHandler` protocol + `auto_approve`, `auto_deny`, `cli_prompt_approval`, `callback_approval`.
- `ApprovalRequest`, `ApprovalDecision` frozen types.
- `RunResult` minimal frozen type (`correlation_id`, `bundle_id`, `final_answer`, `error`, `steps_taken`).
- `AuditEvent` simplified: `correlation_id`, `bundle_id`, `seq`, `kind`, `timestamp`, `body`.
- `compile_policy(..., python_rules=...)` — explicit Python rules.

#### Removed
- `Runtime` class (and the module-level `runtime` singleton).
- `runtime.run / resume / approve / deny / get_run / get_steps / audit_chain / verify_audit / list_runs`.
- SQLiteStore, PostgresStore, the whole `stores/` package.
- `ApprovalBroker` — replaced by synchronous `on_approval` callback.
- Global tool registry — replaced by explicit `ToolSet`.
- Global `@policy.rule` registration — replaced by `python_rules=` argument.
- `enable_prometheus`, `enable_otel`, `trace_step` — replaced by sinks (Prometheus/OTel sinks land in 2.1).
- Pre-execution checkpointing.
- Idempotency-key dedupe (`compute_idempotency_key`, `GENESIS_HASH`).
- Hash-chained `AuditEvent.id` / `.prev`.
- `Step.checkpoint_blob`, `Run.resume_token`, `Run.last_step_seq`, `RunStatus.PAUSED`.

### CLI

#### Kept
- `lynx --version`
- `lynx init` — writes policy.yaml only (no `.lynx/`, no `lynx.toml`)
- `lynx run <script>` — runs an async `main()` from any Python script
- `lynx policy lint`
- `lynx policy bundle-id`

#### Removed
- `lynx ps`
- `lynx trace <run-id>`
- `lynx audit verify / export`
- `lynx resume`
- `lynx approvals / approve / deny`

### Type system

- `mypy --strict` is now a hard CI gate (was soft in v1).
- Every public type is `frozen=True, slots=True`.
- Public API uses `Mapping` / `tuple` / `Sequence`, never `dict` / `list`.
- Zero `Any` in the public API surface; internal `Any` only at adapter boundaries.

### Dependencies

- Dropped: `msgpack`, `python-ulid` (now using stdlib `uuid`).
- Dropped extras: `[postgres]`.
- Optional extras kept: `[anthropic]`, `[openai]`, `[langgraph]`, `[crewai]`, `[mcp]`.
- New optional extras coming in 2.1: `[sinks-otel]`, `[sinks-prom]`, `[sinks-kafka]`, `[sinks-http]`.

### Testing

- Test suite slimmed from 57 v1 tests to 57 focused v2 tests (different tests).
- Removed: store, audit-chain, resume, broker, idempotency tests.
- Added: ToolSet immutability tests, sink contract tests, approval handler tests, `run_agent` integration tests.

### Documentation

- New: `docs/v2-rfc.md` — the formal RFC this implementation follows.
- Rewritten: README, examples (12), concepts, FAQ, cookbook.
- Removed: data-model deep dive (the new model is small enough to live in the RFC).

## [1.0.1] — 2026-06-10

Docs-only release. Aligned docs with v1.0 surface. See git history for details.

## [1.0.0] — 2026-06-09

First public release. v1 design preserved on PyPI for users needing durability + audit chain.

[Unreleased]: https://github.com/hadihonarvar/lynx/compare/v2.0.0...HEAD
[2.0.0]: https://github.com/hadihonarvar/lynx/releases/tag/v2.0.0
[1.0.1]: https://github.com/hadihonarvar/lynx/releases/tag/v1.0.1
[1.0.0]: https://github.com/hadihonarvar/lynx/releases/tag/v1.0.0
