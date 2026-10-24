"""Тексты для людей: без терминов методики и в пределах лимита Telegram."""

import json
import re
from dataclasses import replace
from datetime import datetime

import pytest

from core import texts
from core.forecast import build_forecast
from core.interpretator import DATA_DIR

DATA = json.loads((DATA_DIR / "interpretations" / "interpretations.json").read_text("utf-8"))
JARGON = re.compile(r"синтетич|асцендент|лунар|крест|\bMC\b|стихи|\d+\s*дом", re.I)
TG_LIMIT = 4096


@pytest.fixture
def forecast(profile):
    return build_forecast(profile, at=datetime(2026, 10, 24, 12, 0))


def test_summary(forecast):
    out = texts.render_summary(forecast)
    assert "Роль месяца" in out and "Главная задача" in out
    assert not JARGON.search(out)
    assert "Начался" in texts.render_summary(forecast, new_cycle=True)


def test_unknown_time_warning(forecast):
    assert "приблизительный" not in texts.render_summary(forecast)
    assert "приблизительный" in texts.render_summary(replace(forecast, time_known=False))


@pytest.mark.parametrize("i,sign", list(enumerate(texts.ROLES)))
def test_fallback_story_every_combination(forecast, i, sign):
    f = replace(forecast, synth_sign=sign, synth_house=str(i + 1))
    out = texts.render_story_header(f) + texts.render_story_fallback(f, DATA)
    for section in ("Тебе захочется", "А жизнь тебе", "Чему учат обстоятельства", "Что поможет"):
        assert section in out
    assert not JARGON.search(out)
    assert len(out) < TG_LIMIT


def test_dynamics(forecast):
    out = texts.render_dynamics(forecast, DATA)
    assert "Начало месяца" in out and "Финал месяца" in out
    assert not re.search(r"\*\*", out)
    assert len(out) < TG_LIMIT


def test_expert_keeps_terms(forecast):
    out = texts.render_expert(forecast)
    assert "Синтетический знак" in out and "Асцендент" in out
    assert len(out) < TG_LIMIT
