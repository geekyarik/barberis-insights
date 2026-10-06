"""Service settings. Values come from environment variables prefixed INSIGHTS_ or a .env file."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Barber:
    key: str
    altegio_id: int
    name: str
    tier: str


def default_barbers() -> list[Barber]:
    """Initial roster for `insights import-legacy`, from var/barbers.json (private, not in git):
    [{"key", "altegio_id", "name", "tier"}]. After that the database `barbers` table is the source of truth."""
    import json
    path = Path(Settings().data_dir) / "barbers.json"
    return [Barber(**b) for b in json.loads(path.read_text())] if path.exists() else []


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="INSIGHTS_", env_file=ROOT / ".env", extra="ignore")

    location_id: int = 209563
    data_dir: Path = ROOT / "var"
    history_start: str = "2022-01-03"  # client profiles, segments, win-back: all imported history
    metrics_history_start: str = "2025-01-01"  # Goal metrics keep this until their definitions are versioned
    addon_keywords: tuple[str, ...] = ("Масаж", "Камуфляж", "Воскове", "брів")
    baseline_date: str = "2026-09-27"
    # risk rules
    overdue_min_days: int = 45
    overdue_gap_factor: float = 1.5
    lapsed_after_days: int = 180
    case_cooldown_days: int = 60
    winback_window_days: int = 60
    # google sheet for the admin call list
    sheet_id: str | None = None
    sheet_lang: str = "uk"  # language of the call sheet's tabs, headers and dropdowns ("uk" or "en"); the sync reads both
    # notifications and jobs
    telegram_bot_token: str | None = None
    telegram_owner_chat_id: int | None = None  # a private chat or a group with only the owner in it: the weekly message carries client names
    owner_lang: str = "uk"
    timezone: str = "Europe/Kyiv"  # the shop's local time: jobs run on its clock
    data_stale_days: int = 3  # an Alert when the newest completed visit is older than this
    host: str = "127.0.0.1"
    port: int = 8765

    @property
    def db_url(self) -> str:
        return f"sqlite:///{self.data_dir / 'insights.sqlite'}"


settings = Settings()
