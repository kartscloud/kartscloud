from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from jarvis.config import Config
from jarvis.db import init_db
from jarvis.skills.canvas import CanvasSkill


def _iso_in(hours: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()


def _make_handler():
    """Mock transport handler for Canvas endpoints."""

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        params = dict(request.url.params)

        if path.endswith("/courses"):
            return httpx.Response(
                200,
                json=[
                    {"id": 1, "name": "CS 122B", "course_code": "CS122B"},
                    {"id": 2, "name": "MATH 2B", "course_code": "MATH2B"},
                ],
            )
        if path.endswith("/assignments"):
            course_id = int(path.split("/")[-2])
            bucket = params.get("bucket", "upcoming")
            if course_id == 1 and bucket == "upcoming":
                return httpx.Response(200, json=[
                    {"id": 101, "name": "Homework 4", "due_at": _iso_in(5), "html_url": "x"},
                    {"id": 102, "name": "Midterm Exam", "due_at": _iso_in(24 * 5), "html_url": "x"},
                ])
            if course_id == 1 and bucket == "overdue":
                return httpx.Response(200, json=[
                    {"id": 99, "name": "Lab 1", "due_at": _iso_in(-24 * 3), "html_url": "x"},
                ])
            if course_id == 2 and bucket == "upcoming":
                return httpx.Response(200, json=[
                    {"id": 201, "name": "Webwork 9", "due_at": _iso_in(3), "html_url": "x"},
                ])
            return httpx.Response(200, json=[])
        if path.endswith("/planner/items"):
            return httpx.Response(200, json=[])
        if path.endswith("/todo") or path.endswith("/upcoming_events"):
            return httpx.Response(200, json=[])
        return httpx.Response(404, json={"error": "not found", "path": path})

    return handler


def _make_skill(tmp_path):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_db(conn)

    config = Config(canvas_token="fake", canvas_base_url="https://canvas.test/api/v1")
    transport = httpx.MockTransport(_make_handler())
    return CanvasSkill(config, conn, transport=transport)


async def test_summary_shape(tmp_path):
    skill = _make_skill(tmp_path)
    async with skill:
        summary = await skill.summary()

    assert set(summary.keys()) == {"overdue", "due_today", "due_this_week", "exams_14d", "by_course"}
    assert isinstance(summary["due_this_week"], dict)
    assert set(summary["due_this_week"].keys()) == {"Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"}


async def test_summary_classifies_items(tmp_path):
    skill = _make_skill(tmp_path)
    async with skill:
        summary = await skill.summary()

    titles_overdue = {i["title"] for i in summary["overdue"]}
    assert "Lab 1" in titles_overdue

    all_week = {i["title"] for day in summary["due_this_week"].values() for i in day}
    all_items = all_week | {i["title"] for i in summary["due_today"]}
    assert "Homework 4" in all_items
    assert "Webwork 9" in all_items

    exam_titles = {i["title"] for i in summary["exams_14d"]}
    assert "Midterm Exam" in exam_titles


async def test_by_course_populated(tmp_path):
    skill = _make_skill(tmp_path)
    async with skill:
        summary = await skill.summary()

    assert "CS 122B" in summary["by_course"]
    assert "MATH 2B" in summary["by_course"]
    assert len(summary["by_course"]["CS 122B"]) >= 2
