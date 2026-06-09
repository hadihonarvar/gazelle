"""Security-focused tests: regex DoS guard, audit tamper detection, etc."""

from __future__ import annotations

import pytest

from lynx.core.policy import compile_policy


def test_regex_redos_pattern_rejected():
    """A classic catastrophic-backtracking shape should fail at compile time."""
    with pytest.raises((ValueError, Exception)):
        compile_policy(
            """
version: 1
rules:
  - id: redos
    match:
      tool: shell
      args.cmd.matches: "(a+)+b"
    decision: deny
            """
        )


def test_overlong_regex_rejected():
    long_pat = "a" * 1500
    with pytest.raises((ValueError, Exception)):
        compile_policy(
            f"""
version: 1
rules:
  - id: too-long
    match:
      tool: shell
      args.cmd.matches: "{long_pat}"
    decision: deny
            """
        )


def test_normal_regex_still_works():
    bundle = compile_policy(
        """
version: 1
defaults: { on_no_match: allow }
rules:
  - id: ok
    match:
      tool: shell
      args.cmd.matches: '^ls\\b'
    decision: allow
        """
    )
    assert len(bundle.rules) == 1
