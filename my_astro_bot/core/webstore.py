"""
webstore.py — хранилище сайта и общих для сайта и бота вещей (та же база SQLite).

  accounts, login_codes, login_fails, sessions — вход по коду из письма
  web_profiles  — данные рождения владельца аккаунта (один человек на аккаунт)
  grants        — оплаченные личные месяцы (owner: «w:<аккаунт>» или «t:<Telegram ID>»)
  orders        — счета Robokassa (номер счёта = InvId)
  diary         — дневник «дата — запись» (owner как у grants)
  report_cache  — снимок открытого платного прогноза: месяц не меняется задним числом

Время везде — UTC, строки ISO «ГГГГ-ММ-ДДTЧЧ:ММ:СС». Деньги — в копейках.
"""

import hashlib
import json
import secrets
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta
from typing import List, Optional

from core.astrology import utcnow_naive
from core.periods import Grant

SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    email            TEXT    NOT NULL UNIQUE,
    consent_version  TEXT,
    consent_at       TEXT,
    created_at       TEXT    NOT NULL,
    last_login_at    TEXT
);

CREATE TABLE IF NOT EXISTS login_codes (           -- сам код не храним, только SHA-256(email:код)
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    email       TEXT NOT NULL,
    code_hash   TEXT NOT NULL,
    ip          TEXT,
    created_at  TEXT NOT NULL,
    expires_at  TEXT NOT NULL,
    used_at     TEXT
);
CREATE INDEX IF NOT EXISTS ix_codes_email ON login_codes (email, created_at);
CREATE INDEX IF NOT EXISTS ix_codes_ip ON login_codes (ip, created_at);

