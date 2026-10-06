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
    # win-back cases (docs/CASES.md)
    case_expire_days: int = 14  # an open case nobody processed closes as expired after this many days
    case_booking_grace_days: int = 3  # a booking an administrator reported must show up in the CRM within this many days
    # win-back offer (docs/OFFERS.md): the discount a client gets for booking during the call, and who is worth one
    book_now_pct: int = 15
    early_overdue_days: int = 30  # up to this many days past a regular's own overdue line the offer is a call, not a discount
    book_now_lapsed_max_days: int = 365  # regulars silent longer than this are not contacted (a year; beyond it 4% or fewer return on their own, and the list is too long to call)
    book_now_first_timer_days: tuple[int, int] = (46, 120)  # one-time clients are worth the offer only while the first visit is this recent
    # notifications and jobs
    telegram_bot_token: str | None = None
    telegram_owner_chat_id: int | None = None  # a private chat or a group with only the owner in it: the weekly message carries client names
    owner_lang: str = "uk"
    timezone: str = "Europe/Kyiv"  # the shop's local time: jobs run on its clock
    # the weekly job's fresh-data step: a headless Claude with the Altegio connector (the only way in until the REST token works)
    weekly_fetch: bool = True
    fetch_claude_bin: str | None = None  # default: `claude` on the PATH, then ~/.local/bin/claude
    fetch_claude_config_dir: Path | None = None  # the Claude profile that has the Altegio connector signed in
    fetch_timeout: int = 1200
    fetch_max_turns: int = 60
    data_stale_days: int = 3  # an Alert when the newest completed visit is older than this
    host: str = "127.0.0.1"
    port: int = 8765

    @property
    def db_url(self) -> str:
        return f"sqlite:///{self.data_dir / 'insights.sqlite'}"


settings = Settings()
