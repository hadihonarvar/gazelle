"""Tests for the LLM adapters. Uses mocked clients so no API key is needed."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from lynx import tool
from lynx.adapters.anthropic_sdk import (
    ClaudeAgent,
    _signature_to_json_schema,
    _to_anthropic_messages,
)
from lynx.adapters.openai_sdk import OpenAIAgent, _to_openai_messages
from lynx.core.mediator import get_registry
from lynx.sdk import FinalAnswer, Message, ToolCall


@pytest.fixture
def registered_tools():
    get_registry().clear()

    @tool(cost="low", reversible=True, scope=["filesystem:read"])
    async def list_dir(path: str) -> list[str]:
        """List a directory."""
        return []

    @tool(cost="medium", reversible=False, scope=["filesystem:write"])
    async def write_file(path: str, content: str) -> str:
        """Write a file."""
        return ""

    yield
    get_registry().clear()


def test_signature_to_json_schema(registered_tools):
    reg = get_registry().get("write_file")
    schema = _signature_to_json_schema(reg)
    assert schema["type"] == "object"
    assert "path" in schema["properties"]
    assert "content" in schema["properties"]
    assert schema["properties"]["path"]["type"] == "string"
    assert set(schema["required"]) == {"path", "content"}


def test_anthropic_message_translation():
    conv = [
        Message(role="user", content="hello"),
        Message(role="assistant", content="hi back"),
        Message(role="tool", content="result", tool_call_id="t1", name="list_dir"),
    ]
    out = _to_anthropic_messages(conv)
    assert out[0] == {"role": "user", "content": "hello"}
    assert out[1] == {"role": "assistant", "content": "hi back"}
    assert out[2]["role"] == "user"
    assert out[2]["content"][0]["type"] == "tool_result"
    assert out[2]["content"][0]["tool_use_id"] == "t1"


def test_openai_message_translation():
    conv = [
        Message(role="user", content="hello"),
        Message(role="tool", content="ok", tool_call_id="oa-1"),
    ]
    out = _to_openai_messages(conv, system="be careful")
    assert out[0] == {"role": "system", "content": "be careful"}
    assert out[1] == {"role": "user", "content": "hello"}
    assert out[2] == {"role": "tool", "tool_call_id": "oa-1", "content": "ok"}


class _FakeAnthropicResponse:
    def __init__(self, content):
        self.content = content


class _FakeAnthropicMessages:
    def __init__(self, response):
        self._response = response
        self.last_kwargs = None

    async def create(self, **kwargs):
        self.last_kwargs = kwargs
        return self._response


class _FakeAnthropicClient:
    def __init__(self, response):
        self.messages = _FakeAnthropicMessages(response)


async def test_claude_agent_tool_call(registered_tools):
    block = SimpleNamespace(type="tool_use", name="list_dir", input={"path": "/tmp"}, id="tu-1")
    response = _FakeAnthropicResponse([block])
    client = _FakeAnthropicClient(response)
    agent = ClaudeAgent(model="claude-opus-4-7", client=client)
    action = await agent.step([Message(role="user", content="list /tmp")])
    assert isinstance(action, ToolCall)
    assert action.tool == "list_dir"
    assert action.args == {"path": "/tmp"}


async def test_claude_agent_final_answer(registered_tools):
    block = SimpleNamespace(type="text", text="all done")
    response = _FakeAnthropicResponse([block])
    client = _FakeAnthropicClient(response)
    agent = ClaudeAgent(model="claude-opus-4-7", client=client)
    action = await agent.step([Message(role="user", content="hi")])
    assert isinstance(action, FinalAnswer)
    assert action.text == "all done"


class _FakeOpenAIChoice:
    def __init__(self, message):
        self.message = message


class _FakeOpenAIResponse:
    def __init__(self, message):
        self.choices = [_FakeOpenAIChoice(message)]


class _FakeOpenAIChatCompletions:
    def __init__(self, response):
        self._response = response
        self.last_kwargs = None

    async def create(self, **kwargs):
        self.last_kwargs = kwargs
        return self._response


class _FakeOpenAIClient:
    def __init__(self, response):
        self.chat = SimpleNamespace(completions=_FakeOpenAIChatCompletions(response))


async def test_openai_agent_tool_call(registered_tools):
    fn = SimpleNamespace(name="list_dir", arguments='{"path": "/tmp"}')
    tc = SimpleNamespace(id="oa-1", function=fn)
    msg = SimpleNamespace(content=None, tool_calls=[tc])
    response = _FakeOpenAIResponse(msg)
    client = _FakeOpenAIClient(response)
    agent = OpenAIAgent(model="gpt-5", client=client)
    action = await agent.step([Message(role="user", content="list /tmp")])
    assert isinstance(action, ToolCall)
    assert action.tool == "list_dir"
    assert action.args == {"path": "/tmp"}


async def test_openai_agent_final_answer(registered_tools):
    msg = SimpleNamespace(content="done", tool_calls=None)
    response = _FakeOpenAIResponse(msg)
    client = _FakeOpenAIClient(response)
    agent = OpenAIAgent(model="gpt-5", client=client)
    action = await agent.step([Message(role="user", content="hi")])
    assert isinstance(action, FinalAnswer)
    assert action.text == "done"
