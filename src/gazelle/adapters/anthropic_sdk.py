"""Anthropic Claude adapter.

Wraps the Anthropic Messages API into the Gazelle Agent protocol. The user's
@tool decorators register with the registry; this adapter discovers them and
exposes them to Claude as tool_use definitions.

Example::

    from gazelle import tool, runtime
    from gazelle.adapters.anthropic_sdk import ClaudeAgent

    @tool(reversible=False, scope=["filesystem:write"])
    async def shell(cmd: str) -> str: ...

    agent = ClaudeAgent(model="claude-opus-4-7", system="You are a careful sysadmin.")
    await runtime.run(agent, task="clean up /tmp", policy="policy.yaml")

Requires `pip install gazelle[anthropic]` (or `pip install anthropic`).
"""

from __future__ import annotations

import inspect
from typing import Any

from gazelle.core.mediator import RegisteredTool, get_registry
from gazelle.sdk import FinalAnswer, Message, ToolCall


class ClaudeAgent:
    """An Agent that delegates step() to Anthropic's Claude.

    Conversation buffer is owned by the agent. The runtime supplies updates
    after each tool result, and the agent re-issues the call with the
    refreshed buffer.
    """

    def __init__(
        self,
        model: str = "claude-opus-4-7",
        system: str = "",
        max_tokens: int = 4096,
        client: Any | None = None,
    ) -> None:
        if client is None:
            try:
                from anthropic import AsyncAnthropic
            except ImportError as exc:
                raise ImportError(
                    "ClaudeAgent requires the 'anthropic' package. "
                    "Install with: pip install anthropic"
                ) from exc
            client = AsyncAnthropic()
        self.client = client
        self.model = model
        self.system = system
        self.max_tokens = max_tokens

    async def step(self, conversation: list[Message]):
        tools = _tools_for_anthropic()
        messages = _to_anthropic_messages(conversation)
        kwargs: dict[str, Any] = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "messages": messages,
        }
        if self.system:
            kwargs["system"] = self.system
        if tools:
            kwargs["tools"] = tools

        response = await self.client.messages.create(**kwargs)

        # Walk content blocks looking for a tool_use; fall back to text → FinalAnswer.
        text_parts: list[str] = []
        for block in response.content:
            if getattr(block, "type", None) == "tool_use":
                return ToolCall(
                    tool=block.name,
                    args=dict(block.input or {}),
                    call_id=block.id,
                )
            if getattr(block, "type", None) == "text":
                text_parts.append(block.text)
        return FinalAnswer(text="\n".join(text_parts).strip() or "(no response)")


# ---------------------------------------------------------------------------
# Translation helpers
# ---------------------------------------------------------------------------


def _tools_for_anthropic() -> list[dict[str, Any]]:
    """Convert every registered @tool into Anthropic tool-definition JSON."""
    out: list[dict[str, Any]] = []
    for name, registered in get_registry().all().items():
        schema = _signature_to_json_schema(registered)
        out.append(
            {
                "name": name,
                "description": registered.description or f"Tool {name}",
                "input_schema": schema,
            }
        )
    return out


def _signature_to_json_schema(registered: RegisteredTool) -> dict[str, Any]:
    """Naive but useful: inspect the function signature, produce JSON Schema."""
    sig = inspect.signature(registered.fn)
    properties: dict[str, Any] = {}
    required: list[str] = []
    for pname, param in sig.parameters.items():
        if pname in {"self", "cls"}:
            continue
        properties[pname] = _annotation_to_schema(param.annotation)
        if param.default is inspect.Parameter.empty:
            required.append(pname)
    schema = {
        "type": "object",
        "properties": properties,
    }
    if required:
        schema["required"] = required
    return schema


def _annotation_to_schema(annotation: Any) -> dict[str, Any]:
    if annotation is str:
        return {"type": "string"}
    if annotation is int:
        return {"type": "integer"}
    if annotation is float:
        return {"type": "number"}
    if annotation is bool:
        return {"type": "boolean"}
    if annotation is list or annotation is list[str]:
        return {"type": "array", "items": {"type": "string"}}
    if annotation is dict:
        return {"type": "object"}
    return {"type": "string"}  # fallback


def _to_anthropic_messages(conversation: list[Message]) -> list[dict[str, Any]]:
    """Convert gzl Messages into Anthropic Messages API shape.

    Tool results become user-role messages with `tool_result` content blocks.
    """
    msgs: list[dict[str, Any]] = []
    for m in conversation:
        if m.role == "system":
            # System content is handled via top-level `system` parameter.
            continue
        if m.role == "user":
            msgs.append({"role": "user", "content": m.content})
        elif m.role == "assistant":
            msgs.append({"role": "assistant", "content": m.content})
        elif m.role == "tool":
            msgs.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": m.tool_call_id or "unknown",
                            "content": m.content,
                        }
                    ],
                }
            )
    return msgs


__all__ = ["ClaudeAgent"]
