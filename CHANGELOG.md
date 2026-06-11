# Changelog

All notable changes to Lynx will be documented here. Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versioning follows [SemVer](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- `PolicyCompileError` raised for malformed YAML, unknown operators (with typo suggestions), unknown predicate names, invalid `transform` blocks, malformed `between` / `in` operands, and ReDoS-guard rejections.
- `Message.tool_call_args` field — the scheduler now records the assistant's tool-call shape so Anthropic / OpenAI adapters can re-emit a well-formed `assistant→tool` alternation on the next step.
- `action.dry_run_completed` audit event kind, distinct from `action.completed`. Tool-side denials emit `action.denied` (was `action.failed`) so consumers can bucket denials separately.
- `mcp_tools` now returns an `async with` context manager that keeps the MCP child process alive for the lifetime of the run.
- Sink failures (in `run_agent` and in `multi_sink`) are reported to stderr instead of being silently swallowed.
- `ClaudeAgent` and `OpenAIAgent` are async context managers and expose `aclose()`. Auto-created HTTP clients are released on `__aexit__`; user-supplied clients are left alone.

### Fixed
- TRANSFORM verdict no longer silently degrades to ALLOW when `transform_args` is missing.
- Python rules and YAML rules now share a single priority-sorted evaluation order; a higher-priority YAML rule no longer loses to a lower-priority Python rule.
- `bundle_id` now hashes rule bodies (and defaults / python-rule priorities), not just rule IDs. Two policies with the same IDs but different verdicts now produce different IDs.
- Equal-priority rules sort by integer file order, not by lexicographic source location (`rule[10]` no longer sorts before `rule[2]`).
- `approve_required` `timeout_seconds` is enforced by the mediator: a hanging handler now times out into a deny instead of hanging the run forever. Exceptions in the handler convert to a deny.
- `cli_prompt_approval` no longer blocks the event loop while waiting for stdin.
- Sandbox subprocess kill path now reaps the child; PYTHONPATH no longer leaks empty `sys.path` entries.
- `Verdict` parsing in YAML accepts mixed case.
- `in` / `between` / `not_between` operators validate their right-hand side at compile time.
- Operator typos (`args.cmd.matchess`) raise `PolicyCompileError` instead of silently becoming a never-matching field path.
- `canonical_json` falls back to `repr()` for non-serializable values instead of crashing sinks.
- `ToolSet.from_functions` / `with_tool` / `union` raise on duplicate tool names instead of silently overwriting.
- `Budget.duration_seconds` uses `time.monotonic()` instead of `time.time()`.
- `_annotation_to_schema` understands `list[int]`, `Literal[...]`, `Optional[X]`, `Union[...]`, `tuple[...]`, and `bytes` instead of flattening every non-primitive to `{"type": "string"}`.
- Service examples (FastAPI / Flask / Django) inspect events for `action.denied` and return HTTP 403 instead of reporting a misleading 200.
- Example 10 + `examples/policies/devops.yaml` now exercise all five verdicts (run once in staging + once in prod). The docstring matches reality.
- Django example puts the project root on `sys.path` before `django.setup()` so the documented invocation actually works.

### Removed
- `Budget.usd` and `Budget.tokens` fields — neither was enforced; token/spend accounting belongs in a sink.

### Leak fixes
- `shadows/sql.py`: cursor opened against a user-supplied `conn` was never closed; now closed in a `finally` block.
- `sandbox.py`: the sandboxed child is now killed and reaped in a `finally` block, so cancellation or any post-exec exception cannot leave a zombie process or open stdout/stderr pipes.
- `adapters/anthropic_sdk.py` + `adapters/openai_sdk.py`: when the agent auto-created the SDK client, the HTTP/2 connection pool had no shutdown path. `aclose()` + `__aenter__` / `__aexit__` close it cleanly. User-supplied clients are untouched.

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

- Every public type is `frozen=True, slots=True`.
- Public API uses `Mapping` / `tuple` / `Sequence`, never `dict` / `list`.
- Zero `Any` in the public API surface; internal `Any` only at adapter boundaries.
- `mypy src` runs in CI as an advisory check; tightening to `--strict` and making it a hard gate is tracked for a follow-up release.

### Dependencies

- Dropped: `msgpack`, `python-ulid` (now using stdlib `uuid`).
- Dropped extras: `[postgres]`.
- Optional extras kept: `[anthropic]`, `[openai]`, `[langgraph]`, `[crewai]`, `[mcp]`.
- New optional extras coming in 2.1: `[sinks-otel]`, `[sinks-prom]`, `[sinks-kafka]`, `[sinks-http]`.

### Testing

- Test suite rewritten around the new surface. Removed: store, audit-chain, resume, broker, idempotency tests. Added: ToolSet immutability tests, sink contract tests, approval handler tests, `run_agent` integration tests (including TRANSFORM end-to-end, approval timeout, sink failures, and policy hot-swap).

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
