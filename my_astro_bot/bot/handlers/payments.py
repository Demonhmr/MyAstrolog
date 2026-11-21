"""
bot/handlers/payments.py — тарифы Звездицы за звёзды Telegram.

/premium — тарифы и кнопки оплаты (если включён PAYWALL_ENABLED), /months — какие месяцы
открыты, /previous — прошлый месяц бесплатно. pre_checkout проверяет счёт, successful_payment
записывает платёж и выдаёт личные месяцы (core/periods.py). /paysupport обязателен по правилам Telegram.
Оплата разовая, без автопродления.
"""

import asyncio
import logging
import os
from datetime import datetime

from aiogram import Router, types, F
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import LabeledPrice
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot import delivery
from core import billing, periods, plans, storage, texts, webstore
from core.astrology import utcnow_naive

router = Router()
logger = logging.getLogger(__name__)

PREMIUM_TEXT = (
    "✨ <b>Тарифы Звездицы</b>\n\n"
    "Прогноз считается на <b>личный месяц</b> (~27 дней). Прошлый личный месяц — бесплатно: /previous\n\n"
    "{lines}\n\n"
    "Оплаченные месяцы остаются у тебя навсегда. Пакет начинается с текущего месяца, "
    "уже оплаченные не сгорают — пакет продлевается за них. Без автопродления."
)


def support_contact() -> str:
    return os.getenv("SUPPORT_CONTACT", "[почта поддержки]")


def terms_url() -> str:
    return os.getenv("TERMS_URL", "https://zvezditsa.ru/bot/oferta")


def plan_lines() -> str:
    out = []
    for p in plans.plans().values():
        out.append(f"• <b>{p.title}</b> — {p.stars} ⭐\n  <i>{plans.describe(p)}</i>")
    return "\n".join(out)


async def _invoice_link(bot, plan: plans.Plan, user_id: int) -> str:
    return await bot.create_invoice_link(
        title=f"Звездица · {plan.short}"[:32],
        description=plans.describe(plan)[:255],
        payload=billing.make_payload(plan.code, user_id),
        currency="XTR",
        prices=[LabeledPrice(label=plan.short, amount=plan.stars)],
    )


async def show_premium(message: types.Message, user_id: int):
    if not delivery.paywall_enabled():
        await message.answer("Сейчас все прогнозы Звездицы открыты бесплатно ✨ /forecast")
        return
    p = await asyncio.to_thread(storage.get_profile, user_id)
    if not p:
        await message.answer("Сначала ответь на 4 вопроса, чтобы я посчитала твои месяцы: /start")
        return
    kb = InlineKeyboardBuilder()
    try:
        for plan in plans.plans().values():
            link = await _invoice_link(message.bot, plan, user_id)
            kb.button(text=f"{plan.short} — {plan.stars} ⭐", url=link)
    except Exception as e:
        logger.error("Invoice link failed: %s", e, exc_info=True)
        await message.answer("Оплата сейчас недоступна. Попробуй чуть позже.")
        return
    kb.adjust(1)
    await message.answer(
        PREMIUM_TEXT.format(lines=plan_lines()) +
        f"\n\nОплата звёздами Telegram. Условия: {terms_url()}\n"
        "Мои месяцы: /months · Вопросы по оплате: /paysupport",
        parse_mode="HTML", reply_markup=kb.as_markup(), disable_web_page_preview=True,
    )


@router.message(Command("premium"), StateFilter("*"))
async def cmd_premium(message: types.Message):
    await show_premium(message, message.from_user.id)


@router.callback_query(F.data == "premium", StateFilter("*"))
async def cb_premium(callback: types.CallbackQuery):
    await callback.answer()
    await show_premium(callback.message, callback.from_user.id)


@router.message(Command("months"), StateFilter("*"))
async def cmd_months(message: types.Message):
    p = await asyncio.to_thread(storage.get_profile, message.from_user.id)
    if not p:
        await message.answer("Сначала ответь на 4 вопроса: /start")
        return
    items = await asyncio.to_thread(delivery.months_overview, p)
    await message.answer(texts.render_months(items, p.cur_tz), parse_mode="HTML")


