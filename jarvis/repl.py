from __future__ import annotations

import asyncio
import json
import sqlite3
import uuid
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from prompt_toolkit import PromptSession
from prompt_toolkit.formatted_text import FormattedText
from rich.console import Console

from .agent import Agent, AgentError
from .config import Config
from .db import append_chat, kv_get, kv_set, load_chat
from .prompts.system import SYSTEM_PROMPT
from .skills import CANVAS_TOOL_SCHEMA, CanvasSkill
from .theme import THEME


SLASH_COMMANDS = {"/exit", "/quit", "/clear", "/new", "/tools", "/resume"}


def _greeting(tz: ZoneInfo, user_name: str) -> str:
    hour = datetime.now(tz).hour
    if hour < 12:
        part = "good morning"
    elif hour < 18:
        part = "good afternoon"
    else:
        part = "good evening"
    return f"{part} sir. what do you want to do today?"


async def _warm_canvas_if_stale(
    config: Config, conn: sqlite3.Connection, console: Console
) -> None:
    tz = ZoneInfo(config.user_timezone)
    today_str = datetime.now(tz).strftime("%Y-%m-%d")
    last = kv_get(conn, "last_canvas_refresh_date")
    if last == today_str:
        return

    if not config.canvas_token:
        return

    with console.status("[dim]syncing canvas...[/dim]", spinner="dots"):
        try:
            async with CanvasSkill(config, conn) as canvas:
                await canvas.summary()
            kv_set(conn, "last_canvas_refresh_date", today_str)
        except Exception as exc:
            console.print(f"[dim](canvas sync failed: {exc})[/dim]")


async def run(config: Config, conn: sqlite3.Connection) -> None:
    console = Console(theme=THEME)
    try:
        agent = Agent(config)
    except AgentError as exc:
        console.print(f"[warn]{exc}[/warn]")
        console.print("[dim]run `jarvis doctor` for a full setup check.[/dim]")
        return

    await _warm_canvas_if_stale(config, conn, console)

    tz = ZoneInfo(config.user_timezone)
    console.print(f"[accent]{_greeting(tz, config.user_name)}[/accent]")
    console.print("[dim](type /exit to quit, /new for a new session)[/dim]")
    console.print()

    session_id = str(uuid.uuid4())
    kv_set(conn, "last_session", session_id)
    history: list[dict[str, Any]] = []

    session = PromptSession()

    tools = [CANVAS_TOOL_SCHEMA]

    async def canvas_handler(_: dict[str, Any]) -> Any:
        async with CanvasSkill(config, conn) as canvas:
            return await canvas.summary()

    tool_handlers = {"canvas_summary": canvas_handler}

    def on_tool_call(name: str) -> None:
        pretty = {"canvas_summary": "checking canvas"}.get(name, f"using {name}")
        console.print(f"[dim]({pretty}...)[/dim]")

    while True:
        try:
            user_input = await session.prompt_async(FormattedText([("#d4aa00 bold", "> ")]))
        except (EOFError, KeyboardInterrupt):
            console.print()
            return

        user_input = user_input.strip()
        if not user_input:
            continue

        if user_input in SLASH_COMMANDS:
            if user_input in ("/exit", "/quit"):
                return
            if user_input == "/clear":
                console.clear()
                continue
            if user_input == "/new":
                session_id = str(uuid.uuid4())
                kv_set(conn, "last_session", session_id)
                history = []
                console.print("[dim](new session)[/dim]")
                continue
            if user_input == "/tools":
                for t in tools:
                    console.print(f"[accent]{t['name']}[/accent] — {t['description']}")
                continue
            if user_input == "/resume":
                history = load_chat(conn, session_id)
                console.print(f"[dim](resumed {len(history)} messages)[/dim]")
                continue

        history.append({"role": "user", "content": user_input})
        append_chat(conn, session_id, "user", user_input)

        try:
            text, history = await agent.chat(
                messages=history,
                system=SYSTEM_PROMPT,
                tools=tools,
                tool_handlers=tool_handlers,
                on_tool_call=on_tool_call,
            )
        except KeyboardInterrupt:
            console.print("[dim](interrupted)[/dim]")
            continue
        except AgentError as exc:
            console.print(f"[warn]{exc}[/warn]")
            continue
        except Exception as exc:
            console.print(f"[warn]error: {exc}[/warn]")
            continue

        if text:
            console.print(text)
            console.print()
        append_chat(conn, session_id, "assistant", json.dumps(history[-1]["content"]))
