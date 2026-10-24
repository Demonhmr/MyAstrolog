"""Расчёт личного месяца для профиля на заданный момент."""

from dataclasses import replace
from datetime import datetime, timedelta

from core.forecast import build_forecast

AT = datetime(2026, 10, 24, 12, 0)


def test_cycle_contains_moment(profile):
    f = build_forecast(profile, at=AT)
    assert f.cycle_start_utc <= AT < f.cycle_end_utc
    length = f.cycle_end_utc - f.cycle_start_utc
    assert timedelta(days=26.5) < length < timedelta(days=28.5)


def test_next_cycle_starts_where_previous_ends(profile):
    f1 = build_forecast(profile, at=AT)
    f2 = build_forecast(profile, at=f1.cycle_end_utc + timedelta(minutes=10))
    assert abs((f2.cycle_start_utc - f1.cycle_end_utc).total_seconds()) < 120


def test_result_fields(profile):
    f = build_forecast(profile, at=AT)
    assert f.synth_sign and f.synth_house
    assert f.start_local.tzinfo is not None
    assert f.dynamics["start_sign"] == f.points["ascendant"]
    assert sum(f.sign_scores["elements"].values()) == 26


def test_unknown_time_flag(profile):
    f = build_forecast(replace(profile, time_known=False, birth_time="12:00"), at=AT)
    assert f.time_known is False
