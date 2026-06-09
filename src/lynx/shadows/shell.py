"""Shadow for shell command execution.

Parses the command line and identifies probable effects (deletes, overwrites,
network egress) without running the command.
"""

from __future__ import annotations

import glob
import re
import shlex
from typing import Any

_DESTRUCTIVE_TOKENS = {"rm", "unlink", "rmdir", "del", "shred", "drop", "truncate"}
_NETWORK_TOKENS = {"curl", "wget", "scp", "rsync", "ssh", "ftp", "nc"}
_OVERWRITE_REDIRECT = re.compile(r"(?<!\d)(>)(?!&)")


async def shell_shadow(cmd: str) -> dict[str, Any]:
    """Estimate the would-be effects of running `cmd`.

    Returns a dict with:
        - would_run:           the literal command
        - tokens:              shlex'd tokens (best-effort)
        - destructive_tokens:  any destructive command words detected
        - network_egress:      whether the command appears to make a network call
        - paths_affected:      expanded glob of paths the command targets
        - overwrites:          paths matching `>` redirects
        - note:                always present, says no real execution happened
    """
    try:
        tokens = shlex.split(cmd, comments=False)
    except ValueError:
        tokens = cmd.split()

    destructive = sorted(t for t in tokens if t in _DESTRUCTIVE_TOKENS)
    network = sorted(t for t in tokens if t in _NETWORK_TOKENS)

    paths_affected: list[str] = []
    if destructive:
        # Anything that looks like a path or glob after a destructive token.
        for t in tokens:
            if t.startswith(("-", "&", "|", ">", "<", ";")):
                continue
            if t in _DESTRUCTIVE_TOKENS:
                continue
            if "/" in t or "*" in t or "?" in t:
                expanded = sorted(glob.glob(t))
                paths_affected.extend(expanded or [t])

    overwrites = [t for t in re.findall(r">\s*(\S+)", cmd)]

    return {
        "would_run": cmd,
        "tokens": tokens,
        "destructive_tokens": destructive,
        "network_egress": bool(network),
        "paths_affected": paths_affected,
        "overwrites": overwrites,
        "note": "no real execution — shell_shadow preview only",
    }