CREATE TABLE IF NOT EXISTS login_fails (
    email       TEXT NOT NULL,
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_fails ON login_fails (email, created_at);

CREATE TABLE IF NOT EXISTS sessions (              -- токен не храним, только SHA-256
    token_hash    TEXT PRIMARY KEY,
    account_id    INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    created_at    TEXT NOT NULL,
    expires_at    TEXT NOT NULL,
    last_seen_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS web_profiles (
    account_id     INTEGER PRIMARY KEY REFERENCES accounts(id) ON DELETE CASCADE,
    birth_date     TEXT NOT NULL,                  -- ГГГГ-ММ-ДД
    birth_time     TEXT,                           -- ЧЧ:ММ или NULL (не знает)
    birth_place    TEXT NOT NULL,                  -- JSON {name, lat, lon, tz}
    current_place  TEXT,                           -- JSON или NULL (там же)
    updated_at     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS grants (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    owner        TEXT NOT NULL,
    cycle_start  TEXT NOT NULL,
    cycle_end    TEXT NOT NULL,
    plan         TEXT NOT NULL,
    order_ref    TEXT NOT NULL,                    -- rk:<InvId> | tg:<charge_id> | manual:<…>
    preview      INTEGER NOT NULL DEFAULT 0,
    created_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_grants_owner ON grants (owner, cycle_start);

CREATE TABLE IF NOT EXISTS orders (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,   -- InvId в Robokassa
    account_id    INTEGER,                             -- NULL после удаления аккаунта (платёж остаётся для учёта)
    plan          TEXT    NOT NULL,
    amount_kop    INTEGER NOT NULL,
    status        TEXT    NOT NULL DEFAULT 'new',      -- new | paid
    is_test       INTEGER NOT NULL DEFAULT 0,
    granted       INTEGER NOT NULL DEFAULT 0,          -- сколько месяцев выдано
    result_count  INTEGER NOT NULL DEFAULT 0,          -- сколько раз пришло уведомление
    fee_kop       INTEGER,
    note          TEXT,
    created_at    TEXT NOT NULL,
    paid_at       TEXT
);

CREATE TABLE IF NOT EXISTS diary (
    owner       TEXT NOT NULL,
    id          TEXT NOT NULL,
    day         TEXT NOT NULL,                     -- ГГГГ-ММ-ДД
    text        TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    PRIMARY KEY (owner, id)
);
CREATE INDEX IF NOT EXISTS ix_diary_day ON diary (owner, day);

CREATE TABLE IF NOT EXISTS report_cache (
    owner        TEXT NOT NULL,
    cycle_start  TEXT NOT NULL,
    place_key    TEXT NOT NULL,
    report       TEXT NOT NULL,
    created_at   TEXT NOT NULL,
    PRIMARY KEY (owner, cycle_start)
);
"""

FIRST_INV_ID = 1001
SESSION_DAYS = 180
CODE_TTL = timedelta(minutes=10)
DIARY_MAX_TEXT = 2000
DIARY_MAX_ENTRIES = 5000


def migrate(conn: sqlite3.Connection) -> None:
    # Номера счетов Robokassa начинаются с FIRST_INV_ID
    if not conn.execute("SELECT 1 FROM sqlite_sequence WHERE name = 'orders'").fetchone():
        conn.execute("INSERT INTO sqlite_sequence (name, seq) VALUES ('orders', ?)", (FIRST_INV_ID - 1,))


def _conn():
    from core.storage import _connect
    return _connect()


def _iso(dt: datetime) -> str:
    return dt.replace(microsecond=0).isoformat(timespec="seconds")


def _now() -> str:
    return _iso(utcnow_naive())


def _sha(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def web_owner(account_id: int) -> str:
    return f"w:{account_id}"


def tg_owner(user_id: int) -> str:
    return f"t:{user_id}"


# ── Вход по коду ─────────────────────────────────────────────────────────────

def code_counts(email: str, ip: str, now: Optional[datetime] = None) -> dict:
    now = now or utcnow_naive()
    with closing(_conn()) as c:
        last = c.execute("SELECT MAX(created_at) FROM login_codes WHERE email = ?", (email,)).fetchone()[0]
        hour = _iso(now - timedelta(hours=1))
        by_email = c.execute("SELECT COUNT(*) FROM login_codes WHERE email = ? AND created_at > ?",
                             (email, hour)).fetchone()[0]
        by_ip = c.execute("SELECT COUNT(*) FROM login_codes WHERE ip = ? AND created_at > ?",
                          (ip, hour)).fetchone()[0]
    return {"last": datetime.fromisoformat(last) if last else None, "email_hour": by_email, "ip_hour": by_ip}


def new_code(email: str, ip: str, code: Optional[str] = None) -> str:
    code = code or f"{secrets.randbelow(1000000):06d}"
    now = utcnow_naive()
    with closing(_conn()) as c:
        c.execute("INSERT INTO login_codes (email, code_hash, ip, created_at, expires_at) VALUES (?, ?, ?, ?, ?)",
                  (email, _sha(f"{email}:{code}"), ip, _iso(now), _iso(now + CODE_TTL)))
        c.commit()
    return code


def drop_code(email: str) -> None:
    """Письмо не ушло — последний код не считаем (не тратит лимит «раз в минуту»)."""
    with closing(_conn()) as c:
        c.execute("DELETE FROM login_codes WHERE id = (SELECT MAX(id) FROM login_codes WHERE email = ?)", (email,))
        c.commit()


def recent_fails(email: str, now: Optional[datetime] = None) -> int:
    now = now or utcnow_naive()
    with closing(_conn()) as c:
        return c.execute("SELECT COUNT(*) FROM login_fails WHERE email = ? AND created_at > ?",
                         (email, _iso(now - timedelta(minutes=15)))).fetchone()[0]


def check_code(email: str, code: str) -> str:
    """'ok' — код верный (все коды адреса гасятся), 'bad' — неверный, 'expired' — нет живых кодов."""
    now = _now()
    with closing(_conn()) as c:
        live = c.execute("SELECT id, code_hash FROM login_codes WHERE email = ? AND used_at IS NULL AND expires_at > ?",
                         (email, now)).fetchall()
        if not live:
            return "expired"
        h = _sha(f"{email}:{code}")
        if not any(secrets.compare_digest(r["code_hash"], h) for r in live):
            c.execute("INSERT INTO login_fails (email, created_at) VALUES (?, ?)", (email, now))
            c.commit()
            return "bad"
        c.execute("UPDATE login_codes SET used_at = ? WHERE email = ? AND used_at IS NULL", (now, email))
        c.execute("DELETE FROM login_fails WHERE email = ?", (email,))
        c.commit()
    return "ok"


def get_account_by_email(email: str) -> Optional[dict]:
    with closing(_conn()) as c:
        r = c.execute("SELECT * FROM accounts WHERE email = ?", (email,)).fetchone()
    return dict(r) if r else None


def get_account(account_id: int) -> Optional[dict]:
    with closing(_conn()) as c:
        r = c.execute("SELECT * FROM accounts WHERE id = ?", (account_id,)).fetchone()
    return dict(r) if r else None


def create_account(email: str, consent_version: str) -> int:
    now = _now()
    with closing(_conn()) as c:
        cur = c.execute("INSERT INTO accounts (email, consent_version, consent_at, created_at) VALUES (?, ?, ?, ?)",
                        (email, consent_version, now, now))
        c.commit()
        return cur.lastrowid


def set_consent(account_id: int, version: str) -> None:
    with closing(_conn()) as c:
        c.execute("UPDATE accounts SET consent_version = ?, consent_at = ? WHERE id = ?", (version, _now(), account_id))
        c.commit()


def new_session(account_id: int) -> str:
    token = secrets.token_urlsafe(32)
    now = utcnow_naive()
    with closing(_conn()) as c:
        c.execute("INSERT INTO sessions (token_hash, account_id, created_at, expires_at, last_seen_at) "
                  "VALUES (?, ?, ?, ?, ?)",
                  (_sha(token), account_id, _iso(now), _iso(now + timedelta(days=SESSION_DAYS)), _iso(now)))
        c.execute("UPDATE accounts SET last_login_at = ? WHERE id = ?", (_iso(now), account_id))
        c.commit()
    return token


def session_account(token: str) -> Optional[int]:
    """Аккаунт по токену; срок сессии продлевается при использовании (не чаще раза в сутки)."""
    if not token or len(token) > 100:
        return None
    now = utcnow_naive()
    with closing(_conn()) as c:
        r = c.execute("SELECT account_id, last_seen_at FROM sessions WHERE token_hash = ? AND expires_at > ?",
                      (_sha(token), _iso(now))).fetchone()
        if not r:
            return None
        if datetime.fromisoformat(r["last_seen_at"]) < now - timedelta(days=1):
            c.execute("UPDATE sessions SET last_seen_at = ?, expires_at = ? WHERE token_hash = ?",
                      (_iso(now), _iso(now + timedelta(days=SESSION_DAYS)), _sha(token)))
            c.commit()
        return r["account_id"]


def end_session(token: str) -> None:
    with closing(_conn()) as c:
        c.execute("DELETE FROM sessions WHERE token_hash = ?", (_sha(token),))
        c.commit()


def erase_account(account_id: int) -> None:
    """Удаление аккаунта по просьбе: профиль, дневник, месяцы, сессии. Счета обезличиваются."""
    owner = web_owner(account_id)
    with closing(_conn()) as c:
        c.execute("DELETE FROM diary WHERE owner = ?", (owner,))
        c.execute("DELETE FROM grants WHERE owner = ?", (owner,))
        c.execute("DELETE FROM report_cache WHERE owner = ?", (owner,))
        c.execute("UPDATE orders SET account_id = NULL WHERE account_id = ?", (account_id,))
        c.execute("DELETE FROM sessions WHERE account_id = ?", (account_id,))
        c.execute("DELETE FROM web_profiles WHERE account_id = ?", (account_id,))
        acc = c.execute("SELECT email FROM accounts WHERE id = ?", (account_id,)).fetchone()
        if acc:
            c.execute("DELETE FROM login_codes WHERE email = ?", (acc["email"],))
            c.execute("DELETE FROM login_fails WHERE email = ?", (acc["email"],))
        c.execute("DELETE FROM accounts WHERE id = ?", (account_id,))
        c.commit()


def cleanup(now: Optional[datetime] = None) -> None:
    """Старые коды, ошибки и просроченные сессии (по сроку из политики — 30 дней)."""
    now = now or utcnow_naive()
    old = _iso(now - timedelta(days=30))
    with closing(_conn()) as c:
        c.execute("DELETE FROM login_codes WHERE created_at < ?", (old,))
        c.execute("DELETE FROM login_fails WHERE created_at < ?", (old,))
        c.execute("DELETE FROM sessions WHERE expires_at < ?", (_iso(now),))
        c.commit()


# ── Профиль сайта ────────────────────────────────────────────────────────────

def get_web_profile(account_id: int) -> Optional[dict]:
    with closing(_conn()) as c:
        r = c.execute("SELECT * FROM web_profiles WHERE account_id = ?", (account_id,)).fetchone()
    if not r:
        return None
    return {
        "birth_date": r["birth_date"], "birth_time": r["birth_time"],
        "birth_place": json.loads(r["birth_place"]),
        "current_place": json.loads(r["current_place"]) if r["current_place"] else None,
    }


def save_web_profile(account_id: int, p: dict) -> None:
    with closing(_conn()) as c:
        c.execute(
            "INSERT INTO web_profiles (account_id, birth_date, birth_time, birth_place, current_place, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(account_id) DO UPDATE SET birth_date = excluded.birth_date, "
            "birth_time = excluded.birth_time, birth_place = excluded.birth_place, "
            "current_place = excluded.current_place, updated_at = excluded.updated_at",
            (account_id, p["birth_date"], p.get("birth_time"), json.dumps(p["birth_place"], ensure_ascii=False),
             json.dumps(p["current_place"], ensure_ascii=False) if p.get("current_place") else None, _now()),
        )
        c.execute("DELETE FROM report_cache WHERE owner = ?", (web_owner(account_id),))
        c.commit()


# ── Оплаченные месяцы ────────────────────────────────────────────────────────

def grants_of(owner: str) -> List[Grant]:
    with closing(_conn()) as c:
        rows = c.execute("SELECT cycle_start, preview FROM grants WHERE owner = ? ORDER BY cycle_start",
                         (owner,)).fetchall()
    return [Grant(datetime.fromisoformat(r["cycle_start"]), bool(r["preview"])) for r in rows]


def has_grants(owner: str) -> bool:
    with closing(_conn()) as c:
        return c.execute("SELECT 1 FROM grants WHERE owner = ? LIMIT 1", (owner,)).fetchone() is not None


def add_grants(c: sqlite3.Connection, owner: str, cycles, plan: str, order_ref: str, preview: bool) -> int:
    now = _now()
    for cy in cycles:
        c.execute("INSERT INTO grants (owner, cycle_start, cycle_end, plan, order_ref, preview, created_at) "
                  "VALUES (?, ?, ?, ?, ?, ?, ?)",
                  (owner, _iso(cy.start), _iso(cy.end), plan, order_ref, int(preview), now))
    return len(cycles)


def grant_cycles(owner: str, cycles, plan: str, order_ref: str, preview: bool) -> int:
    with closing(_conn()) as c:
        n = add_grants(c, owner, cycles, plan, order_ref, preview)
        c.commit()
    return n


# ── Счета Robokassa ──────────────────────────────────────────────────────────

def create_order(account_id: int, plan: str, amount_kop: int, is_test: bool) -> int:
    with closing(_conn()) as c:
        cur = c.execute("INSERT INTO orders (account_id, plan, amount_kop, is_test, created_at) VALUES (?, ?, ?, ?, ?)",
                        (account_id, plan, amount_kop, int(is_test), _now()))
        c.commit()
        return cur.lastrowid


def get_order(inv_id: int) -> Optional[dict]:
    with closing(_conn()) as c:
        r = c.execute("SELECT * FROM orders WHERE id = ?", (inv_id,)).fetchone()
    return dict(r) if r else None


def pay_order(inv_id: int, fee_kop: Optional[int], grant_fn) -> dict:
    """
    Отмечает счёт оплаченным и выдаёт месяцы — одной транзакцией, ровно один раз.
    grant_fn(conn, order) → (сколько месяцев выдано, примечание или None); вызывается только при первой оплате.
    """
    with closing(_conn()) as c:
        c.execute("BEGIN IMMEDIATE")
        o = dict(c.execute("SELECT * FROM orders WHERE id = ?", (inv_id,)).fetchone())
        c.execute("UPDATE orders SET result_count = result_count + 1, fee_kop = COALESCE(?, fee_kop) WHERE id = ?",
                  (fee_kop, inv_id))
        first = o["status"] != "paid"
        if first:
            granted, note = grant_fn(c, o)
            c.execute("UPDATE orders SET status = 'paid', paid_at = ?, granted = ?, note = ? WHERE id = ?",
                      (_now(), granted, note, inv_id))
        c.commit()
    o["first"] = first
    return o


# ── Дневник ──────────────────────────────────────────────────────────────────

def diary_list(owner: str) -> list:
    with closing(_conn()) as c:
        rows = c.execute("SELECT id, day, text, created_at, updated_at FROM diary WHERE owner = ? "
                         "ORDER BY day DESC, created_at DESC", (owner,)).fetchall()
    return [dict(r) for r in rows]


def diary_count(owner: str) -> int:
    with closing(_conn()) as c:
        return c.execute("SELECT COUNT(*) FROM diary WHERE owner = ?", (owner,)).fetchone()[0]


def diary_put(owner: str, entry_id: str, day: str, text: str, created_at: Optional[str] = None) -> dict:
    now = _now()
    with closing(_conn()) as c:
        c.execute("INSERT INTO diary (owner, id, day, text, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?) "
                  "ON CONFLICT(owner, id) DO UPDATE SET day = excluded.day, text = excluded.text, "
                  "updated_at = excluded.updated_at", (owner, entry_id, day, text, created_at or now, now))
        c.commit()
        r = c.execute("SELECT id, day, text, created_at, updated_at FROM diary WHERE owner = ? AND id = ?",
                      (owner, entry_id)).fetchone()
    return dict(r)


def diary_exists(owner: str, entry_id: str) -> bool:
    with closing(_conn()) as c:
        return c.execute("SELECT 1 FROM diary WHERE owner = ? AND id = ?", (owner, entry_id)).fetchone() is not None


def diary_delete(owner: str, entry_id: str) -> bool:
    with closing(_conn()) as c:
        n = c.execute("DELETE FROM diary WHERE owner = ? AND id = ?", (owner, entry_id)).rowcount
        c.commit()
    return n > 0


# ── Снимки открытых платных прогнозов ────────────────────────────────────────

def cached_report(owner: str, cycle_start: datetime, place_key: str) -> Optional[dict]:
    with closing(_conn()) as c:
        r = c.execute("SELECT cycle_start, place_key, report FROM report_cache WHERE owner = ?", (owner,)).fetchall()
    for row in r:
        if abs(datetime.fromisoformat(row["cycle_start"]) - cycle_start) <= timedelta(hours=6) \
                and row["place_key"] == place_key:
            return json.loads(row["report"])
    return None


def save_report(owner: str, cycle_start: datetime, place_key: str, report: dict) -> None:
    with closing(_conn()) as c:
        # старый снимок того же месяца (другой город) заменяется
        rows = c.execute("SELECT cycle_start FROM report_cache WHERE owner = ?", (owner,)).fetchall()
        for row in rows:
            if abs(datetime.fromisoformat(row["cycle_start"]) - cycle_start) <= timedelta(hours=6):
                c.execute("DELETE FROM report_cache WHERE owner = ? AND cycle_start = ?", (owner, row["cycle_start"]))
        c.execute("INSERT INTO report_cache (owner, cycle_start, place_key, report, created_at) VALUES (?, ?, ?, ?, ?)",
                  (owner, _iso(cycle_start), place_key, json.dumps(report, ensure_ascii=False), _now()))
        c.commit()
