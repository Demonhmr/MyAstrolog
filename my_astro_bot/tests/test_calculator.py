"""Tests for AstroCalculator: weights sum to 26, dominants, synthetics."""

from core.calculator import AstroCalculator, EXPECTED_TOTAL


def _planets_fixture():
    # All 10 planets, arbitrary but valid signs/houses
    return [
        {"name": "Sun",     "sign": "Leo",         "house": 1},
        {"name": "Moon",    "sign": "Cancer",      "house": 4},
        {"name": "Mercury", "sign": "Virgo",       "house": 2},
        {"name": "Venus",   "sign": "Libra",       "house": 3},
        {"name": "Mars",    "sign": "Aries",       "house": 5},
        {"name": "Jupiter", "sign": "Sagittarius", "house": 9},
        {"name": "Saturn",  "sign": "Capricorn",   "house": 10},
        {"name": "Uranus",  "sign": "Aquarius",    "house": 11},
        {"name": "Neptune", "sign": "Pisces",      "house": 12},
        {"name": "Pluto",   "sign": "Scorpio",     "house": 8},
    ]


def test_scores_sum_to_26():
    calc = AstroCalculator()
    sign_scores, house_scores = calc.calculate_scores(_planets_fixture())
    for scores in (sign_scores, house_scores):
        assert sum(scores["elements"].values()) == EXPECTED_TOTAL
        assert sum(scores["crosses"].values()) == EXPECTED_TOTAL


def test_planet_weights_sum():
    assert sum(AstroCalculator.WEIGHTS.values()) == EXPECTED_TOTAL


def test_dominants_and_synthetics():
    calc = AstroCalculator()
    # Sun(5)+Mars(3)+Jupiter(2) fire = 10 → fire dominates
    sign_scores, _ = calc.calculate_scores(_planets_fixture())
    el, cr = calc.get_dominants(sign_scores)
    assert el in ("Огонь", "Земля", "Воздух", "Вода")
    assert cr in ("Кардинальный", "Фиксированный", "Мутабельный")

    synth = calc.get_synthetic_sign(el, cr)
    assert synth in calc.ZODIAC
    assert calc.ZODIAC[synth] == {"element": el, "cross": cr}

    house = calc.get_synthetic_house(el, cr)
    assert house is not None
    assert calc.HOUSE_PROPS[int(house)] == {"element": el, "cross": cr}


def test_dominants_empty_scores():
    calc = AstroCalculator()
    assert calc.get_dominants({"elements": {}, "crosses": {}}) == (None, None)
    assert calc.get_synthetic_sign(None, None) is None
    assert calc.get_synthetic_house(None, None) is None
