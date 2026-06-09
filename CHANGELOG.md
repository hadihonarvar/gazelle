# Changelog

All notable changes to Gazelle will be documented here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versioning follows [SemVer](https://semver.org/spec/v2.0.0.html) from v1.0 onwards.

## [Unreleased]

### Added
- LangGraph adapter (`gzl.adapters.langgraph`)
- CrewAI adapter (`gzl.adapters.crewai`)
- MCP universal adapter (`gzl.adapters.mcp`)
- Postgres store backend (`gzl.stores.postgres`)
- Subprocess sandbox mode for `@tool(sandbox="subprocess")`
- Threat model document at `docs/threat-model.md`
- Benchmarks under `benchmarks/`
- Prometheus + OpenTelemetry instrumentation

### Changed
- (nothing yet)

### Fixed
- (nothing yet)

## [0.1.0] — 2026-06-08

### Added
- Core kernel: types (Task / Run / Step / ActionRequest / Decision / AuditEvent), policy compiler + PDP, action mediator (PEP), scheduler with pre-execution checkpointing.
- SQLite store with hash-chained audit log.
- Public SDK: `@tool` decorator, `runtime.run/resume/approve/deny`, `Agent` protocol.
- CLI: `init`, `run`, `resume`, `ps`, `trace`, `approvals`, `approve`, `deny`, `audit verify/export`, `policy lint`, `policy bundle-id`.
- Anthropic Claude adapter (`gzl.adapters.anthropic_sdk.ClaudeAgent`).
- OpenAI GPT adapter (`gzl.adapters.openai_sdk.OpenAIAgent`).
- Shadow library: `shell_shadow`, `write_file_shadow`, `delete_file_shadow`, `sql_shadow`, `http_shadow`.
- Crash-resume + approval-resume flow.
- Examples: `hello_agent.py`, `file_janitor.py`, `claude_janitor.py`.
- 48-test suite covering policy, mediator, scheduler, shadows, adapters, audit chain, CLI.

[Unreleased]: https://github.com/hadihonarvar/gazelle/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/hadihonarvar/gazelle/releases/tag/v0.1.0
