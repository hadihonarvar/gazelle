"""Shadow tools for filesystem operations."""

from __future__ import annotations

from pathlib import Path
from typing import Any


async def write_file_shadow(path: str, content: str) -> dict[str, Any]:
    p = Path(path)
    return {
        "would_write": path,
        "bytes": len(content.encode()),
        "would_overwrite": p.exists(),
        "would_overwrite_bytes": p.stat().st_size if p.exists() else None,
        "preview_first_200_chars": content[:200],
        "note": "no real execution — write_file_shadow preview only",
    }


async def delete_file_shadow(path: str) -> dict[str, Any]:
    p = Path(path)
    if not p.exists():
        return {
            "would_delete": path,
            "exists": False,
            "note": "file does not exist; delete would be a no-op",
        }
    return {
        "would_delete": path,
        "exists": True,
        "size_bytes": p.stat().st_size if p.is_file() else None,
        "is_directory": p.is_dir(),
        "note": "no real execution — delete_file_shadow preview only",
    }
