"""Tests for the shadow library."""

from __future__ import annotations

from gazelle.shadows.filesystem import delete_file_shadow, write_file_shadow
from gazelle.shadows.http import http_shadow
from gazelle.shadows.shell import shell_shadow
from gazelle.shadows.sql import sql_shadow

# --- shell ----------------------------------------------------------------


async def test_shell_shadow_detects_destructive():
    out = await shell_shadow("rm -rf /tmp/foo")
    assert out["destructive_tokens"] == ["rm"]
    assert out["would_run"] == "rm -rf /tmp/foo"


async def test_shell_shadow_detects_network():
    out = await shell_shadow("curl -X POST https://example.com")
    assert out["network_egress"] is True


async def test_shell_shadow_detects_overwrite_redirect():
    out = await shell_shadow("echo hello > /tmp/marker.txt")
    assert "/tmp/marker.txt" in out["overwrites"]


# --- filesystem ------------------------------------------------------------


async def test_write_file_shadow_new(tmp_path):
    out = await write_file_shadow(str(tmp_path / "new.txt"), "hello")
    assert out["would_overwrite"] is False
    assert out["bytes"] == 5
    assert not (tmp_path / "new.txt").exists()


async def test_write_file_shadow_overwrite(tmp_path):
    target = tmp_path / "exists.txt"
    target.write_text("old")
    out = await write_file_shadow(str(target), "new content")
    assert out["would_overwrite"] is True
    assert out["would_overwrite_bytes"] == 3


async def test_delete_file_shadow_missing(tmp_path):
    out = await delete_file_shadow(str(tmp_path / "nope.txt"))
    assert out["exists"] is False


async def test_delete_file_shadow_present(tmp_path):
    target = tmp_path / "doomed.txt"
    target.write_text("x")
    out = await delete_file_shadow(str(target))
    assert out["exists"] is True
    assert out["size_bytes"] == 1
    assert target.exists()  # not actually deleted


# --- sql -------------------------------------------------------------------


async def test_sql_shadow_select():
    out = await sql_shadow("SELECT * FROM users WHERE id = 1")
    assert out["operation"] == "SELECT"
    assert out["tables"] == ["users"]
    assert out["has_where_clause"] is True
    assert out["destructive"] is False


async def test_sql_shadow_destructive_without_where_warns():
    out = await sql_shadow("DELETE FROM users")
    assert out["operation"] == "DELETE"
    assert out["destructive"] is True
    assert out["has_where_clause"] is False
    assert "warning" in out
    assert "ALL rows" in out["warning"]


# --- http ------------------------------------------------------------------


async def test_http_shadow_redacts_auth():
    out = await http_shadow(
        "POST",
        "https://api.example.com/users",
        headers={"Authorization": "Bearer secret", "Content-Type": "application/json"},
        body='{"name": "alice"}',
    )
    assert out["headers"]["Authorization"] == "<redacted>"
    assert out["headers"]["Content-Type"] == "application/json"
    assert out["host"] == "api.example.com"
    assert out["destructive"] is False


async def test_http_shadow_destructive():
    out = await http_shadow("DELETE", "https://api.example.com/users/1")
    assert out["destructive"] is True
