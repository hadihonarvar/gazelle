"""Smoke tests for the framework adapters.

These verify the adapter can be imported and the protocol shape is right.
Live integration is exercised in the examples/ directory against real
LangGraph / CrewAI / MCP installs (gated behind extras).
"""

from __future__ import annotations

import pytest


def test_langgraph_adapter_import_guard():
    """If langgraph is not installed, the adapter raises a useful import error."""
    import importlib
    import sys

    # Pretend langgraph is not installed for this test.
    saved = sys.modules.get("langgraph")
    sys.modules["langgraph"] = None  # type: ignore[assignment]
    try:
        if "gazelle.adapters.langgraph_adapter" in sys.modules:
            importlib.reload(sys.modules["gazelle.adapters.langgraph_adapter"])
        from gazelle.adapters.langgraph_adapter import LangGraphAgent

        with pytest.raises(ImportError, match="langgraph"):
            LangGraphAgent(compiled_graph=None)
    finally:
        if saved is not None:
            sys.modules["langgraph"] = saved
        else:
            sys.modules.pop("langgraph", None)


def test_crewai_adapter_import_guard():
    import importlib
    import sys

    saved = sys.modules.get("crewai")
    sys.modules["crewai"] = None  # type: ignore[assignment]
    try:
        if "gazelle.adapters.crewai_adapter" in sys.modules:
            importlib.reload(sys.modules["gazelle.adapters.crewai_adapter"])
        from gazelle.adapters.crewai_adapter import CrewAIAgent

        with pytest.raises(ImportError, match="crewai"):
            CrewAIAgent(crew=None)
    finally:
        if saved is not None:
            sys.modules["crewai"] = saved
        else:
            sys.modules.pop("crewai", None)


async def test_mcp_adapter_import_guard():
    import sys

    saved = sys.modules.get("mcp")
    sys.modules["mcp"] = None  # type: ignore[assignment]
    try:
        from gazelle.adapters.mcp import register_mcp_server

        with pytest.raises(ImportError, match="mcp"):
            await register_mcp_server("nonexistent-cmd")
    finally:
        if saved is not None:
            sys.modules["mcp"] = saved
        else:
            sys.modules.pop("mcp", None)
