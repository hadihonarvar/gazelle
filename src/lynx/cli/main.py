"""Lynx CLI v2 — minimal: init, run, policy lint, policy bundle-id, --version."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import click

from lynx import __version__
from lynx.policy import load_policy_file

__all__ = ["cli"]


_DEFAULT_POLICY = """\
version: 1
defaults:
  on_missing_shadow: approve_required
  on_no_match: deny

rules:
  - id: read-only-allow
    description: Read-only tools are always fine
    match:
      declared.scope.contains_any: ["filesystem:read", "net:read"]
    decision: allow

  - id: shell-rm-rf-root
    description: Never delete from filesystem root
    match:
      tool: shell
      args.cmd.matches: '^\\s*rm\\s+(-[rRf]+\\s+)+/(\\s|$)'
    decision: deny
    reason: "rm -rf / is never allowed"

  - id: irreversible-needs-approval
    description: Irreversible actions require explicit approval
    match:
      declared.reversible: false
    decision: approve_required
"""


@click.group()
@click.version_option(__version__, prog_name="lynx")
def cli() -> None:
    """Lynx: stateless, type-safe policy kernel for AI agent tool calls."""


@cli.command()
@click.option("--dir", "directory", default=".", help="Project directory")
@click.option("--force", is_flag=True, help="Overwrite policy.yaml even if it already exists")
def init(directory: str, force: bool) -> None:
    """Write a starter policy.yaml in the given directory.

    No state directory. No config file. Lynx v2 holds nothing on disk.
    """
    d = Path(directory).resolve()
    policy_path = d / "policy.yaml"
    if policy_path.exists() and not force:
        click.echo(f"= {policy_path} already exists (use --force to overwrite)", err=True)
        sys.exit(1)
    policy_path.write_text(_DEFAULT_POLICY)
    click.echo(f"wrote {policy_path}")


@cli.command()
@click.argument("script", type=click.Path(exists=True))
def run(script: str) -> None:
    """Run a Python script that defines an async ``main()`` coroutine.

    The script owns the runtime call (``await run_agent(...)``); Lynx just
    imports it and executes ``main()``.
    """
    import runpy

    sys.path.insert(0, str(Path(script).resolve().parent))
    namespace = runpy.run_path(script)

    if "main" not in namespace or not asyncio.iscoroutinefunction(namespace["main"]):
        click.echo(
            "script must define an async `main()` coroutine that calls run_agent(...)",
            err=True,
        )
        sys.exit(1)

    asyncio.run(namespace["main"]())


@cli.group()
def policy() -> None:
    """Policy file operations."""


@policy.command("lint")
@click.argument("path", default="policy.yaml")
def policy_lint(path: str) -> None:
    """Compile-check a policy file and print rule summary."""
    try:
        bundle = load_policy_file(path)
    except Exception as exc:
        click.echo(f"{type(exc).__name__}: {exc}", err=True)
        sys.exit(1)
    click.echo(f"{len(bundle.rules)} rules compiled cleanly")
    for r in bundle.rules:
        click.echo(f"  {r.id} (priority {r.priority}) - {r.description}")


@policy.command("bundle-id")
@click.argument("path", default="policy.yaml")
def policy_bundle_id(path: str) -> None:
    """Print the content-addressed bundle ID for a policy file."""
    bundle = load_policy_file(path)
    click.echo(bundle.id)


if __name__ == "__main__":
    cli()
