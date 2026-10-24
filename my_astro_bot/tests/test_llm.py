"""Нейросеть: без ключа — None, ответ превращается в безопасный Telegram-HTML."""

import asyncio

from core import llm


def test_no_key_returns_none(monkeypatch):
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    assert not llm.is_configured()
    assert asyncio.run(llm.write_story("prompt")) is None


def test_to_telegram_html():
    raw = (
        "Внутри — ВОЗДУХ (хочу обсуждать)\n"
        "Снаружи — ОГОНЬ (жизнь требует действий)\n\n"
        "Как ты себя чувствуешь:\nТы любишь <думать> & **взвешивать**.\n\n\n\n"
        "Ты хочешь:\n— обсудить"
    )
    out = llm.to_telegram_html(raw)
    assert "<b>Внутри — ВОЗДУХ (хочу обсуждать)</b>" in out
    assert "<b>Как ты себя чувствуешь:</b>" in out
    assert "&lt;думать&gt; &amp; взвешивать" in out
    assert "**" not in out and "\n\n\n" not in out


def test_long_answer_is_cut():
    out = llm.to_telegram_html(("абзац " * 50 + "\n") * 40)
    assert len(out) <= llm.MAX_CHARS


def test_network_error_returns_none(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "test")
    monkeypatch.setenv("LLM_BASE_URL", "http://127.0.0.1:9")  # закрытый порт
    assert asyncio.run(llm.write_story("prompt")) is None
