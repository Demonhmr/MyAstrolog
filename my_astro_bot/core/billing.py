"""
billing.py — тарифы Звездицы+ и продление подписки (оплата в Telegram Stars).

Месяц — подписка Stars с автопродлением раз в 30 дней (так устроены подписки
в Telegram). Год — разовая оплата на 365 дней. Цены задаются в .env.
"""

import os
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

SUBSCRIPTION_PERIOD = 30 * 24 * 3600  # Telegram принимает только 30 дней


@dataclass(frozen=True)
class Plan:
    code: str
    title: str
    stars: int
    days: int
    recurring: bool


def plans() -> dict:
    month = int(os.getenv("PRICE_MONTH_STARS", "200"))
    year = int(os.getenv("PRICE_YEAR_STARS", "1700"))
    return {
        "month": Plan("month", "Звездица+ на месяц", month, 30, True),
        "year": Plan("year", "Звездица+ на год", year, 365, False),
    }


def make_payload(plan: str, user_id: int) -> str:
    return f"zv:{plan}:{user_id}"


def parse_payload(payload: str) -> Optional[tuple]:
    """'zv:month:42' → ('month', 42); всё остальное → None."""
    parts = (payload or "").split(":")
    if len(parts) != 3 or parts[0] != "zv" or parts[1] not in ("month", "year"):
        return None
    try:
        return parts[1], int(parts[2])
    except ValueError:
        return None


def new_premium_until(plan: Plan, now: datetime, current_until: Optional[datetime]) -> datetime:
    """
    До какого момента действует подписка после оплаты: от текущего окончания,
    если оно ещё впереди, иначе от «сейчас». Оплаченные дни не теряются,
    а автосписание Stars (в момент окончания) продлевает ровно на 30 дней.
    """
    start = current_until if current_until and current_until > now else now
    return start + timedelta(days=plan.days)
