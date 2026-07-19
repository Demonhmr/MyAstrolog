"""Tests for AstrologyEngine: lunar return correctness on Swiss Ephemeris."""

from datetime import datetime, timedelta

import swisseph as swe

from core.astrology import AstrologyEngine, SIGN_RULERS, utcnow_naive


BIRTH = dict(name="Test", year=1990, month=1, day=15, hour=14, minute=30,
             lat=55.7558, lon=37.6173, utc_offset=3.0)


def test_lunar_return_moon_matches_natal():
    """At the found return moment the Moon must be at the natal longitude."""
    engine = AstrologyEngine()
    result = engine.get_lunar_return(**BIRTH)

    natal_utc = datetime(
        BIRTH["year"], BIRTH["month"], BIRTH["day"], BIRTH["hour"], BIRTH["minute"]
    ) - timedelta(hours=BIRTH["utc_offset"])
    jd_natal = engine._datetime_to_jd(natal_utc)
    natal_lon = swe.calc_ut(jd_natal, swe.MOON)[0][0]

    return_lon = swe.calc_ut(result["chart_data"]["jd"], swe.MOON)[0][0]
    diff = abs(return_lon - natal_lon)
    if diff > 180:
        diff = 360 - diff
    # 1-hour steps + linear interpolation → should be well within 0.05°
    assert diff < 0.05


def test_cycle_contains_today():
    engine = AstrologyEngine()
    result = engine.get_lunar_return(**BIRTH)
    now = utcnow_naive()
    assert result["start_date"] <= now <= result["end_date"]

    cycle_days = (result["end_date"] - result["start_date"]).total_seconds() / 86400
    assert 26.5 < cycle_days < 28.5  # sidereal month ≈ 27.32 days


def test_planets_data_complete():
    engine = AstrologyEngine()
    result = engine.get_lunar_return(**BIRTH)
    planets = engine.get_planets_data(result["chart_data"])

    assert len(planets) == 10
    for p in planets:
        assert 1 <= p["house"] <= 12
        assert 0 <= p["lon_deg"] < 360
        assert isinstance(p["is_retro"], bool)

    points = engine.get_chart_points(result["chart_data"])
    assert "ascendant" in points and "midheaven" in points
    assert 0 <= points["ascendant_deg"] < 360


def test_sign_rulers_cover_all_signs():
    signs = ["Aries", "Taurus", "Gemini", "Cancer", "Leo", "Virgo",
             "Libra", "Scorpio", "Sagittarius", "Capricorn", "Aquarius", "Pisces"]
    planet_names = {"Sun", "Moon", "Mercury", "Venus", "Mars", "Jupiter",
                    "Saturn", "Uranus", "Neptune", "Pluto"}
    for sign in signs:
        assert SIGN_RULERS[sign] in planet_names
