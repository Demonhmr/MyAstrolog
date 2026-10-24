"""
storage.py — SQLite: профили пользователей и архив прогнозов.

Функции синхронные и короткие; из async-кода их вызывают через
asyncio.to_thread, чтобы не блокировать бота.
"""

import os
import sqlite3
from contextlib import closing
from dataclasses import dataclass, asdict, fields
from datetime import datetime
from pathlib import Path
from typing import Optional, List

from core.astrology import utcnow_naive

DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / "storage" / "zvezditsa.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    user_id           INTEGER PRIMARY KEY,
    chat_id           INTEGER NOT NULL,
    name              TEXT    NOT NULL,
    birth_date        TEXT    NOT NULL,          -- ДД.ММ.ГГГГ
    birth_time        TEXT    NOT NULL,          -- ЧЧ:ММ (12:00, если неизвестно)
    time_known        INTEGER NOT NULL DEFAULT 1,
    birth_city        TEXT    NOT NULL,
    birth_lat         REAL    NOT NULL,
    birth_lon         REAL    NOT NULL,
    birth_utc_offset  REAL    NOT NULL,
    birth_tz          TEXT    NOT NULL,
    cur_city          TEXT    NOT NULL,
    cur_lat           REAL    NOT NULL,
    cur_lon           REAL    NOT NULL,
    cur_tz            TEXT    NOT NULL,
    next_cycle_utc    TEXT,                      -- начало следующего личного месяца (UTC, ISO)
    reminders_on      INTEGER NOT NULL DEFAULT 1,
    premium_until     TEXT,                      -- UTC ISO; NULL — бесплатный доступ
    created_at        TEXT    NOT NULL,
    updated_at        TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS forecasts (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id          INTEGER NOT NULL,
    cycle_start_utc  TEXT    NOT NULL,
    cycle_end_utc    TEXT    NOT NULL,
    story_text       TEXT,                       -- живой текст «как хочу / как будет»
    created_at       TEXT    NOT NULL,
    UNIQUE (user_id, cycle_start_utc)
);

CREATE INDEX IF NOT EXISTS idx_users_due ON users (reminders_on, next_cycle_utc);
"""


@dataclass
class Profile:
    user_id: int
    chat_id: int
    name: str
    birth_date: str
    birth_time: str
    time_known: bool
    birth_city: str
    birth_lat: float
    birth_lon: float
    birth_utc_offset: float
    birth_tz: str
    cur_city: str
    cur_lat: float
    cur_lon: float
    cur_tz: str
    next_cycle_utc: Optional[str] = None
    reminders_on: bool = True
    premium_until: Optional[str] = None

    def is_premium(self, now: Optional[datetime] = None) -> bool:
        if not self.premium_until:
            return False
        now = now or utcnow_naive()
        return datetime.fromisoformat(self.premium_until) > now


_PROFILE_FIELDS = [f.name for f in fields(Profile)]


def db_path() -> Path:
    return Path(os.getenv("DB_PATH") or DEFAULT_DB_PATH)


def _connect() -> sqlite3.Connection:
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with closing(_connect()) as conn:
        conn.executescript(SCHEMA)
        conn.commit()


def _now_iso() -> str:
    return utcnow_naive().isoformat(timespec="seconds")


def _row_to_profile(row: sqlite3.Row) -> Profile:
    data = {k: row[k] for k in _PROFILE_FIELDS}
    data["time_known"] = bool(data["time_known"])
    data["reminders_on"] = bool(data["reminders_on"])
    return Profile(**data)


def save_profile(p: Profile) -> None:
    """Создаёт или обновляет профиль. Статус подписки не трогает."""
    data = asdict(p)
    data["time_known"] = int(p.time_known)
    data["reminders_on"] = int(p.reminders_on)
    data.pop("premium_until")
    now = _now_iso()
    cols = list(data.keys())
    updates = ", ".join(f"{c}=excluded.{c}" for c in cols if c != "user_id")
    with closing(_connect()) as conn:
        conn.execute(
            f"INSERT INTO users ({', '.join(cols)}, created_at, updated_at) "
            f"VALUES ({', '.join('?' for _ in cols)}, ?, ?) "
            f"ON CONFLICT(user_id) DO UPDATE SET {updates}, updated_at=excluded.updated_at",
            [data[c] for c in cols] + [now, now],
        )
        conn.commit()


def get_profile(user_id: int) -> Optional[Profile]:
    with closing(_connect()) as conn:
        row = conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
    return _row_to_profile(row) if row else None


def delete_user(user_id: int) -> None:
    """Удаляет профиль и все прогнозы пользователя (по его запросу)."""
    with closing(_connect()) as conn:
        conn.execute("DELETE FROM forecasts WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM users WHERE user_id = ?", (user_id,))
        conn.commit()


def set_next_cycle(user_id: int, next_cycle_utc: datetime) -> None:
    with closing(_connect()) as conn:
        conn.execute(
            "UPDATE users SET next_cycle_utc = ?, updated_at = ? WHERE user_id = ?",
            (next_cycle_utc.isoformat(timespec="seconds"), _now_iso(), user_id),
        )
        conn.commit()


def set_reminders(user_id: int, on: bool) -> None:
    with closing(_connect()) as conn:
        conn.execute(
            "UPDATE users SET reminders_on = ?, updated_at = ? WHERE user_id = ?",
            (int(on), _now_iso(), user_id),
        )
        conn.commit()


def set_premium_until(user_id: int, until_utc: Optional[datetime]) -> None:
    with closing(_connect()) as conn:
        conn.execute(
            "UPDATE users SET premium_until = ?, updated_at = ? WHERE user_id = ?",
            (until_utc.isoformat(timespec="seconds") if until_utc else None, _now_iso(), user_id),
        )
        conn.commit()


def due_profiles(now: Optional[datetime] = None, limit: int = 50) -> List[Profile]:
    """Профили, у которых уже начался новый личный месяц и включены напоминания."""
    now = now or utcnow_naive()
    with closing(_connect()) as conn:
        rows = conn.execute(
            "SELECT * FROM users WHERE reminders_on = 1 AND next_cycle_utc IS NOT NULL "
            "AND next_cycle_utc <= ? ORDER BY next_cycle_utc LIMIT ?",
            (now.isoformat(timespec="seconds"), limit),
        ).fetchall()
    return [_row_to_profile(r) for r in rows]


def get_story(user_id: int, cycle_start_utc: datetime) -> Optional[str]:
    with closing(_connect()) as conn:
        row = conn.execute(
            "SELECT story_text FROM forecasts WHERE user_id = ? AND cycle_start_utc = ?",
            (user_id, cycle_start_utc.isoformat(timespec="minutes")),
        ).fetchone()
    return row["story_text"] if row else None


def save_story(user_id: int, cycle_start_utc: datetime, cycle_end_utc: datetime, text: str) -> None:
    with closing(_connect()) as conn:
        conn.execute(
            "INSERT INTO forecasts (user_id, cycle_start_utc, cycle_end_utc, story_text, created_at) "
            "VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(user_id, cycle_start_utc) DO UPDATE SET story_text = excluded.story_text",
            (
                user_id,
                cycle_start_utc.isoformat(timespec="minutes"),
                cycle_end_utc.isoformat(timespec="minutes"),
                text,
                _now_iso(),
            ),
        )
        conn.commit()
