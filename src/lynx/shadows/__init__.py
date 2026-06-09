"""Pre-built shadow implementations for common dangerous tools.

A shadow is a function with the same signature as the real tool but no
side effects — it returns a preview of what the action *would* do. The
mediator calls a tool's shadow when the PDP returns the DRY_RUN verdict.

Use these as drop-in helpers when wrapping common operations::

    from lynx import tool
    from lynx.shadows import shell_shadow, write_file_shadow

    @tool(reversible=False, scope=["compute:exec"])
    async def shell(cmd: str) -> str:
        ...

    shell.shadow(shell_shadow)
"""

from lynx.shadows.filesystem import (
    delete_file_shadow,
    write_file_shadow,
)
from lynx.shadows.http import http_shadow
from lynx.shadows.shell import shell_shadow
from lynx.shadows.sql import sql_shadow

__all__ = [
    "delete_file_shadow",
    "http_shadow",
    "shell_shadow",
    "sql_shadow",
    "write_file_shadow",
]
