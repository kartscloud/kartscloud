from __future__ import annotations

import os
from pathlib import Path
from typing import List

from dotenv import load_dotenv
from pydantic import BaseModel, Field


JARVIS_HOME = Path(os.path.expanduser("~/.jarvis"))


def _csv(value: str | None) -> List[str]:
    if not value:
        return []
    return [s.strip() for s in value.split(",") if s.strip()]


class Config(BaseModel):
    anthropic_api_key: str = ""
    canvas_token: str = ""
    canvas_base_url: str = "https://canvas.eee.uci.edu/api/v1"

    user_name: str = "Carter"
    user_timezone: str = "America/Los_Angeles"

    daily_calorie_target: int = 2400
    daily_protein_target: int = 200
    daily_carb_target: int = 240
    daily_fat_target: int = 70
    goal: str = "cut"

    watchlist_stocks: List[str] = Field(default_factory=list)
    watchlist_crypto: List[str] = Field(default_factory=list)
    job_watchlist_companies: List[str] = Field(default_factory=list)

    google_credentials_path: str = str(JARVIS_HOME / "google_credentials.json")

    db_path: Path = JARVIS_HOME / "jarvis.db"
    briefs_dir: Path = JARVIS_HOME / "briefs"


def load_config() -> Config:
    env_path = JARVIS_HOME / ".env"
    if env_path.exists():
        load_dotenv(env_path, override=False)
    load_dotenv(override=False)

    return Config(
        anthropic_api_key=os.getenv("ANTHROPIC_API_KEY", ""),
        canvas_token=os.getenv("CANVAS_TOKEN", ""),
        canvas_base_url=os.getenv("CANVAS_BASE_URL", "https://canvas.eee.uci.edu/api/v1"),
        user_name=os.getenv("USER_NAME", "Carter"),
        user_timezone=os.getenv("USER_TIMEZONE", "America/Los_Angeles"),
        daily_calorie_target=int(os.getenv("DAILY_CALORIE_TARGET", "2400")),
        daily_protein_target=int(os.getenv("DAILY_PROTEIN_TARGET", "200")),
        daily_carb_target=int(os.getenv("DAILY_CARB_TARGET", "240")),
        daily_fat_target=int(os.getenv("DAILY_FAT_TARGET", "70")),
        goal=os.getenv("GOAL", "cut"),
        watchlist_stocks=_csv(os.getenv("WATCHLIST_STOCKS")),
        watchlist_crypto=_csv(os.getenv("WATCHLIST_CRYPTO")),
        job_watchlist_companies=_csv(os.getenv("JOB_WATCHLIST_COMPANIES")),
        google_credentials_path=os.path.expanduser(
            os.getenv("GOOGLE_CREDENTIALS_PATH", str(JARVIS_HOME / "google_credentials.json"))
        ),
    )


def ensure_dirs(config: Config) -> None:
    JARVIS_HOME.mkdir(parents=True, exist_ok=True)
    config.briefs_dir.mkdir(parents=True, exist_ok=True)
