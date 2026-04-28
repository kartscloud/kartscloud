from __future__ import annotations

from types import SimpleNamespace

import pytest

from jarvis.agent import Agent
from jarvis.config import Config


class _FakeResponse:
    def __init__(self, blocks, stop_reason):
        self.content = blocks
        self.stop_reason = stop_reason


class _FakeMessages:
    def __init__(self, scripted):
        self._scripted = list(scripted)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self._scripted.pop(0)


class _FakeClient:
    def __init__(self, scripted):
        self.messages = _FakeMessages(scripted)


async def test_agent_tool_loop_calls_handler(monkeypatch):
    config = Config(anthropic_api_key="fake")
    agent = Agent.__new__(Agent)
    agent.config = config

    tool_use_block = SimpleNamespace(type="tool_use", id="t1", name="canvas_summary", input={})
    final_text_block = SimpleNamespace(type="text", text="ok here's your day")

    agent.client = _FakeClient([
        _FakeResponse([tool_use_block], stop_reason="tool_use"),
        _FakeResponse([final_text_block], stop_reason="end_turn"),
    ])

    called = {}

    async def handler(inp):
        called["yes"] = True
        return {"overdue": [], "due_today": []}

    text, convo = await agent.chat(
        messages=[{"role": "user", "content": "school shit"}],
        system="you are JARVIS",
        tools=[{"name": "canvas_summary", "description": "x", "input_schema": {"type": "object", "properties": {}}}],
        tool_handlers={"canvas_summary": handler},
    )

    assert called.get("yes") is True
    assert "ok here" in text
    assert len(agent.client.messages.calls) == 2
