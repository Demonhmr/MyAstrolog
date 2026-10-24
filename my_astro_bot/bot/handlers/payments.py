"""
bot/handlers/payments.py — Звездица+ за Telegram Stars.

/premium показывает тарифы и кнопки оплаты (если включён PAYWALL_ENABLED),
pre_checkout подтверждает счёт, successful_payment продлевает подписку
и сразу присылает полный прогноз. /paysupport обязателен по правилам Telegram.
"""

import asyncio
import logging
import os
from datetime import datetime

from aiogram import Router, types, F
from aiogram.filters import Command, StateFilter
from aiogram.types import LabeledPrice
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot import delivery
from core import billing, storage
from core.astrology import utcnow_naive

router = Router()
logger = logging.getLogger(__name__)

PREMIUM_TEXT = (
    "✨ <b>Звездица+</b>\n\n"
    "• живой разбор месяца «как хочешь / как будет»\n"
    "• как начнётся и чем закончится месяц\n"
    "• подробный расчёт для знатоков\n"
    "• прогноз приходит сам в начале каждого личного месяца\n\n"
    "Бесплатно остаются даты личного месяца, роль месяца, главная задача и карта неба."
)


def support_contact() -> str:
    return os.getenv("SUPPORT_CONTACT", "[почта поддержки]")


def terms_url() -> str:
    return os.getenv("TERMS_URL", "https://zvezditsa.ru/oferta.html")


async def _invoice_link(bot, plan: billing.Plan, user_id: int) -> str:
    kwargs = dict(
        title=plan.title,
        description=(
            "Полный прогноз на каждый личный месяц. Автопродление раз в 30 дней, "
            "отменить можно в любой момент в настройках Telegram."
            if plan.recurring else
            "Полный прогноз на каждый личный месяц в течение года. Без автопродления."
        ),
        payload=billing.make_payload(plan.code, user_id),
        currency="XTR",
        prices=[LabeledPrice(label=plan.title, amount=plan.stars)],
    )
    if plan.recurring:
        kwargs["subscription_period"] = billing.SUBSCRIPTION_PERIOD
    return await bot.create_invoice_link(**kwargs)


@router.message(Command("premium"), StateFilter("*"))
async def cmd_premium(message: types.Message):
    user_id = message.from_user.id
    p = await asyncio.to_thread(storage.get_profile, user_id)
    if p and p.is_premium():
        await message.answer(
            f"{PREMIUM_TEXT}\n\n✅ Подписка активна до <b>{p.premium_until[:10]}</b>.",
            parse_mode="HTML",
        )
        return
    if not delivery.paywall_enabled():
        await message.answer(f"{PREMIUM_TEXT}\n\nСейчас весь прогноз доступен бесплатно.", parse_mode="HTML")
        return
    if not p:
        await message.answer("Сначала ответь на 4 вопроса, чтобы я посчитала твой месяц: /start")
        return

    kb = InlineKeyboardBuilder()
    try:
        for plan in billing.plans().values():
            link = await _invoice_link(message.bot, plan, user_id)
            label = f"Месяц — {plan.stars} ⭐" if plan.recurring else f"Год — {plan.stars} ⭐"
            kb.button(text=label, url=link)
    except Exception as e:
        logger.error("Invoice link failed: %s", e, exc_info=True)
        await message.answer("Оплата сейчас недоступна. Попробуй чуть позже.")
        return
    kb.adjust(1)
    await message.answer(
        f"{PREMIUM_TEXT}\n\nОплата звёздами Telegram. "
        f"Условия: {terms_url()}\nВопросы по оплате: /paysupport",
        parse_mode="HTML", reply_markup=kb.as_markup(), disable_web_page_preview=True,
    )


@router.pre_checkout_query()
async def pre_checkout(query: types.PreCheckoutQuery):
    parsed = billing.parse_payload(query.invoice_payload)
    plan = billing.plans().get(parsed[0]) if parsed else None
    ok = bool(
        plan and query.currency == "XTR" and query.total_amount == plan.stars
        and parsed[1] == query.from_user.id
    )
    await query.answer(ok=ok, error_message=None if ok else "Счёт устарел. Открой /premium ещё раз.")


@router.message(F.successful_payment)
async def successful_payment(message: types.Message):
    sp = message.successful_payment
    parsed = billing.parse_payload(sp.invoice_payload)
    if not parsed:
        logger.error("Unknown payment payload: %s", sp.invoice_payload)
        return
    plan = billing.plans()[parsed[0]]
    user_id = message.from_user.id

    profile = await asyncio.to_thread(storage.get_profile, user_id)
    if not profile:  # профиль удалили между счётом и оплатой
        await message.answer("Оплата получена ✨ Ответь на 4 вопроса, и я пришлю полный прогноз: /start")
        logger.error("Payment from user without profile: %s %s", user_id, sp.telegram_payment_charge_id)
        return

    now = utcnow_naive()
    current = datetime.fromisoformat(profile.premium_until) if profile.premium_until else None
    until = billing.new_premium_until(plan, now, current)
    fresh = await asyncio.to_thread(
        storage.record_payment, user_id, plan.code, sp.total_amount, sp.currency,
        sp.telegram_payment_charge_id, bool(sp.is_recurring), until,
    )
    if not fresh:
        return  # этот платёж уже учтён

    if sp.is_recurring and not sp.is_first_recurring:
        await message.answer(f"✨ Звездица+ продлена до <b>{until:%d.%m.%Y}</b>.", parse_mode="HTML")
        return

    await message.answer(
        f"✨ Спасибо! Звездица+ активна до <b>{until:%d.%m.%Y}</b>. Вот твой полный прогноз:",
        parse_mode="HTML",
    )
    profile = await asyncio.to_thread(storage.get_profile, user_id)
    await delivery.send_forecast(message.bot, profile)


@router.message(Command("paysupport"), StateFilter("*"))
async def cmd_paysupport(message: types.Message):
    await message.answer(
        "💬 <b>Вопросы по оплате</b>\n\n"
        f"Напиши на {support_contact()}: укажи дату оплаты и что случилось. "
        "Отвечаем в течение 2 рабочих дней.\n\n"
        "Если подписка не включилась после оплаты или прогноз не пришёл, вернём звёзды. "
        "Отменить автопродление можно в Telegram: Настройки → Мои звёзды → подписка Звездицы.\n\n"
        f"Условия: {terms_url()}",
        parse_mode="HTML", disable_web_page_preview=True,
    )
