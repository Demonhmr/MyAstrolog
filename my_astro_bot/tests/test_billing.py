"""Тарифы, продление подписки и обработка успешной оплаты Stars."""

import asyncio
from datetime import datetime, timedelta
from types import SimpleNamespace

from bot.handlers import payments
from core import billing
from core.astrology import utcnow_naive

NOW = datetime(2026, 11, 1, 12, 0)


def test_payload_roundtrip():
    assert billing.parse_payload(billing.make_payload("month", 42)) == ("month", 42)
    assert billing.parse_payload("zv:forever:42") is None
    assert billing.parse_payload("zv:month:abc") is None
    assert billing.parse_payload("") is None


def test_prices_from_env(monkeypatch):
    monkeypatch.setenv("PRICE_MONTH_STARS", "150")
    assert billing.plans()["month"].stars == 150
    assert billing.plans()["month"].recurring and not billing.plans()["year"].recurring


def test_premium_extension():
    month, year = billing.plans()["month"], billing.plans()["year"]
    assert billing.new_premium_until(month, NOW, None) == NOW + timedelta(days=30)
    # истёкшая подписка — считаем от «сейчас»
    assert billing.new_premium_until(month, NOW, NOW - timedelta(days=5)) == NOW + timedelta(days=30)
    # действующий год + месяц — дни не теряются
    active = NOW + timedelta(days=100)
    assert billing.new_premium_until(month, NOW, active) == active + timedelta(days=30)
    assert billing.new_premium_until(year, NOW, None) == NOW + timedelta(days=365)


class FakeMessage:
    def __init__(self, user_id, sp, bot):
        self.from_user = SimpleNamespace(id=user_id)
        self.successful_payment = sp
        self.bot = bot
        self.answers = []

    async def answer(self, text, **kw):
        self.answers.append(text)


class FakeBot:
    def __init__(self):
        self.messages = []

    async def send_message(self, chat_id, text, **kw):
        self.messages.append(text)

    async def send_photo(self, *a, **kw):
        pass

    async def send_chat_action(self, *a, **kw):
        pass


def _payment(charge_id, recurring=True, first=True, plan="month", user_id=42, amount=200):
    return SimpleNamespace(
        invoice_payload=billing.make_payload(plan, user_id), total_amount=amount, currency="XTR",
        telegram_payment_charge_id=charge_id, is_recurring=recurring, is_first_recurring=first,
    )


def test_successful_payment_activates_and_sends_forecast(db, profile, monkeypatch):
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.setenv("PAYWALL_ENABLED", "true")
    db.save_profile(profile)
    bot = FakeBot()
    msg = FakeMessage(42, _payment("ch-1"), bot)
    asyncio.run(payments.successful_payment(msg))

    p = db.get_profile(42)
    assert p.is_premium()
    assert "активна до" in msg.answers[0]
    assert any("Как ты хочешь" in m for m in bot.messages)  # полный прогноз сразу

    # Telegram прислал тот же платёж повторно — второй раз не продлеваем
    until = p.premium_until
    asyncio.run(payments.successful_payment(FakeMessage(42, _payment("ch-1"), bot)))
    assert db.get_profile(42).premium_until == until
    assert len(db.payments_of(42)) == 1


def test_recurring_renewal_extends(db, profile, monkeypatch):
    db.save_profile(profile)
    bot = FakeBot()
    asyncio.run(payments.successful_payment(FakeMessage(42, _payment("ch-1"), bot)))
    first = datetime.fromisoformat(db.get_profile(42).premium_until)
    renewal = FakeMessage(42, _payment("ch-2", first=False), bot)
    asyncio.run(payments.successful_payment(renewal))
    assert datetime.fromisoformat(db.get_profile(42).premium_until) == first + timedelta(days=30)
    assert "продлена" in renewal.answers[0]
    assert first > utcnow_naive()


def test_pre_checkout_checks_amount_and_user(monkeypatch):
    answers = []

    class Q(SimpleNamespace):
        async def answer(self, ok, error_message=None):
            answers.append(ok)

    good = Q(invoice_payload="zv:month:42", currency="XTR", total_amount=200, from_user=SimpleNamespace(id=42))
    wrong_user = Q(invoice_payload="zv:month:42", currency="XTR", total_amount=200, from_user=SimpleNamespace(id=7))
    wrong_sum = Q(invoice_payload="zv:month:42", currency="XTR", total_amount=1, from_user=SimpleNamespace(id=42))
    for q in (good, wrong_user, wrong_sum):
        asyncio.run(payments.pre_checkout(q))
    assert answers == [True, False, False]
