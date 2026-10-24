"""Напоминания о новом личном месяце с поддельным ботом."""

import asyncio
from datetime import timedelta

from aiogram.exceptions import TelegramForbiddenError
from aiogram.methods import SendMessage

from bot import delivery, scheduler
from core.astrology import utcnow_naive


class FakeBot:
    def __init__(self, blocked=False):
        self.blocked = blocked
        self.messages, self.photos = [], []

    async def send_message(self, chat_id, text, **kw):
        if self.blocked:
            raise TelegramForbiddenError(method=SendMessage(chat_id=chat_id, text=text),
                                         message="bot was blocked by the user")
        self.messages.append(text)

    async def send_photo(self, chat_id, photo, **kw):
        self.photos.append(photo)

    async def send_chat_action(self, chat_id, action, **kw):
        pass


def _setup(db, profile, monkeypatch):
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.setattr(scheduler, "PAUSE_BETWEEN_USERS", 0)
    db.save_profile(profile)
    db.set_next_cycle(profile.user_id, utcnow_naive() - timedelta(hours=1))


def test_new_cycle_forecast_is_sent_once(db, profile, monkeypatch):
    _setup(db, profile, monkeypatch)
    bot = FakeBot()
    assert asyncio.run(scheduler.run_once(bot)) == 1
    assert "Начался твой новый личный месяц" in bot.messages[0]
    assert len(bot.photos) == 1
    # следующее напоминание перенесено в будущее — второй раз не шлём
    assert db.get_profile(42).next_cycle_utc > utcnow_naive().isoformat()
    assert asyncio.run(scheduler.run_once(bot)) == 0


def test_blocked_user_turns_reminders_off(db, profile, monkeypatch):
    _setup(db, profile, monkeypatch)
    asyncio.run(scheduler.run_once(FakeBot(blocked=True)))
    assert db.get_profile(42).reminders_on is False


def test_paywall_sends_teaser(db, profile, monkeypatch):
    _setup(db, profile, monkeypatch)
    monkeypatch.setenv("PAYWALL_ENABLED", "true")
    bot = FakeBot()
    asyncio.run(delivery.send_forecast(bot, db.get_profile(42)))
    assert any("Звездице+" in m for m in bot.messages)
    assert not any("Как ты хочешь" in m for m in bot.messages)
