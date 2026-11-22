"""Живой текст нейросети на сайте: общий кэш по сочетанию, /api/story, суточный лимит."""

import asyncio

import pytest
from fastapi.testclient import TestClient

from api import app as api_mod
from core import llm, webstore

MOSCOW = {"name": "Москва, Россия", "lat": 55.7558, "lon": 37.6173, "tz": "Europe/Moscow"}
BODY = {"birth_date": "1990-01-15", "birth_time": "14:30", "birth_place": MOSCOW}
TEXT = "<b>Как ты себя чувствуешь:</b>\nЖивой текст " + "очень " * 60


@pytest.fixture
def client():
    api_mod._rl_forecast.hits.clear()
    api_mod._story_jobs.clear()
    return TestClient(api_mod.app)


@pytest.fixture
def fake_llm(monkeypatch):
    calls = []

    async def write_story(prompt):
        calls.append(prompt)
        await asyncio.sleep(0)
        return TEXT

    monkeypatch.setenv("LLM_API_KEY", "test")
    monkeypatch.delenv("LLM_WEB_DAILY", raising=False)
    monkeypatch.setattr(llm, "write_story", write_story)
    return calls


def test_without_key_dictionary_only(client, monkeypatch):
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    rep = client.post("/api/forecast", json=BODY).json()
    assert rep["story"]["source"] == "dictionary" and "story_pending" not in rep
    assert client.post("/api/story", json=BODY).json() == {"story": None}


def test_story_written_once_and_shared(client, fake_llm):
    rep = client.post("/api/forecast", json=BODY).json()
    assert rep["story"]["source"] == "dictionary" and rep["story_pending"] is True
    assert "|" in rep["story_key"]

    r = client.post("/api/story", json=BODY).json()
    assert r["story"] == {"source": "llm", "text": TEXT}
    assert len(fake_llm) == 1
    # в промпт не попадают данные рождения
    assert "1990" not in fake_llm[0] and "Москва" not in fake_llm[0]

    # теперь текст отдаётся сразу, нейросеть больше не зовём
    rep2 = client.post("/api/forecast", json=BODY).json()
    assert rep2["story"] == {"source": "llm", "text": TEXT} and "story_pending" not in rep2
    assert client.post("/api/story", json=BODY).json()["story"]["text"] == TEXT
    assert len(fake_llm) == 1
    assert webstore.llm_story(rep["story_key"]) == TEXT


def test_llm_failure_keeps_dictionary(client, monkeypatch):
    async def fail(prompt):
        return None

    monkeypatch.setenv("LLM_API_KEY", "test")
    monkeypatch.setattr(llm, "write_story", fail)
    assert client.post("/api/story", json=BODY).json() == {"story": None}
    rep = client.post("/api/forecast", json=BODY).json()
    assert rep["story"]["source"] == "dictionary" and rep["story_pending"] is True


def test_daily_limit(client, fake_llm, monkeypatch):
    monkeypatch.setenv("LLM_WEB_DAILY", "0")
    rep = client.post("/api/forecast", json=BODY).json()
    assert "story_pending" not in rep
    assert client.post("/api/story", json=BODY).json() == {"story": None}
    assert fake_llm == []


def test_story_closed_month(client, fake_llm, monkeypatch):
    monkeypatch.setenv("WEB_PAYWALL", "on")
    # без входа при платном доступе текущий месяц закрыт
    r = client.post("/api/story", json=BODY)
    assert r.status_code == 402
    assert fake_llm == []


def test_reasoning_off_by_default(monkeypatch):
    sent = {}

    class Resp:
        status = 200

        async def json(self, content_type=None):
            return {"choices": [{"message": {"content": "Текст " * 100}}]}

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

    class Session:
        def __init__(self, *a, **k):
            pass

        def post(self, url, json=None, headers=None):
            sent.update(json)
            return Resp()

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

    monkeypatch.setenv("LLM_API_KEY", "test")
    monkeypatch.setattr(llm.aiohttp, "ClientSession", Session)
    assert asyncio.run(llm.write_story("p"))
    assert sent["reasoning"] == {"enabled": False}
    monkeypatch.setenv("LLM_REASONING", "on")
    sent.clear()
    asyncio.run(llm.write_story("p"))
    assert "reasoning" not in sent
