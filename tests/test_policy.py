"""Policy engine (PDP) tests — pure function behavior."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime

import pytest

from lynx import (
    ActionRequest,
    Decision,
    ExecutionContext,
    Principal,
    ToolMetadata,
    Verdict,
    allow,
    compile_policy,
    deny,
)
from lynx.policy import evaluate


def _ctx(env: str = "dev") -> ExecutionContext:
    return ExecutionContext(
        principal=Principal(kind="user", id="t"),
        environment=env,
        workspace="/tmp",
        correlation_id="c-test",
        step_seq=0,
        timestamp=datetime.now(UTC),
    )


def _req(
    tool: str = "shell",
    args: Mapping[str, object] | None = None,
    *,
    reversible: bool = True,
    has_shadow: bool = False,
    env: str = "dev",
) -> ActionRequest:
    return ActionRequest(
        tool=tool,
        args=args or {},
        declared=ToolMetadata(
            cost="low",
            reversible=reversible,
            scope=("compute:exec",),
            has_shadow=has_shadow,
        ),
        context=_ctx(env=env),
    )


def test_simple_allow_deny() -> None:
    bundle = compile_policy(
        """
version: 1
defaults: { on_no_match: allow }
rules:
  - id: block
    match:
      tool: shell
      args.cmd.matches: '^rm -rf /$'
    decision: deny
    reason: forbidden
        """
    )
    d1 = evaluate(bundle, _req(args={"cmd": "rm -rf /"}), _ctx())
    assert d1.verdict == Verdict.DENY
    assert "forbidden" in d1.reason

    d2 = evaluate(bundle, _req(args={"cmd": "ls"}), _ctx())
    assert d2.verdict == Verdict.ALLOW


def test_first_match_wins() -> None:
    bundle = compile_policy(
        """
version: 1
defaults: { on_no_match: deny }
rules:
  - id: specific-allow
    priority: 10
    match: { tool: shell, args.cmd.matches: '^curl http://localhost' }
    decision: allow
  - id: general-deny
    priority: 5
    match: { tool: shell, args.cmd.matches: '^curl ' }
    decision: deny
        """
    )
    d = evaluate(bundle, _req(args={"cmd": "curl http://localhost/health"}), _ctx())
    assert d.verdict == Verdict.ALLOW


def test_default_on_missing_shadow() -> None:
    bundle = compile_policy(
        """
version: 1
defaults:
  on_no_match: allow
  on_missing_shadow: approve_required
rules: []
        """
    )
    d = evaluate(bundle, _req(reversible=False, has_shadow=False), _ctx())
    assert d.verdict == Verdict.APPROVE_REQUIRED


def test_python_rules_explicit_not_global() -> None:
    """Python rules are passed in at compile time, not via a global registry."""

    def block_in_prod(req: ActionRequest, ctx: ExecutionContext) -> Decision | None:
        if ctx.environment == "prod":
            return deny(reason="prod is locked")
        return None

    bundle = compile_policy(
        "version: 1\ndefaults: { on_no_match: allow }\nrules: []",
        python_rules=(block_in_prod,),
        python_rule_priorities=(("block_in_prod", 100),),
    )

    d_prod = evaluate(bundle, _req(env="prod"), _ctx(env="prod"))
    assert d_prod.verdict == Verdict.DENY

    d_dev = evaluate(bundle, _req(env="dev"), _ctx(env="dev"))
    assert d_dev.verdict == Verdict.ALLOW


def test_python_rule_returning_none_falls_through() -> None:
    def maybe_deny(req: ActionRequest, ctx: ExecutionContext) -> Decision | None:
        return None  # never matches

    bundle = compile_policy(
        "version: 1\ndefaults: { on_no_match: allow }\nrules: []",
        python_rules=(maybe_deny,),
    )
    d = evaluate(bundle, _req(), _ctx())
    assert d.verdict == Verdict.ALLOW


def test_pdp_is_deterministic() -> None:
    """Same inputs → same Decision, always."""
    bundle = compile_policy(
        """
version: 1
defaults: { on_no_match: allow }
rules:
  - id: r
    match: { tool: shell }
    decision: deny
    reason: no shells
        """
    )
    req = _req()
    ctx = _ctx()
    d1 = evaluate(bundle, req, ctx)
    d2 = evaluate(bundle, req, ctx)
    d3 = evaluate(bundle, req, ctx)
    assert d1 == d2 == d3


def test_redos_guard_rejects_dangerous_regex() -> None:
    with pytest.raises((ValueError, Exception)):
        compile_policy(
            """
version: 1
defaults: { on_no_match: deny }
rules:
  - id: redos
    match:
      tool: shell
      args.cmd.matches: '(a+)+b'
    decision: deny
            """
        )


def test_overlong_regex_rejected() -> None:
    long_pat = "a" * 1500
    with pytest.raises((ValueError, Exception)):
        compile_policy(
            f"""
version: 1
defaults: {{ on_no_match: deny }}
rules:
  - id: too-long
    match:
      tool: shell
      args.cmd.matches: "{long_pat}"
    decision: deny
            """
        )


def test_decision_constructors() -> None:
    assert allow().verdict == Verdict.ALLOW
    assert deny("no").verdict == Verdict.DENY
    assert deny("no").reason == "no"
