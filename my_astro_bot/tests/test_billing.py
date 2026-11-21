"""Тарифы в звёздах, оплата в боте и выдача личных месяцев."""

import asyncio
from types import SimpleNamespace

from bot import delivery
from bot.handlers import payments
from core import billing, periods, plans, webstore


def test_payload_roundtrip():
    assert billing.parse_payload(billing.make_payload("p3", 42)) == ("p3", 42)
    assert billing.parse_payload("zv:month:42") is None       # старый тариф подписки
    assert billing.parse_payload("zv:p3:abc") is None
    assert billing.parse_payload("") is None


def test_prices():
    p = plans.plans()
    assert [(x.code, x.rub, x.months, x.preview) for x in p.values()] == [
        ("one", 150, 1, False), ("p3", 390, 3, False), ("p6", 590, 6, False),
        ("p13", 990, 13, False), ("plus", 1590, 13, True)]
    # звёзды ≈ рубли / 1,5, кратно 5
    assert [x.stars for x in p.values()] == [100, 260, 395, 660, 1060]


def test_prices_from_env(monkeypatch):
    monkeypatch.setenv("PRICE_P3_STARS", "250")
    monkeypatch.setenv("PRICE_ONE_RUB", "199")
    assert plans.get("p3").stars == 250
    assert plans.get("one").rub == 199 and plans.get("one").stars == 135


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


def _payment(charge_id, plan="p3", user_id=42):
    return SimpleNamespace(
        invoice_payload=billing.make_payload(plan, user_id), total_amount=plans.get(plan).stars,
        currency="XTR", telegram_payment_charge_id=charge_id,
    )


def test_successful_payment_grants_months_and_sends_forecast(db, profile, monkeypatch):
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.setenv("PAYWALL_ENABLED", "true")
    db.save_profile(profile)
    bot = FakeBot()
    msg = FakeMessage(42, _payment("ch-1"), bot)
    asyncio.run(payments.successful_payment(msg))
    assert "Открыто 3 месяца" in msg.answers[0]
    assert any("Как ты хочешь" in m for m in bot.messages)  # текущий месяц сразу
    st = [s for _, s in delivery.months_overview(db.get_profile(42))]
    assert st[:5] == [periods.FREE, periods.PAID, periods.PAID_LATER, periods.PAID_LATER, periods.LOCKED]

    # Telegram прислал тот же платёж повторно — месяцы не добавляются
    asyncio.run(payments.successful_payment(FakeMessage(42, _payment("ch-1"), bot)))
    assert len(webstore.grants_of("t:42")) == 3
    assert len(db.payments_of(42)) == 1

    # «Год наперёд»: следующие 13 месяцев, открыты сразу
    msg = FakeMessage(42, _payment("ch-2", "plus"), bot)
    asyncio.run(payments.successful_payment(msg))
    assert "Открыто 13 месяцев" in msg.answers[0]
    st = [s for _, s in delivery.months_overview(db.get_profile(42))]
    assert st[1:5] == [periods.PAID, periods.PAID_LATER, periods.PAID_LATER, periods.PAID]
    assert len(st) == 17


def test_pre_checkout_checks_amount_user_and_profile(db, profile):
    db.save_profile(profile)
    answers = []

    class Q(SimpleNamespace):
        async def answer(self, ok, error_message=None):
            answers.append(ok)

    stars = plans.get("one").stars
    good = Q(invoice_payload="zv:one:42", currency="XTR", total_amount=stars, from_user=SimpleNamespace(id=42))
    wrong_user = Q(invoice_payload="zv:one:42", currency="XTR", total_amount=stars, from_user=SimpleNamespace(id=7))
    wrong_sum = Q(invoice_payload="zv:one:42", currency="XTR", total_amount=1, from_user=SimpleNamespace(id=42))
    old_plan = Q(invoice_payload="zv:month:42", currency="XTR", total_amount=200, from_user=SimpleNamespace(id=42))
    for q in (good, wrong_user, wrong_sum, old_plan):
        asyncio.run(payments.pre_checkout(q))
    assert answers == [True, False, False, False]
