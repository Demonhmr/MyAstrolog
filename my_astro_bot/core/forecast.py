"""
forecast.py — расчёт прогноза на личный месяц (лунар) для одного профиля.

Здесь только астрология и числа, без текстов для людей (они в core/texts.py)
и без Telegram. Расчёт синхронный и тяжёлый: из бота его зовут через
asyncio.to_thread.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import pytz

from core.astrology import AstrologyEngine, SIGN_RULERS
from core.calculator import AstroCalculator


@dataclass
class Forecast:
    name: str
    city: str
    tz: str
    time_known: bool
    cycle_start_utc: datetime      # naive UTC
    cycle_end_utc: datetime        # naive UTC
    start_local: datetime
    end_local: datetime
    planets: list
    points: dict
    sign_scores: dict
    house_scores: dict
    el_s: str
    cr_s: str
    el_h: str
    cr_h: str
    synth_sign: Optional[str]      # «роль месяца», англ. название знака
    synth_house: Optional[str]     # «главная задача», номер дома строкой
    dynamics: dict


def build_forecast(profile, at: Optional[datetime] = None) -> Forecast:
    """
    profile — объект с полями Profile (core.storage) или похожий.
    at — момент (naive UTC), для которого ищется текущий личный месяц.
    """
    d, m, y = map(int, profile.birth_date.split("."))
    hh, mm = map(int, profile.birth_time.split(":"))

    engine = AstrologyEngine()
    calc = AstroCalculator()

    # Натальная Луна — по месту и поясу рождения; карта лунара — на текущий город
    lunar = engine.get_lunar_return(
        profile.name, y, m, d, hh, mm,
        profile.cur_lat, profile.cur_lon, profile.birth_utc_offset,
        at=at,
    )
    chart = lunar["chart_data"]
    planets = engine.get_planets_data(chart)
    points = engine.get_chart_points(chart)

    sign_scores, house_scores = calc.calculate_scores(planets)
    el_s, cr_s = calc.get_dominants(sign_scores)
    el_h, cr_h = calc.get_dominants(house_scores)

    tz = pytz.timezone(profile.cur_tz)
    start_local = pytz.utc.localize(lunar["start_date"]).astimezone(tz)
    end_local = pytz.utc.localize(lunar["end_date"]).astimezone(tz)

    by_name = {p["name"]: p for p in planets}
    asc_ruler = SIGN_RULERS.get(points["ascendant"])
    mc_ruler = SIGN_RULERS.get(points["midheaven"])
    dynamics = {
        "start_sign": points["ascendant"],
        "end_sign": points["midheaven"],
        "asc_ruler": asc_ruler,
        "asc_ruler_house": by_name.get(asc_ruler, {}).get("house"),
        "mc_ruler": mc_ruler,
        "mc_ruler_house": by_name.get(mc_ruler, {}).get("house"),
    }

    return Forecast(
        name=profile.name,
        city=profile.cur_city,
        tz=profile.cur_tz,
        time_known=bool(getattr(profile, "time_known", True)),
        cycle_start_utc=lunar["start_date"],
        cycle_end_utc=lunar["end_date"],
        start_local=start_local,
        end_local=end_local,
        planets=planets,
        points=points,
        sign_scores=sign_scores,
        house_scores=house_scores,
        el_s=el_s, cr_s=cr_s, el_h=el_h, cr_h=cr_h,
        synth_sign=calc.get_synthetic_sign(el_s, cr_s),
        synth_house=calc.get_synthetic_house(el_h, cr_h),
        dynamics=dynamics,
    )
