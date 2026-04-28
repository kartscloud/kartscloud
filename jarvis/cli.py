from __future__ import annotations

import asyncio

import click
import httpx
from rich.console import Console

from . import __version__, scheduler
from .agent import Agent, AgentError
from .config import JARVIS_HOME, Config, ensure_dirs, load_config
from .db import get_conn, init_db
from .prompts.system import SYSTEM_PROMPT
from .skills import CANVAS_TOOL_SCHEMA, CanvasSkill, render_summary
from .theme import THEME


NOT_IMPL = "not yet implemented in v0.1 — coming soon"


def _bootstrap() -> tuple[Config, Console]:
    config = load_config()
    ensure_dirs(config)
    conn = get_conn(config.db_path)
    init_db(conn)
    conn.close()
    console = Console(theme=THEME)
    return config, console


@click.group(invoke_without_command=True)
@click.version_option(__version__, prog_name="jarvis")
@click.pass_context
def main(ctx: click.Context) -> None:
    """JARVIS — Carter's personal operational agent."""
    if ctx.invoked_subcommand is None:
        config, _ = _bootstrap()
        conn = get_conn(config.db_path)
        try:
            from .repl import run as repl_run
            asyncio.run(repl_run(config, conn))
        finally:
            conn.close()


@main.command()
@click.option("--json", "as_json", is_flag=True, help="emit raw JSON instead of a rendered table")
def canvas(as_json: bool) -> None:
    """School summary: overdue, today, week, exams."""
    config, console = _bootstrap()

    async def _go() -> None:
        conn = get_conn(config.db_path)
        try:
            async with CanvasSkill(config, conn) as c:
                summary = await c.summary()
        finally:
            conn.close()
        if as_json:
            import json as _json
            click.echo(_json.dumps(summary, indent=2, default=str))
        else:
            render_summary(summary, console)

    try:
        asyncio.run(_go())
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 401:
            console.print("[warn]canvas: 401 unauthorized — token expired or revoked. regenerate it in Canvas → Account → Settings and update ~/.jarvis/.env[/warn]")
        else:
            console.print(f"[warn]canvas: {exc.response.status_code} {exc.response.reason_phrase}[/warn]")
        raise click.Abort()
    except RuntimeError as exc:
        console.print(f"[warn]{exc}[/warn]")
        raise click.Abort()


@main.command()
@click.argument("question", required=True)
def ask(question: str) -> None:
    """One-shot question with full agent context."""
    config, console = _bootstrap()

    async def _go() -> None:
        agent = Agent(config)
        conn = get_conn(config.db_path)

        async def canvas_handler(_: dict) -> dict:
            async with CanvasSkill(config, conn) as c:
                return await c.summary()

        try:
            text, _ = await agent.chat(
                messages=[{"role": "user", "content": question}],
                system=SYSTEM_PROMPT,
                tools=[CANVAS_TOOL_SCHEMA] if config.canvas_token else [],
                tool_handlers={"canvas_summary": canvas_handler},
                on_tool_call=lambda n: console.print(f"[dim]({n}...)[/dim]"),
            )
        finally:
            conn.close()
        console.print(text)

    try:
        asyncio.run(_go())
    except AgentError as exc:
        console.print(f"[warn]{exc}[/warn]")
        raise click.Abort()
    except RuntimeError as exc:
        console.print(f"[warn]{exc}[/warn]")
        raise click.Abort()


