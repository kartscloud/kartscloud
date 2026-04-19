from __future__ import annotations

import asyncio
import hashlib
import json
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

import httpx
from dateutil import parser as dateparser

from ..config import Config
from ..db import cache_get, cache_set


CACHE_TTL_SECONDS = 15 * 60
RATE_LIMIT_FLOOR = 200
EXAM_KEYWORDS = ("exam", "midterm", "final", "test")
WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def _hash(s: str) -> str:
    return hashlib.sha1(s.encode()).hexdigest()[:10]


def _parse_link_header(link: str | None) -> dict[str, str]:
    if not link:
        return {}
    out: dict[str, str] = {}
    for part in link.split(","):
        m = re.match(r'\s*<([^>]+)>\s*;\s*rel="([^"]+)"', part)
        if m:
            out[m.group(2)] = m.group(1)
    return out


class CanvasSkill:
    name = "canvas"

    def __init__(self, config: Config, conn: sqlite3.Connection, transport: httpx.BaseTransport | None = None):
        self.config = config
        self.conn = conn
        if not config.canvas_token:
            raise RuntimeError("CANVAS_TOKEN not set in ~/.jarvis/.env")
        self._client = httpx.AsyncClient(
            base_url=config.canvas_base_url,
            headers={"Authorization": f"Bearer {config.canvas_token}"},
            timeout=20.0,
            transport=transport,
        )
        self._tz = ZoneInfo(config.user_timezone)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> "CanvasSkill":
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.aclose()

    async def _get(self, path: str, params: dict[str, Any] | None = None, paginate: bool = False) -> Any:
        params = params or {}
        key = f"canvas:{path}:{_hash(json.dumps(params, sort_keys=True))}:paginate={paginate}"
        cached = cache_get(self.conn, key, CACHE_TTL_SECONDS)
        if cached is not None:
            return json.loads(cached)

        if paginate:
            params = {**params, "per_page": 100}

        results: list[Any] = []
        url: str | None = path
        first = True
        while url:
            if first:
                r = await self._client.get(url, params=params)
                first = False
            else:
                r = await self._client.get(url)
            r.raise_for_status()
            self._honor_rate_limit(r.headers)
            body = r.json()
            if paginate and isinstance(body, list):
                results.extend(body)
                url = _parse_link_header(r.headers.get("Link")).get("next")
            else:
                results = body
                url = None

        cache_set(self.conn, key, json.dumps(results))
        return results

    def _honor_rate_limit(self, headers: httpx.Headers) -> None:
        remaining = headers.get("X-Rate-Limit-Remaining")
        if remaining is None:
            return
        try:
            if float(remaining) < RATE_LIMIT_FLOOR:
                # coarse throttle; don't block the event loop too long
                import time as _t
                _t.sleep(min(5.0, (RATE_LIMIT_FLOOR - float(remaining)) / 100.0))
        except ValueError:
            pass

    async def get_todo(self) -> list[dict[str, Any]]:
        return await self._get("/users/self/todo", paginate=True)

    async def get_upcoming_events(self) -> list[dict[str, Any]]:
        return await self._get("/users/self/upcoming_events", paginate=True)

    async def get_active_courses(self) -> list[dict[str, Any]]:
        return await self._get("/courses", {"enrollment_state": "active"}, paginate=True)

    async def get_course_assignments(self, course_id: int, bucket: str) -> list[dict[str, Any]]:
        return await self._get(
            f"/courses/{course_id}/assignments", {"bucket": bucket}, paginate=True
        )

    async def get_planner_items(self, start: datetime, end: datetime) -> list[dict[str, Any]]:
        return await self._get(
            "/planner/items",
            {"start_date": start.isoformat(), "end_date": end.isoformat()},
            paginate=True,
        )

    async def summary(self) -> dict[str, Any]:
        now = datetime.now(self._tz)
        start_of_today = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end_of_today = start_of_today + timedelta(days=1)
        end_of_week = start_of_today + timedelta(days=7)
        end_14d = start_of_today + timedelta(days=14)

        courses = await self.get_active_courses()
        course_by_id = {c["id"]: c.get("name") or c.get("course_code") or f"course_{c['id']}" for c in courses}

        # fetch assignment buckets in parallel per course
        async def fetch_for(cid: int) -> tuple[int, list[dict[str, Any]], list[dict[str, Any]]]:
            up_task = asyncio.create_task(self.get_course_assignments(cid, "upcoming"))
            od_task = asyncio.create_task(self.get_course_assignments(cid, "overdue"))
            return cid, await up_task, await od_task

        per_course_results = await asyncio.gather(*[fetch_for(cid) for cid in course_by_id]) if course_by_id else []

        planner = await self.get_planner_items(start_of_today, end_14d)

        # normalize items
        items: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()

        def add_item(course: str, title: str, due_at: str | None, item_type: str, url: str | None = None) -> None:
            if not title:
                return
            key = (title, due_at or "")
            if key in seen:
                return
            seen.add(key)
            parsed_due = None
            if due_at:
                try:
                    parsed_due = dateparser.isoparse(due_at).astimezone(self._tz)
                except (ValueError, TypeError):
                    parsed_due = None
            items.append(
                {
                    "course": course,
                    "title": title,
                    "due_at": due_at,
                    "due_dt": parsed_due,
                    "type": item_type,
                    "url": url,
                }
            )

        for cid, upcoming, overdue in per_course_results:
            cname = course_by_id[cid]
            for a in upcoming:
                add_item(cname, a.get("name", ""), a.get("due_at"), "assignment", a.get("html_url"))
            for a in overdue:
                add_item(cname, a.get("name", ""), a.get("due_at"), "assignment", a.get("html_url"))

        for p in planner:
            plannable = p.get("plannable", {}) or {}
            title = plannable.get("title") or plannable.get("name") or ""
            due_at = p.get("plannable_date") or plannable.get("due_at") or plannable.get("todo_date")
            course = course_by_id.get(p.get("course_id"), p.get("context_name", "planner"))
            add_item(course, title, due_at, p.get("plannable_type", "planner"), p.get("html_url"))

        overdue_list: list[dict[str, Any]] = []
        due_today: list[dict[str, Any]] = []
        due_this_week: dict[str, list[dict[str, Any]]] = {d: [] for d in WEEKDAYS}
        exams_14d: list[dict[str, Any]] = []
        by_course: dict[str, list[dict[str, Any]]] = {}

        for item in items:
            by_course.setdefault(item["course"], []).append(item)
            d = item.get("due_dt")
            title_lower = item["title"].lower()
            if any(kw in title_lower for kw in EXAM_KEYWORDS) and d and start_of_today <= d <= end_14d:
                exams_14d.append(item)
            if d is None:
                continue
            if d < now:
                overdue_list.append(item)
            elif start_of_today <= d < end_of_today:
                due_today.append(item)
            elif end_of_today <= d < end_of_week:
                due_this_week[WEEKDAYS[d.weekday()]].append(item)

        for lst in (overdue_list, due_today, *due_this_week.values(), exams_14d):
            lst.sort(key=lambda x: x.get("due_dt") or datetime.max.replace(tzinfo=timezone.utc))

        return {
            "overdue": [_strip(i) for i in overdue_list],
            "due_today": [_strip(i) for i in due_today],
            "due_this_week": {d: [_strip(i) for i in lst] for d, lst in due_this_week.items()},
            "exams_14d": [_strip(i) for i in exams_14d],
            "by_course": {c: [_strip(i) for i in lst] for c, lst in by_course.items()},
        }


