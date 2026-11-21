"""
billing.py — оплата в боте звёздами Telegram: счёт и выдача личных месяцев.

Тарифы и цены — core/plans.py (те же, что на сайте, цены в звёздах).
Оплата разовая, без автопродления. Оплаченные месяцы записываются в grants
(owner «t:<Telegram ID>») по правилам core/periods.py.
"""

from typing import Optional

from core import plans


def make_payload(plan: str, user_id: int) -> str:
    return f"zv:{plan}:{user_id}"


def parse_payload(payload: str) -> Optional[tuple]:
    """'zv:p3:42' → ('p3', 42); всё остальное → None."""
    parts = (payload or "").split(":")
    if len(parts) != 3 or parts[0] != "zv" or plans.get(parts[1]) is None:
        return None
    try:
        return parts[1], int(parts[2])
    except ValueError:
        return None
