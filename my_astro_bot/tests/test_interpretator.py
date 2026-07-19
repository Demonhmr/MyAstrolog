"""Tests for ReportInterpretator: templates render, HTML is safe."""

import re

from core.interpretator import ReportInterpretator, HOUSE_SPHERES, PLANET_RU


def _interp():
    return ReportInterpretator()  # default package-relative path


def test_sanitize_escapes_html():
    interp = _interp()
    out = interp._sanitize("Fish & <chips> **bold**")
    assert "&amp;" in out
    assert "&lt;chips&gt;" in out
    assert "**" not in out


def test_generate_report():
    interp = _interp()
    report = interp.generate_report(
        ("Огонь", "Кардинальный"), ("Земля", "Фиксированный"),
        "Aries", "2", {"start_sign": "Leo", "end_sign": "Taurus"},
    )
    assert "Овен" in report
    assert "Дом 2" in report
    assert len(report) <= 4096  # Telegram message limit


def test_generate_dynamics_with_rulers():
    interp = _interp()
    report = interp.generate_dynamics_report({
        "start_sign": "Leo", "end_sign": "Taurus",
        "asc_ruler": "Sun", "asc_ruler_house": 3,
        "mc_ruler": "Venus", "mc_ruler_house": 10,
    })
    assert "Лев" in report and "Телец" in report
    assert "Солнце" in report and "Венера" in report
    assert HOUSE_SPHERES[3] in report
    assert HOUSE_SPHERES[10] in report


def test_generate_dynamics_without_rulers():
    interp = _interp()
    report = interp.generate_dynamics_report({"start_sign": "Leo", "end_sign": "Taurus"})
    assert "Управитель" not in report


def test_generate_llm_prompt_no_leftover_placeholders():
    interp = _interp()
    prompt = interp.generate_llm_prompt(
        ("Огонь", "Кардинальный"), ("Земля", "Фиксированный"), "Aries", "2",
    )
    assert not prompt.startswith("Ошибка")
    leftovers = re.findall(r"\{[a-z_]+\}", prompt)
    assert leftovers == []


def test_house_spheres_cover_all_houses():
    assert set(HOUSE_SPHERES) == set(range(1, 13))
    assert len(PLANET_RU) == 10