def _strip(item: dict[str, Any]) -> dict[str, Any]:
    out = {k: v for k, v in item.items() if k != "due_dt"}
    if item.get("due_dt"):
        out["due_local"] = item["due_dt"].strftime("%Y-%m-%d %H:%M")
    return out


def render_summary(summary: dict[str, Any], console) -> None:
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text

    def render_list(title: str, items: list[dict[str, Any]]) -> None:
        if not items:
            return
        table = Table(title=title, title_style="header", show_header=True, header_style="dim", expand=False)
        table.add_column("when", style="dim")
        table.add_column("course")
        table.add_column("title")
        for it in items:
            when = it.get("due_local", "").split(" ")[-1] if it.get("due_local") else "—"
            table.add_row(when, it.get("course", ""), it.get("title", ""))
        console.print(table)

    render_list("OVERDUE", summary["overdue"])
    render_list("TODAY", summary["due_today"])

    week_items = []
    for day in WEEKDAYS:
        for it in summary["due_this_week"].get(day, []):
            week_items.append({**it, "_day": day})
    if week_items:
        table = Table(title="THIS WEEK", title_style="header", show_header=True, header_style="dim")
        table.add_column("day", style="dim")
        table.add_column("course")
        table.add_column("title")
        for it in week_items:
            table.add_row(it["_day"], it.get("course", ""), it.get("title", ""))
        console.print(table)

    if summary["exams_14d"]:
        table = Table(title="EXAMS (next 14d)", title_style="header", show_header=True, header_style="dim")
        table.add_column("date", style="dim")
        table.add_column("course")
        table.add_column("title")
        for it in summary["exams_14d"]:
            d = it.get("due_local", "").split(" ")[0] if it.get("due_local") else "—"
            table.add_row(d, it.get("course", ""), it.get("title", ""))
        console.print(table)

    if not any([summary["overdue"], summary["due_today"], week_items, summary["exams_14d"]]):
        console.print(Text("nothing on canvas right now", style="dim"))


CANVAS_TOOL_SCHEMA = {
    "name": "canvas_summary",
    "description": (
        "Get Carter's current school load from Canvas: overdue assignments, what's due today, "
        "what's due this week (grouped Mon-Sun), and exams in the next 14 days. "
        "Pulls all active courses dynamically — never assume which classes he's taking. "
        "Cached 15 minutes, so calling multiple times in a session is cheap."
    ),
    "input_schema": {"type": "object", "properties": {}, "required": []},
}