async def _send_previous(message: types.Message, user_id: int, state: FSMContext):
    await state.clear()
    p = await asyncio.to_thread(storage.get_profile, user_id)
    if not p:
        await message.answer("Сначала ответь на 4 вопроса: /start")
        return
    await message.answer("✨ Считаю прошлый месяц…")
    try:
        await delivery.send_forecast(message.bot, p, index=-1)
    except Exception as e:
        logger.error("Previous forecast failed for %s: %s", user_id, e, exc_info=True)
        await message.answer("Не получилось посчитать прогноз. Попробуй ещё раз чуть позже.")


@router.message(Command("previous"), StateFilter("*"))
async def cmd_previous(message: types.Message, state: FSMContext):
    await _send_previous(message, message.from_user.id, state)


@router.callback_query(F.data == "previous", StateFilter("*"))
async def cb_previous(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await _send_previous(callback.message, callback.from_user.id, state)


@router.pre_checkout_query()
async def pre_checkout(query: types.PreCheckoutQuery):
    parsed = billing.parse_payload(query.invoice_payload)
    plan = plans.get(parsed[0]) if parsed else None
    profile = await asyncio.to_thread(storage.get_profile, query.from_user.id) if plan else None
    ok = bool(
        plan and query.currency == "XTR" and query.total_amount == plan.stars
        and parsed[1] == query.from_user.id and profile is not None
    )
    await query.answer(ok=ok, error_message=None if ok else "Счёт устарел. Открой /premium ещё раз.")


def grant_for_stars(profile: storage.Profile, plan: plans.Plan, charge_id: str):
    """Функция выдачи месяцев для record_stars_payment (внутри её транзакции)."""
    def run(conn):
        owner = webstore.tg_owner(profile.user_id)
        rows = conn.execute("SELECT cycle_start, preview FROM grants WHERE owner = ?", (owner,)).fetchall()
        grants = [periods.Grant(datetime.fromisoformat(r["cycle_start"]), bool(r["preview"])) for r in rows]
        cal = periods.CycleCalendar(profile, utcnow_naive())
        cycles = periods.cycles_to_grant(cal, grants, plan.months)
        return webstore.add_grants(conn, owner, cycles, plan.code, f"tg:{charge_id}", plan.preview)
    return run


@router.message(F.successful_payment)
async def successful_payment(message: types.Message):
    sp = message.successful_payment
    parsed = billing.parse_payload(sp.invoice_payload)
    if not parsed:
        logger.error("Unknown payment payload: %s", sp.invoice_payload)
        return
    plan = plans.get(parsed[0])
    user_id = message.from_user.id

    profile = await asyncio.to_thread(storage.get_profile, user_id)
    if not profile:  # профиль удалили между счётом и оплатой — звёзды вернём по /paysupport
        await message.answer(
            "Оплата получена, но твоих данных уже нет. Напиши в поддержку — вернём звёзды: /paysupport")
        logger.error("Payment from user without profile: %s %s", user_id, sp.telegram_payment_charge_id)
        return

    n = await asyncio.to_thread(
        storage.record_stars_payment, user_id, plan.code, sp.total_amount, sp.currency,
        sp.telegram_payment_charge_id, grant_for_stars(profile, plan, sp.telegram_payment_charge_id),
    )
    if n is None:
        return  # этот платёж уже учтён

    word = "месяц" if n == 1 else ("месяца" if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14 else "месяцев")
    await message.answer(f"✨ Спасибо! Открыто {n} {word}. Список: /months")
    cyc, st = await asyncio.to_thread(delivery.month_access, profile, 0)
    if st == periods.PAID:
        await delivery.send_forecast(message.bot, profile)


@router.message(Command("paysupport"), StateFilter("*"))
async def cmd_paysupport(message: types.Message):
    await message.answer(
        "💬 <b>Вопросы по оплате</b>\n\n"
        f"Напиши на {support_contact()}: укажи дату оплаты и что случилось. "
        "Отвечаем в течение 2 рабочих дней.\n\n"
        "Если месяцы не открылись после оплаты или прогноз не пришёл, вернём звёзды. "
        "Автопродления нет: каждая оплата разовая.\n\n"
        f"Условия: {terms_url()}",
        parse_mode="HTML", disable_web_page_preview=True,
    )
