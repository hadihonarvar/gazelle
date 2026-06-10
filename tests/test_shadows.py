"""Tests for the shadow library."""

from __future__ import annotations

from lynx.shadows.filesystem import delete_file_shadow, write_file_shadow
from lynx.shadows.http import http_shadow
from lynx.shadows.shell import shell_shadow
from lynx.shadows.sql import sql_shadow


async def test_shell_shadow_detects_destructive() -> None:
    out = await shell_shadow("rm -rf /tmp/foo")
    assert out["destructive_tokens"] == ["rm"]


async def test_shell_shadow_detects_network() -> None:
    out = await shell_shadow("curl https://example.com")
    assert out["network_egress"] is True


async def test_write_file_shadow_new(tmp_path) -> None:
    out = await write_file_shadow(str(tmp_path / "new.txt"), "hello")
    assert out["would_overwrite"] is False
    assert out["bytes"] == 5
    assert not (tmp_path / "new.txt").exists()


async def test_write_file_shadow_overwrite(tmp_path) -> None:
    target = tmp_path / "exists.txt"
    target.write_text("old")
    out = await write_file_shadow(str(target), "new content")
    assert out["would_overwrite"] is True


async def test_delete_file_shadow_missing(tmp_path) -> None:
    out = await delete_file_shadow(str(tmp_path / "nope.txt"))
    assert out["exists"] is False


async def test_delete_file_shadow_present(tmp_path) -> None:
    target = tmp_path / "doomed.txt"
    target.write_text("x")
    out = await delete_file_shadow(str(target))
    assert out["exists"] is True


async def test_sql_shadow_select() -> None:
    out = await sql_shadow("SELECT * FROM users WHERE id = 1")
    assert out["operation"] == "SELECT"
    assert out["has_where_clause"] is True


async def test_sql_shadow_bulk_delete_warning() -> None:
    out = await sql_shadow("DELETE FROM users")
    assert "warning" in out
    assert out["destructive"] is True


async def test_http_shadow_redacts_auth() -> None:
    out = await http_shadow(
        "POST",
        "https://api.example.com/x",
        headers={"Authorization": "Bearer secret", "Content-Type": "application/json"},
    )
    assert out["headers"]["Authorization"] == "<redacted>"
    assert out["headers"]["Content-Type"] == "application/json"
