"""Shared helpers used by the LLM adapters.

Kept private so the adapter layer can evolve without touching public API.
"""

from __future__ import annotations

import inspect
import typing
from typing import Any, Literal, Union, get_args, get_origin

from lynx.core.types import ToolDef, ToolSet

_ = typing  # keep the import for forward-ref resolution in get_type_hints

__all__ = ["tooldef_to_json_schema", "toolset_to_anthropic_tools", "toolset_to_openai_tools"]


def tooldef_to_json_schema(td: ToolDef) -> dict[str, Any]:
    """Reflect a ToolDef's underlying function signature into JSON Schema.

    Pure: depends only on the function's annotations.
    """
    sig = inspect.signature(td.fn)
    try:
        hints = typing.get_type_hints(td.fn)
    except Exception:
        # If the function uses forward refs that can't be resolved, fall back
        # to the raw annotations rather than fail schema generation.
        hints = {}
    properties: dict[str, Any] = {}
    required: list[str] = []
    for pname, param in sig.parameters.items():
        if pname in {"self", "cls"} or pname.startswith("_"):
            continue
        annotation = hints.get(pname, param.annotation)
        properties[pname] = _annotation_to_schema(annotation)
        if param.default is inspect.Parameter.empty:
            required.append(pname)
    schema: dict[str, Any] = {"type": "object", "properties": properties}
    if required:
        schema["required"] = required
    return schema


_PRIMITIVE_BY_NAME: dict[str, dict[str, Any]] = {
    "str": {"type": "string"},
    "int": {"type": "integer"},
    "float": {"type": "number"},
    "bool": {"type": "boolean"},
    "list": {"type": "array"},
    "dict": {"type": "object"},
    "None": {"type": "null"},
}


def _annotation_to_schema(annotation: Any) -> dict[str, Any]:
    if annotation is inspect.Parameter.empty:
        # Untyped parameter — best we can do is "anything".
        return {}
    if isinstance(annotation, str):
        return _PRIMITIVE_BY_NAME.get(annotation, {"type": "string"})

    if annotation is str:
        return {"type": "string"}
    if annotation is int:
        return {"type": "integer"}
    if annotation is float:
        return {"type": "number"}
    if annotation is bool:
        return {"type": "boolean"}
    if annotation is type(None):
        return {"type": "null"}
    if annotation is list:
        return {"type": "array"}
    if annotation is dict:
        return {"type": "object"}
    if annotation is bytes:
        return {"type": "string", "format": "byte"}

    origin = get_origin(annotation)
    args = get_args(annotation)

    if origin is Literal:
        # Literal["a", "b"] → enum of those values.
        return {"enum": list(args)}

    if origin is Union:
        # Optional[X] / X | None — drop None and recurse on the other arm.
        non_none = [a for a in args if a is not type(None)]
        if len(non_none) == 1:
            inner = _annotation_to_schema(non_none[0])
            inner["nullable"] = True
            return inner
        return {"anyOf": [_annotation_to_schema(a) for a in args]}

    if origin is list:
        item = args[0] if args else str
        return {"type": "array", "items": _annotation_to_schema(item)}

    if origin is dict:
        return {"type": "object"}

    if origin is tuple:
        return {
            "type": "array",
            "items": [_annotation_to_schema(a) for a in args] if args else {"type": "string"},
        }

    # Unknown / complex annotation — accept any JSON value rather than lying
    # about it being a string.
    return {}


def toolset_to_anthropic_tools(tools: ToolSet) -> list[dict[str, Any]]:
    """Anthropic Messages API tool-definition shape."""
    return [
        {
            "name": td.name,
            "description": td.description or f"Tool {td.name}",
            "input_schema": tooldef_to_json_schema(td),
        }
        for td in tools.tools.values()
    ]


def toolset_to_openai_tools(tools: ToolSet) -> list[dict[str, Any]]:
    """OpenAI Chat Completions API tool-definition shape."""
    return [
        {
            "type": "function",
            "function": {
                "name": td.name,
                "description": td.description or f"Tool {td.name}",
                "parameters": tooldef_to_json_schema(td),
            },
        }
        for td in tools.tools.values()
    ]
