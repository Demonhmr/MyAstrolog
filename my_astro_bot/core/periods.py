"""
periods.py — личные месяцы человека (циклы лунара) и правила доступа к ним.

Личный месяц начинается, когда Луна возвращается в натальную точку, и длится
до следующего возвращения (~27,3 дня). Границы зависят только от даты, времени
и пояса рождения — город, где человек сейчас, влияет на карту, но не на даты.

Тарифы (core/plans.py) продают личные месяцы штучно: оплаченный месяц
записывается «грантом» по моменту начала. Доступ:
  • прошлый месяц (индекс −1) — бесплатно;
  • оплаченный месяц, который уже начался, — открыт навсегда;
  • оплаченный будущий — откроется в момент начала, а с тарифом «наперёд»
    (preview) — сразу;
  • остальное закрыто.

Моменты начала, найденные с разных стартовых точек поиска, расходятся на секунды,
поэтому месяцы сравниваются с допуском MATCH_TOLERANCE (соседние месяцы
отстоят друг от друга на 27 суток, перепутать нельзя).
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Iterable, List, Optional

import swisseph as swe

from core.astrology import AstrologyEngine, utcnow_naive

MEAN_CYCLE_DAYS = 27.3217
MATCH_TOLERANCE = timedelta(hours=6)
MAX_AHEAD = 40              # дальше ~3 лет вперёд месяцы не продаём и не считаем

# Статусы месяца для приложения и бота
OPEN = "open"               # платный доступ выключен — всё открыто
FREE = "free"               # прошлый месяц, бесплатно
PAID = "paid"               # оплачен и уже доступен
PAID_LATER = "paid_later"   # оплачен, откроется в момент начала
LOCKED = "locked"           # не оплачен, можно купить (текущий и будущие)
CLOSED = "closed"           # давно прошёл и не был оплачен

ACCESSIBLE = (OPEN, FREE, PAID)


@dataclass(frozen=True)
class Cycle:
    index: int              # 0 — текущий, −1 — прошлый, 1 — следующий…
    start: datetime         # naive UTC
    end: datetime           # naive UTC


@dataclass(frozen=True)
class Grant:
    cycle_start: datetime
    preview: bool


def _natal_moon(profile) -> float:
    d, m, y = map(int, profile.birth_date.split("."))
    hh, mm = map(int, profile.birth_time.split(":"))
    natal_utc = datetime(y, m, d, hh, mm) - timedelta(hours=profile.birth_utc_offset)
    jd = AstrologyEngine._datetime_to_jd(natal_utc)
    lon, _ = swe.calc_ut(jd, swe.MOON)
    return lon[0]


class CycleCalendar:
    """Границы личных месяцев одного человека относительно момента now."""

    def __init__(self, profile, now: Optional[datetime] = None):
        self.engine = AstrologyEngine()
        self.natal = _natal_moon(profile)
        self.now = now or utcnow_naive()
        self._starts = {}   # индекс → jd начала
        cur = self._find(self.engine._datetime_to_jd(self.now - timedelta(days=28)))
        nxt = self._find(cur + 25.0)
        now_jd = self.engine._datetime_to_jd(self.now)
        if nxt <= now_jd:   # в 28-дневном окне два возвращения — текущее второе
            cur = nxt
        self._starts[0] = cur

    def _find(self, from_jd: float) -> float:
        jd = self.engine._find_next_return(from_jd, self.natal)
        if jd is None:  # не бывает: за 42 дня Луна обязательно возвращается
            raise RuntimeError("lunar return not found")
        return jd

    def _start_jd(self, index: int) -> float:
        if index in self._starts:
            return self._starts[index]
        if index > 0:
            jd = self._find(self._start_jd(index - 1) + 25.0)
        else:
            jd = self._find(self._start_jd(index + 1) - 29.0)
        self._starts[index] = jd
        return jd

    def cycle(self, index: int) -> Cycle:
        to_dt = self.engine._jd_to_datetime
        return Cycle(index, to_dt(self._start_jd(index)), to_dt(self._start_jd(index + 1)))

    def index_of(self, at: datetime) -> int:
        """Номер месяца, в который попадает момент at."""
        start0 = self.cycle(0).start
        i = int((at - start0).total_seconds() // (MEAN_CYCLE_DAYS * 86400))
        for _ in range(4):  # средняя длина неточна — поправляем на соседний
            c = self.cycle(i)
            if at < c.start:
                i -= 1
            elif at >= c.end:
                i += 1
            else:
                return i
        return i

    def index_of_start(self, start: datetime) -> Optional[int]:
        """Номер месяца по моменту его начала (с допуском), None — такого начала нет."""
        i = self.index_of(start + MATCH_TOLERANCE)
        return i if abs(self.cycle(i).start - start) <= MATCH_TOLERANCE else None

    def cycles(self, first: int, last: int) -> List[Cycle]:
        return [self.cycle(i) for i in range(first, last + 1)]


def find_grant(grants: Iterable[Grant], cycle: Cycle) -> Optional[Grant]:
    for g in grants:
        if abs(g.cycle_start - cycle.start) <= MATCH_TOLERANCE:
            return g
    return None


def status(cycle: Cycle, grants: Iterable[Grant], now: datetime, paywall: bool) -> str:
    if not paywall:
        return OPEN
    g = find_grant(grants, cycle)
    if g:
        return PAID if (cycle.start <= now or g.preview) else PAID_LATER
    if cycle.index == -1:
        return FREE
    return CLOSED if cycle.index < -1 else LOCKED


def cycles_to_grant(cal: CycleCalendar, grants: Iterable[Grant], count: int) -> List[Cycle]:
    """
    Какие месяцы получает покупка на count месяцев: первые неоплаченные, начиная
    с текущего. Уже оплаченные не сгорают — пакет продлевается за них.
    """
    grants = list(grants)
    out = []
    i = 0
    while len(out) < count and i <= MAX_AHEAD:
        c = cal.cycle(i)
        if not find_grant(grants, c):
            out.append(c)
        i += 1
    return out


def last_granted_index(cal: CycleCalendar, grants: Iterable[Grant]) -> int:
    """Номер самого дальнего оплаченного месяца (0, если ничего впереди не оплачено)."""
    best = 0
    for g in grants:
        if g.cycle_start > cal.now:
            i = cal.index_of_start(g.cycle_start)
            if i is not None:
                best = max(best, min(i, MAX_AHEAD))
    return best
