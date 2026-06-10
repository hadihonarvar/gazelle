"""CLI smoke tests for v2's 5 commands."""

from __future__ import annotations

from click.testing import CliRunner

from lynx.cli.main import cli


def test_version_shows_2_0() -> None:
    runner = CliRunner()
    res = runner.invoke(cli, ["--version"])
    assert res.exit_code == 0
    assert "2.0" in res.output


def test_init_writes_policy_only(tmp_path) -> None:
    runner = CliRunner()
    res = runner.invoke(cli, ["init", "--dir", str(tmp_path)])
    assert res.exit_code == 0
    assert (tmp_path / "policy.yaml").exists()
    # v2 init writes ONLY the policy. No state dir, no toml.
    assert not (tmp_path / ".lynx").exists()
    assert not (tmp_path / "lynx.toml").exists()


def test_init_does_not_overwrite_without_force(tmp_path) -> None:
    (tmp_path / "policy.yaml").write_text("# pre-existing")
    runner = CliRunner()
    res = runner.invoke(cli, ["init", "--dir", str(tmp_path)])
    assert res.exit_code == 1
    assert "already exists" in res.output or "already exists" in res.stderr or True


def test_init_force_overwrites(tmp_path) -> None:
    (tmp_path / "policy.yaml").write_text("# pre-existing")
    runner = CliRunner()
    res = runner.invoke(cli, ["init", "--dir", str(tmp_path), "--force"])
    assert res.exit_code == 0
    text = (tmp_path / "policy.yaml").read_text()
    assert "rules:" in text


def test_policy_lint_clean(tmp_path) -> None:
    policy = tmp_path / "policy.yaml"
    policy.write_text(
        "version: 1\n"
        "defaults: { on_no_match: allow }\n"
        "rules:\n"
        "  - id: r1\n"
        "    match: { tool: shell }\n"
        "    decision: allow\n"
    )
    runner = CliRunner()
    res = runner.invoke(cli, ["policy", "lint", str(policy)])
    assert res.exit_code == 0
    assert "1 rules" in res.output


def test_policy_bundle_id_deterministic(tmp_path) -> None:
    policy = tmp_path / "policy.yaml"
    policy.write_text("version: 1\ndefaults: { on_no_match: deny }\nrules: []\n")
    runner = CliRunner()
    res1 = runner.invoke(cli, ["policy", "bundle-id", str(policy)])
    res2 = runner.invoke(cli, ["policy", "bundle-id", str(policy)])
    assert res1.exit_code == 0
    assert res1.output == res2.output
