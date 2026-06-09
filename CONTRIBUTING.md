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
2. **Branch from `main`**, with a name like `fix/policy-regex-timeout` or `feat/postgres-store`.
3. **One logical change per PR.** Smaller PRs land faster.
4. **Tests required** for new behavior. Bug fixes should include a regression test.
5. **Update docs** when you change the public API or CLI surface.
6. **Run `make all` locally** before pushing. CI runs the same checks; saving a round-trip helps.

## Architecture rules

These are load-bearing — please don't break them:

1. **`core/` has zero I/O.** It's pure functions and state machines. If you need to do I/O, it goes in `stores/`, `adapters/`, `transports/`, or `cli/`.
2. **The PDP is deterministic.** No network, no clocks read inside policy evaluation, no random. Same input must always produce the same `Decision`.
3. **The audit chain is append-only.** If you find yourself wanting to mutate a past `AuditEvent`, you're solving the wrong problem.
4. **Tools must be async.** A sync tool is `asyncio.to_thread(...)` away from being async; please wrap rather than introducing sync paths into the kernel.
5. **No breaking changes to the public API in patch releases.** We follow SemVer strictly from v1.0 onwards.

## Adding a new adapter

The smallest viable PR for a new framework adapter:

1. `src/lynx/adapters/<framework>.py` — a class that satisfies the `Agent` protocol (`async def step(conversation) -> ToolCall | FinalAnswer`).
2. `tests/test_adapter_<framework>.py` — mock the framework's client; assert the message translation + tool-call extraction.
3. `examples/<framework>_demo.py` — a runnable demo using the new adapter.
4. Update the README's adapter list.

## Adding a new shadow

`src/lynx/shadows/<name>.py` — one or more `async def name_shadow(*args) -> dict` functions that return previews without side effects.

## Coding style

- Python 3.11+
- `ruff` for lint + format
- `mypy --strict` for types
- One blank line between methods, two between top-level definitions
- Docstrings on every public function — short and useful, not ceremonial

## Commit messages

Conventional Commits style:

- `fix: policy regex denial-of-service guard`
- `feat(stores): postgres backend`
- `docs: clarify approve flow`
- `test: cover budget exhaustion`
- `chore: bump ruff to 0.6`

## Release process

Maintainers only:

1. Update `CHANGELOG.md`
2. Bump version in `pyproject.toml` and `src/lynx/__init__.py`
3. `git tag vX.Y.Z` + push tag
4. GitHub Actions handles wheel build + PyPI publish via OIDC trusted publishing

## Code of conduct

By participating you agree to follow the [Contributor Covenant](CODE_OF_CONDUCT.md). In short: be kind, be patient, assume good intent, and call out behavior that crosses lines.

## Security issues

Do **not** open public issues for security vulnerabilities. Follow the process in [SECURITY.md](SECURITY.md).

## Licensing

By contributing, you agree your contributions will be licensed under the Apache License 2.0.
