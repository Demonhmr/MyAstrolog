"""Личные месяцы: границы, номер месяца по моменту, правила доступа и выдача пакета."""

from datetime import datetime, timedelta

from core import periods
from core.forecast import build_forecast
from core.periods import Grant

NOW = datetime(2026, 11, 21, 12, 0)


def test_cycles_are_contiguous_and_contain_now(profile):
    cal = periods.CycleCalendar(profile, NOW)
    cur = cal.cycle(0)
    assert cur.start <= NOW < cur.end
    cs = cal.cycles(-2, 14)
    for a, b in zip(cs, cs[1:]):
        assert a.end == b.start
        assert timedelta(days=26.5) < (a.end - a.start) < timedelta(days=28.2)


def test_matches_forecast_engine(profile):
    """Границы те же, что у расчёта прогноза (с точностью до минуты)."""
    cal = periods.CycleCalendar(profile, NOW)
    for i in (-1, 0, 5):
        c = cal.cycle(i)
        f = build_forecast(profile, c.start + timedelta(days=10))
        assert abs(f.cycle_start_utc - c.start) < timedelta(minutes=2)


def test_index_of(profile):
    cal = periods.CycleCalendar(profile, NOW)
    for i in (-12, -1, 0, 1, 13, 30):
        c = cal.cycle(i)
        assert cal.index_of(c.start + timedelta(minutes=5)) == i
        assert cal.index_of(c.end - timedelta(minutes=5)) == i
        assert cal.index_of_start(c.start + timedelta(seconds=40)) == i
    assert cal.index_of_start(cal.cycle(0).start + timedelta(days=3)) is None


def test_status_rules(profile):
    cal = periods.CycleCalendar(profile, NOW)
    prev, cur, nxt, far, old = cal.cycle(-1), cal.cycle(0), cal.cycle(1), cal.cycle(5), cal.cycle(-3)
    st = lambda c, g: periods.status(c, g, NOW, True)
    assert periods.status(cur, [], NOW, False) == periods.OPEN
    assert st(prev, []) == periods.FREE
    assert st(cur, []) == periods.LOCKED
    assert st(old, []) == periods.CLOSED
    g = [Grant(cur.start + timedelta(seconds=30), False), Grant(nxt.start, False),
         Grant(far.start, True), Grant(old.start, False)]
    assert st(cur, g) == periods.PAID
    assert st(nxt, g) == periods.PAID_LATER            # оплачен, но ещё не начался
    assert st(far, g) == periods.PAID                  # «наперёд» — открыт сразу
    assert st(old, g) == periods.PAID                  # оплаченный прошлый — навсегда
    # месяц начался — оплаченный «потом» становится открытым
    assert periods.status(nxt, g, nxt.start + timedelta(minutes=1), True) == periods.PAID


def test_cycles_to_grant_skips_paid(profile):
    cal = periods.CycleCalendar(profile, NOW)
    got = periods.cycles_to_grant(cal, [], 3)
    assert [c.index for c in got] == [0, 1, 2]
    have = [Grant(cal.cycle(0).start, False), Grant(cal.cycle(2).start, False)]
    got = periods.cycles_to_grant(cal, have, 3)
    assert [c.index for c in got] == [1, 3, 4]
    assert periods.last_granted_index(cal, have) == 2
