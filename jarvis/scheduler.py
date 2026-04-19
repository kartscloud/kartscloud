from __future__ import annotations

from apscheduler.schedulers.background import BackgroundScheduler


_scheduler: BackgroundScheduler | None = None


def start() -> str:
    global _scheduler
    if _scheduler and _scheduler.running:
        return "already running"
    _scheduler = BackgroundScheduler()
    _scheduler.start()
    return "started (no jobs registered in v0.1)"


def stop() -> str:
    global _scheduler
    if not _scheduler or not _scheduler.running:
        return "not running"
    _scheduler.shutdown(wait=False)
    _scheduler = None
    return "stopped"