@main.command()
def doctor() -> None:
    """Verify config, DB, and external reachability."""
    config, console = _bootstrap()

    console.print(f"[header]jarvis doctor[/header]")
    console.print(f"  home       {JARVIS_HOME}")
    console.print(f"  db         {config.db_path}")
    console.print(f"  user       {config.user_name} ({config.user_timezone})")

    def mark(ok: bool, label: str, detail: str = "") -> None:
        tag = "[ok]ok[/ok]" if ok else "[warn]--[/warn]"
        suffix = f" [dim]{detail}[/dim]" if detail else ""
        console.print(f"  {tag}  {label}{suffix}")

    # Anthropic
    if not config.anthropic_api_key:
        mark(False, "ANTHROPIC_API_KEY", "missing — add to ~/.jarvis/.env")
    else:
        mark(True, "ANTHROPIC_API_KEY", f"set ({config.anthropic_api_key[:10]}...)")

    # Canvas
    if not config.canvas_token:
        mark(False, "CANVAS_TOKEN", "missing — add to ~/.jarvis/.env")
    else:
        async def _probe() -> tuple[bool, str]:
            conn = get_conn(config.db_path)
            try:
                async with CanvasSkill(config, conn) as c:
                    courses = await c.get_active_courses()
                return True, f"{len(courses)} active course(s)"
            except httpx.HTTPStatusError as exc:
                return False, f"{exc.response.status_code} {exc.response.reason_phrase}"
            except Exception as exc:
                return False, str(exc)[:80]
            finally:
                conn.close()

        ok, detail = asyncio.run(_probe())
        mark(ok, "canvas reach", detail)

    # DB
    conn = get_conn(config.db_path)
    try:
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )]
        mark(True, "sqlite tables", ", ".join(tables))
    finally:
        conn.close()

    console.print()
    if config.anthropic_api_key and config.canvas_token:
        console.print("[ok]all green. run:[/ok] jarvis")
    else:
        console.print("[warn]fill in ~/.jarvis/.env, then re-run doctor.[/warn]")


@main.group()
def schedule() -> None:
    """Start or stop the background scheduler."""


@schedule.command("start")
def schedule_start() -> None:
    click.echo(scheduler.start())


@schedule.command("stop")
def schedule_stop() -> None:
    click.echo(scheduler.stop())


def _stub(cmd_name: str) -> click.Command:
    @click.command(name=cmd_name, help=f"{cmd_name} — {NOT_IMPL}")
    def _cmd(*args, **kwargs):
        click.echo(f"{cmd_name}: {NOT_IMPL}")

    return _cmd


@main.command("brief")
def brief_cmd() -> None:
    """Main HTML daily brief (stub)."""
    click.echo(f"brief: {NOT_IMPL}")


@main.command("ate")
@click.argument("text", required=False)
def ate_cmd(text: str | None) -> None:
    """Log food via natural language (stub)."""
    click.echo(f"ate: {NOT_IMPL}")


@main.command("gym")
@click.argument("text", required=False)
def gym_cmd(text: str | None) -> None:
    """Log workout via natural language (stub)."""
    click.echo(f"gym: {NOT_IMPL}")


@main.command("cardio")
@click.argument("text", required=False)
def cardio_cmd(text: str | None) -> None:
    """Log cardio (stub)."""
    click.echo(f"cardio: {NOT_IMPL}")


@main.command("macros")
def macros_cmd() -> None:
    """Today's totals vs targets (stub)."""
    click.echo(f"macros: {NOT_IMPL}")


@main.command("week")
def week_cmd() -> None:
    """Weekly training + macro summary (stub)."""
    click.echo(f"week: {NOT_IMPL}")


@main.command("markets")
def markets_cmd() -> None:
    """Market block (stub)."""
    click.echo(f"markets: {NOT_IMPL}")


@main.group("jobs", invoke_without_command=True)
@click.pass_context
def jobs_cmd(ctx: click.Context) -> None:
    """New postings, scored (stub)."""
    if ctx.invoked_subcommand is None:
        click.echo(f"jobs: {NOT_IMPL}")


@jobs_cmd.command("new")
def jobs_new_cmd() -> None:
    click.echo(f"jobs new: {NOT_IMPL}")


@main.command("apply")
@click.argument("job_id")
def apply_cmd(job_id: str) -> None:
    """Mark a job as applied (stub)."""
    click.echo(f"apply: {NOT_IMPL}")


@main.command("status")
@click.argument("job_id")
@click.argument("status")
def status_cmd(job_id: str, status: str) -> None:
    """Update application status (stub)."""
    click.echo(f"status: {NOT_IMPL}")


@main.command("pipeline")
def pipeline_cmd() -> None:
    """Application pipeline view (stub)."""
    click.echo(f"pipeline: {NOT_IMPL}")


@main.command("next")
def next_cmd() -> None:
    """Top 3 to-dos right now (stub)."""
    click.echo(f"next: {NOT_IMPL}")


if __name__ == "__main__":
    main()
