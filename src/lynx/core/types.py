"""Core immutable types for Lynx v2.

Every type here is ``frozen=True, slots=True``. No mutation. No globals.
Pure values that flow through the kernel and out to sinks.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Literal

__all__ = [
    "ActionRequest",
    "ActionResult",
    "ApprovalDecision",
    "ApprovalRequest",
    "AuditEvent",
    "Budget",
    "Decision",
    "ExecutionContext",
    "FinalAnswer",
    "Message",
    "Principal",
    "RunResult",
    "ToolCall",
    "ToolDef",
    "ToolMetadata",
    "ToolSet",
    "Verdict",
    "canonical_json",
    "new_correlation_id",
    "now_utc",
]


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class Verdict(StrEnum):
    ALLOW = "allow"
    DENY = "deny"
    DRY_RUN = "dry_run"
    APPROVE_REQUIRED = "approve_required"
    TRANSFORM = "transform"


# ---------------------------------------------------------------------------
# Time / IDs
# ---------------------------------------------------------------------------


def now_utc() -> datetime:
    return datetime.now(UTC)


def new_correlation_id() -> str:
    """A UUID4 string. Used to group all events from one ``run_agent`` call."""
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Principal / Budget / Context — all frozen
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Principal:
    kind: Literal["user", "service", "agent"]
    id: str
    name: str | None = None


@dataclass(frozen=True, slots=True)
class Budget:
    usd: float | None = None
    duration_seconds: int | None = None
    tokens: int | None = None
    steps: int | None = 50


@dataclass(frozen=True, slots=True)
class ExecutionContext:
    principal: Principal
    environment: str
    workspace: str
    correlation_id: str
    step_seq: int
    timestamp: datetime
    extra: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}))


# ---------------------------------------------------------------------------
# Tool metadata + ToolDef + ToolSet (immutable)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ToolMetadata:
    cost: Literal["low", "medium", "high"]
    reversible: bool
    scope: tuple[str, ...]
    blast_radius_hint: int | None = None
    has_shadow: bool = False


@dataclass(frozen=True, slots=True)
class ToolDef:
    """A tool ready to be passed to ``run_agent``.

    Holds the (real) function, an optional shadow, and the declared metadata.
    All references; no execution state.
    """

    name: str
    description: str
    fn: Callable[..., Awaitable[Any]]
    shadow_fn: Callable[..., Awaitable[Any]] | None
    metadata: ToolMetadata


@dataclass(frozen=True, slots=True)
class ToolSet:
    """An immutable mapping of tool name to ToolDef.

    Build with ``ToolSet.from_functions(*fns)``; operations return new sets.
    """

    tools: Mapping[str, ToolDef] = field(default_factory=lambda: MappingProxyType({}))

    @classmethod
    def from_functions(cls, *fns: Callable[..., Awaitable[Any]]) -> ToolSet:
        """Build a ToolSet from functions decorated with ``@tool``.

        Each function must carry ``__lynx_meta__`` (set by the decorator).
        Functions without that attribute raise ``TypeError``.
        """
        out: dict[str, ToolDef] = {}
        for fn in fns:
            meta = getattr(fn, "__lynx_meta__", None)
            if meta is None:
                raise TypeError(
                    f"{fn.__name__} is not decorated with @tool — cannot include in ToolSet"
                )
            out[meta.name] = meta
        return cls(tools=MappingProxyType(out))

    def with_tool(self, t: ToolDef) -> ToolSet:
        return ToolSet(tools=MappingProxyType({**self.tools, t.name: t}))

    def without_tool(self, name: str) -> ToolSet:
        new = dict(self.tools)
        new.pop(name, None)
        return ToolSet(tools=MappingProxyType(new))

    def union(self, other: ToolSet) -> ToolSet:
        return ToolSet(tools=MappingProxyType({**self.tools, **other.tools}))

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self.tools.keys()))

    def get(self, name: str) -> ToolDef:
        if name not in self.tools:
            raise KeyError(f"Unknown tool: {name}")
        return self.tools[name]

    def __len__(self) -> int:
        return len(self.tools)


# ---------------------------------------------------------------------------
# Agent conversation primitives — frozen
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Message:
    role: Literal["system", "user", "assistant", "tool"]
    content: str
    name: str | None = None
    tool_call_id: str | None = None


@dataclass(frozen=True, slots=True)
class ToolCall:
    tool: str
    args: Mapping[str, Any]
    call_id: str = ""


@dataclass(frozen=True, slots=True)
class FinalAnswer:
    text: str


# ---------------------------------------------------------------------------
# Request / Decision / Result — frozen
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ActionRequest:
    tool: str
    args: Mapping[str, Any]
    declared: ToolMetadata
    context: ExecutionContext


@dataclass(frozen=True, slots=True)
class Decision:
    verdict: Verdict
    reason: str = ""
    matched_rules: tuple[str, ...] = ()
    approvers: tuple[str, ...] = ()
    transform_args: Mapping[str, Any] | None = None
    timeout_seconds: int | None = None


@dataclass(frozen=True, slots=True)
class ActionResult:
    ok: bool
    value: Any | None = None
    error: str | None = None
    duration_ms: int = 0


# ---------------------------------------------------------------------------
# Approval types — frozen, sync-handler-only
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ApprovalRequest:
    request: ActionRequest
    decision: Decision
    correlation_id: str


@dataclass(frozen=True, slots=True)
class ApprovalDecision:
    granted: bool
    approver: str
    reason: str = ""


# ---------------------------------------------------------------------------
# Audit event — sinks consume this; no hash chain
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AuditEvent:
    correlation_id: str
    bundle_id: str
    seq: int
    kind: str
    timestamp: datetime
    body: Mapping[str, Any]


# ---------------------------------------------------------------------------
# Final result of a run — frozen
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RunResult:
    correlation_id: str
    bundle_id: str
    final_answer: str | None = None
    error: str | None = None
    steps_taken: int = 0


# ---------------------------------------------------------------------------
# Canonical JSON (still needed for bundle_id hashing in policy module)
# ---------------------------------------------------------------------------


def canonical_json(obj: Any) -> str:
    """Sorted-keys, no-whitespace JSON. RFC 8785 / JCS-ish."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=_default)


def _default(o: Any) -> Any:
    if isinstance(o, datetime):
        return o.isoformat()
    if isinstance(o, (set, frozenset, tuple)):
        return list(o)
    if isinstance(o, Mapping):
        return dict(o)
    if hasattr(o, "__dataclass_fields__"):
        from dataclasses import asdict

        return asdict(o)
    raise TypeError(f"Cannot canonicalize {type(o).__name__}")
