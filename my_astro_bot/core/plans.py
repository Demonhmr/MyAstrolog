"""
plans.py — тарифы Звездицы (утверждены 21.11.2026).

Продаются личные месяцы (~27,3 дня): разово, без автопродления.
  one   — текущий личный месяц                    150 ₽
  p3    — 3 личных месяца подряд                  390 ₽
  p6    — 6 личных месяцев                        590 ₽
  p13   — год: 13 личных месяцев                  990 ₽
  plus  — годовая подписка: 13 месяцев, и каждый
          можно открыть заранее, не дожидаясь начала  1 590 ₽
Прошлый личный месяц — бесплатно. Оплаченные месяцы остаются доступны навсегда.

Цены в звёздах Telegram (бот) пересчитаны так, чтобы покупатель платил примерно
столько же рублей: звёзды в Telegram для покупателя стоят около 1,5 ₽
(STARS_RUB). Любую цену можно переопределить в .env: PRICE_<КОД>_STARS / PRICE_<КОД>_RUB.
"""

import os
from dataclasses import dataclass
from typing import Dict, Optional

STARS_RUB = 1.5


@dataclass(frozen=True)
class Plan:
    code: str
    title: str          # для экрана тарифов
    short: str          # для кнопки
    receipt: str        # наименование в чеке самозанятого (до 128 знаков, без кавычек)
    months: int
    preview: bool       # можно открыть оплаченные месяцы заранее
    rub: int
    stars: int


_BASE = [
    ("one", "Текущий личный месяц", "1 месяц", "Прогноз Звездицы на 1 личный месяц", 1, False, 150),
    ("p3", "3 личных месяца", "3 месяца", "Прогноз Звездицы на 3 личных месяца", 3, False, 390),
    ("p6", "6 личных месяцев", "6 месяцев", "Прогноз Звездицы на 6 личных месяцев", 6, False, 590),
    ("p13", "Год — 13 личных месяцев", "Год", "Прогноз Звездицы на 13 личных месяцев (год)", 13, False, 990),
    ("plus", "Годовая подписка: 13 месяцев наперёд", "Год наперёд",
     "Годовая подписка Звездицы: 13 личных месяцев с прогнозами наперёд", 13, True, 1590),
]


def _stars(rub: int) -> int:
    """Рубли → звёзды по курсу покупателя, кратно 5."""
    return max(5, int(round(rub / STARS_RUB / 5.0)) * 5)


def plans() -> Dict[str, Plan]:
    out = {}
    for code, title, short, receipt, months, preview, rub in _BASE:
        rub = int(os.getenv(f"PRICE_{code.upper()}_RUB", rub))
        stars = int(os.getenv(f"PRICE_{code.upper()}_STARS", _stars(rub)))
        out[code] = Plan(code, title, short, receipt, months, preview, rub, stars)
    return out


def get(code: str) -> Optional[Plan]:
    return plans().get(code)


def describe(p: Plan) -> str:
    """Одна строка о том, что даёт тариф."""
    if p.code == "one":
        return "Прогноз на текущий личный месяц. Если он уже оплачен — на ближайший неоплаченный."
    if p.preview:
        return ("13 личных месяцев подряд, начиная с текущего. Каждый можно открыть заранее — "
                "смотреть наперёд до года.")
    return (f"{p.months} личных месяцев подряд, начиная с текущего. "
            "Каждый откроется в день, когда начнётся.")


def as_json(p: Plan) -> dict:
    return {"code": p.code, "title": p.title, "short": p.short, "months": p.months,
            "preview": p.preview, "rub": p.rub, "stars": p.stars, "text": describe(p)}
