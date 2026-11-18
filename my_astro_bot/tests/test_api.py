"""Сервер расчёта для приложения: прогноз, карта, города, проверки и лимиты."""

from datetime import datetime
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from api import app as api_mod
from core import geocoder

MOSCOW = {"name": "Москва, Россия", "lat": 55.7558, "lon": 37.6173, "tz": "Europe/Moscow"}
KAZAN = {"name": "Казань, Россия", "lat": 55.7963, "lon": 49.1088, "tz": "Europe/Moscow"}
BODY = {"birth_date": "1990-01-15", "birth_time": "14:30", "birth_place": MOSCOW}


@pytest.fixture
def client():
    # свежие лимиты и кэши на каждый тест
    api_mod._rl_forecast.hits.clear()
    api_mod._rl_cities.hits.clear()
    api_mod._city_cache.clear()
    api_mod._chart_cache.clear()
    return TestClient(api_mod.app)


def test_health(client):
    assert client.get("/api/health").json()["ok"] is True


def test_forecast_structure(client):
    r = client.post("/api/forecast", json=BODY)
    assert r.status_code == 200
    d = r.json()
    assert d["time_known"] is True
    assert d["cycle"]["start"] < d["cycle"]["end"]
    assert d["cycle"]["end_utc"].endswith("Z")
    assert d["role"]["title"] and d["role"]["sign_ru"]
    assert 1 <= d["task"]["house"] <= 12
    assert d["climate"]["inner"].startswith("Хочется")
    assert d["story"]["source"] == "dictionary" and d["story"]["sections"]
    assert d["dynamics"]["start"]["text"] and d["dynamics"]["end"]["text"]
    assert len(d["expert"]["planets"]) == 10
    # никаких HTML-тегов в текстах для приложения
    assert "<b>" not in r.text and "<i>" not in r.text


def test_forecast_contains_no_birth_data(client):
    r = client.post("/api/forecast", json=BODY)
    assert "1990" not in r.text and "14:30" not in r.text


def test_forecast_matches_bot(client, profile):
    """Те же роль, задача и даты цикла, что у бота для того же профиля."""
    from core.forecast import build_forecast
    f = build_forecast(profile)
    d = client.post("/api/forecast", json=BODY).json()
    assert d["role"]["sign"] == f.synth_sign
    assert d["task"]["house"] == int(f.synth_house)
    assert d["cycle"]["start_utc"] == f.cycle_start_utc.strftime("%Y-%m-%dT%H:%M:%SZ")


def test_unknown_time_and_current_place(client):
    body = {**BODY, "birth_time": None, "current_place": KAZAN}
    d = client.post("/api/forecast", json=body).json()
    assert d["time_known"] is False
    assert d["cycle"]["city"].startswith("Казань")


def test_next_month_via_at(client):
    now = client.post("/api/forecast", json=BODY).json()
    nxt = client.post("/api/forecast", json={**BODY, "at": now["cycle"]["end_utc"].replace("Z", "+00:00")}).json()
    # следующий цикл начинается там, где кончился текущий (с точностью до минуты)
    a = datetime.fromisoformat(now["cycle"]["end_utc"].replace("Z", "+00:00"))
    b = datetime.fromisoformat(nxt["cycle"]["start_utc"].replace("Z", "+00:00"))
    assert abs((a - b).total_seconds()) < 120


@pytest.mark.parametrize("patch_body", [
    {"birth_date": "1850-01-01"},
    {"birth_date": "2999-01-01"},
    {"birth_time": "25:00"},
    {"birth_place": {**MOSCOW, "tz": "Mars/Olympus"}},
    {"birth_place": {**MOSCOW, "lat": 123}},
    {"at": "2000-01-01T00:00:00Z"},
])
def test_bad_input_is_422_in_russian(client, patch_body):
    r = client.post("/api/forecast", json={**BODY, **patch_body})
    assert r.status_code == 422
    assert r.json()["error"]


def test_chart_png(client):
    r = client.post("/api/chart", json=BODY)
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/png"
    assert r.content[:8] == b"\x89PNG\r\n\x1a\n"


def test_cities_cached_and_filtered(client):
    found = [{"name": "Казань, Россия", "lat": 55.79, "lon": 49.1, "tz": "Europe/Moscow"}]
    with patch.object(geocoder, "search_cities", return_value=found) as m:
        assert client.get("/api/cities", params={"q": "Казань"}).json() == {"cities": found}
        assert client.get("/api/cities", params={"q": "  казань "}).json() == {"cities": found}
    assert m.call_count == 1


def test_cities_service_down(client):
    with patch.object(geocoder, "search_cities", side_effect=ValueError("недоступен")):
        r = client.get("/api/cities", params={"q": "Казань"})
    assert r.status_code == 503 and "недоступен" in r.json()["error"]


def test_rate_limit(client, monkeypatch):
    monkeypatch.setattr(api_mod, "_rl_forecast", api_mod.RateLimit(2, 600))
    assert client.post("/api/forecast", json=BODY).status_code == 200
    assert client.post("/api/forecast", json=BODY).status_code == 200
    r = client.post("/api/forecast", json=BODY)
    assert r.status_code == 429 and r.json()["error"]


def test_search_cities_filters_non_places():
    from types import SimpleNamespace as NS
    locs = [
        NS(latitude=55.79, longitude=49.10, address="Казань", raw={"addresstype": "city", "class": "place"}),
        NS(latitude=55.791, longitude=49.101, address="Казань (дубль)", raw={"addresstype": "city", "class": "place"}),
        NS(latitude=55.0, longitude=49.0, address="река Казанка", raw={"addresstype": "river", "class": "waterway", "importance": 0.1}),
    ]
    with patch.object(geocoder._geolocator, "geocode", return_value=locs):
        out = geocoder.search_cities("Казань")
    assert [c["name"] for c in out] == ["Казань"]
    assert out[0]["tz"] == "Europe/Moscow"
