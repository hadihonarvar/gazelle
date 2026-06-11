# Contributing to Lynx

Thanks for considering a contribution. This document covers what to do and what to expect.

## Quick setup

```bash
git clone https://github.com/<your-fork>/lynx
cd lynx
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
make all          # fmt + lint + type + test — should be green
```

## Filing issues

Open an issue using one of the [templates](.github/ISSUE_TEMPLATE/) — `bug`, `feature`, or `question`. The more reproduction info you include, the faster we can act.

## Proposing changes

1. **Open an issue first** for non-trivial changes — saves you wasted effort if the design doesn't fit. Trivial fixes (typos, small bugs, clearer error messages) can skip straight to a PR.
2. **Branch from `main`**, with a name like `fix/regex-redos-guard` or `feat/sinks-otel`.
3. **One logical change per PR.** Smaller PRs land faster.
4. **Tests required** for new behavior. Bug fixes should include a regression test.
5. **Update docs** when you change the public API or CLI surface.
6. **Run `make all` locally** before pushing. CI runs the same checks; saving a round-trip helps.

## Architecture rules

These are load-bearing — please don't break them:

1. **`core/` is pure.** No I/O. No globals. No clocks read inside policy evaluation. Functions take inputs and return outputs.
2. **Every public type is `frozen=True, slots=True`.** Mutation returns a new value; never mutate in place.
3. **No module-level mutable state.** No registries, no brokers, no module-level singletons. State flows through function arguments.
4. **The PDP is deterministic.** Same `(bundle, request, context)` always produces the same `Decision`.
5. **Lynx holds nothing on disk or in memory beyond a single `run_agent` call.** Sinks and approval handlers are the user's responsibility.
6. **Tools must be async.** A sync function is `asyncio.to_thread(...)` away from being async; please wrap rather than introducing sync paths into the kernel.
7. **No `Any` in the public API.** Use `Mapping`, `Sequence`, `tuple`, generic Protocols.
8. **No breaking changes to the public API in minor or patch releases.** Major versions only, with a documented deprecation cycle.

## Adding a new sink

`src/lynx/sinks.py` — add a factory returning a `Sink`-conforming async callable:

```python
def my_sink(target: Resource) -> Sink:
    async def sink(event: AuditEvent) -> None:
        await target.write(canonical_json(event))
    return sink
```

Then add tests in `tests/test_sinks_and_approvals.py`.

## Adding a new approval handler

`src/lynx/approvals.py` — add a factory returning an `ApprovalHandler`:

```python
def my_handler(...) -> ApprovalHandler:
    async def handler(req: ApprovalRequest) -> ApprovalDecision:
        ...
        return ApprovalDecision(granted=..., approver=..., reason=...)
    return handler
```

Then add tests.

## Adding a new adapter

The smallest viable PR for a new framework adapter:

1. `src/lynx/adapters/<framework>.py` — a class that satisfies the `Agent` protocol (`async def step(conversation: tuple[Message, ...]) -> ToolCall | FinalAnswer`).
2. Tests in `tests/test_adapters.py` — mock the framework's client; assert message translation + tool-call extraction + (for HTTP-pool-backed SDKs) that auto-created clients are closed via `aclose()` / `__aexit__`.
3. `examples/<framework>_demo.py` — a runnable demo using the new adapter.
4. Update the README's adapter list.
5. Add a `[framework]` optional extra to `pyproject.toml`.

## Adding a new shadow

`src/lynx/shadows/<name>.py` — one or more `async def name_shadow(*args) -> dict` functions that return previews without side effects.

## Coding style

- Python 3.11+
- `ruff` for lint + format (hard CI gate)
- `pytest` for tests (hard CI gate)
- `mypy src` runs as an advisory check in CI; please don't add new errors. Running `mypy --strict` cleanly is a target we're moving toward.
- One blank line between methods, two between top-level definitions
- Docstrings on every public function — short and useful, not ceremonial

## Commit messages

Conventional Commits style:

- `fix: regex redos guard`
- `feat(sinks): otel_sink`
- `docs: clarify approve flow`
- `test: cover budget exhaustion`
- `chore: bump ruff to 0.6`

## Release process

Maintainers only:

1. Update `CHANGELOG.md`
2. Bump version in `src/lynx/__init__.py` (`pyproject.toml` reads it dynamically)
3. `git tag vX.Y.Z` + push tag
4. GitHub Actions handles wheel build + PyPI publish via OIDC trusted publishing

## Code of conduct

By participating you agree to follow the [Contributor Covenant](CODE_OF_CONDUCT.md). In short: be kind, be patient, assume good intent, and call out behavior that crosses lines.

## Security issues

Do **not** open public issues for security vulnerabilities. Follow the process in [SECURITY.md](SECURITY.md).

## Licensing

By contributing, you agree your contributions will be licensed under the Apache License 2.0.
