from __future__ import annotations

import json
from typing import Any, Awaitable, Callable

import anthropic
from anthropic import Anthropic

from .config import Config


OPUS = "claude-opus-4-7"
SONNET = "claude-sonnet-4-6"

MAX_TOOL_ITERATIONS = 6
DEFAULT_MAX_TOKENS = 4096


ToolHandler = Callable[[dict[str, Any]], Awaitable[Any]]


class AgentError(RuntimeError):
    pass


class Agent:
    def __init__(self, config: Config):
        if not config.anthropic_api_key:
            raise AgentError(
                "ANTHROPIC_API_KEY not set. add it to ~/.jarvis/.env, then try again."
            )
        self.client = Anthropic(api_key=config.anthropic_api_key)
        self.config = config

    async def chat(
        self,
        messages: list[dict[str, Any]],
        system: str,
        tools: list[dict[str, Any]] | None = None,
        tool_handlers: dict[str, ToolHandler] | None = None,
        on_tool_call: Callable[[str], None] | None = None,
        model: str = OPUS,
        max_tokens: int = DEFAULT_MAX_TOKENS,
    ) -> tuple[str, list[dict[str, Any]]]:
        """
        Run a multi-turn tool-use loop. Returns (final_text, updated_messages).
        `messages` is not mutated — a new list is returned.
        """
        tools = tools or []
        tool_handlers = tool_handlers or {}
        convo = [dict(m) for m in messages]

        # System prompt as a block list so we can mark it ephemeral-cached.
        # Below Opus 4.7's 4096-token prefix minimum this is a silent no-op;
        # past that (when per-skill context lands) it starts paying off.
        system_param: list[dict[str, Any]] = [
            {
                "type": "text",
                "text": system,
                "cache_control": {"type": "ephemeral"},
            }
        ]

        for _ in range(MAX_TOOL_ITERATIONS):
            try:
                response = self.client.messages.create(
                    model=model,
                    max_tokens=max_tokens,
                    thinking={"type": "adaptive"},
                    system=system_param,
                    tools=tools,
                    messages=convo,
                )
            except anthropic.AuthenticationError as exc:
                raise AgentError(
                    "anthropic: 401 — API key invalid. regenerate it at console.anthropic.com and update ~/.jarvis/.env"
                ) from exc
            except anthropic.RateLimitError as exc:
                raise AgentError("anthropic: rate limited — try again in a bit") from exc
            except anthropic.APIStatusError as exc:
                raise AgentError(f"anthropic: {exc.status_code} {exc.message}") from exc

            assistant_blocks: list[dict[str, Any]] = []
            tool_uses: list[dict[str, Any]] = []
            text_parts: list[str] = []

            for block in response.content:
                if block.type == "text":
                    assistant_blocks.append({"type": "text", "text": block.text})
                    text_parts.append(block.text)
                elif block.type == "tool_use":
                    assistant_blocks.append(
                        {
                            "type": "tool_use",
                            "id": block.id,
                            "name": block.name,
                            "input": block.input,
                        }
                    )
                    tool_uses.append(
                        {"id": block.id, "name": block.name, "input": block.input}
                    )
                elif block.type == "thinking":
                    assistant_blocks.append(
                        {
                            "type": "thinking",
                            "thinking": getattr(block, "thinking", ""),
                            "signature": getattr(block, "signature", ""),
                        }
                    )

            convo.append({"role": "assistant", "content": assistant_blocks})

            if response.stop_reason != "tool_use" or not tool_uses:
                return "\n".join(text_parts).strip(), convo

            tool_results: list[dict[str, Any]] = []
            for tu in tool_uses:
                if on_tool_call:
                    on_tool_call(tu["name"])
                handler = tool_handlers.get(tu["name"])
                if handler is None:
                    result: Any = {"error": f"no handler for tool {tu['name']}"}
                else:
                    try:
                        result = await handler(tu["input"] or {})
                    except Exception as exc:
                        result = {"error": str(exc)}
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": tu["id"],
                        "content": json.dumps(result, default=str),
                    }
                )
            convo.append({"role": "user", "content": tool_results})

        return "stopped: tool loop hit max iterations", convo


def to_user_message(text: str) -> dict[str, Any]:
    return {"role": "user", "content": text}
