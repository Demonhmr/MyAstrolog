"""
bot/handlers/common.py — команды Звездицы и кнопки вне анкеты.
"""

import asyncio
import logging

from aiogram import Router, types, F
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot import delivery
from bot.handlers.registration import start_questionnaire
from core import storage

router = Router()

WELCOME_NEW = (
    "Привет! Я <b>Звездица</b> ✨ твой личный астролог.\n\n"
    "Я считаю твой <b>личный месяц</b>: он начинается не первого числа, а в день, "
    "когда Луна возвращается туда, где была при твоём рождении. И рассказываю, "
    "чего тебе в этот месяц захочется и чего захочет жизнь.\n\n"
    "Нужно ответить на 4 вопроса: дата, время и город рождения и где ты сейчас."
)

HELP_TEXT = (
    "ℹ️ <b>Что я умею</b>\n\n"
    "/forecast — прогноз на текущий личный месяц\n"
    "/profile — мои данные и их изменение\n"
    "/reminders — включить или выключить напоминания о новом месяце\n"
    "/premium — Звездица+\n"
    "/delete — удалить мои данные\n\n"
    "<b>Как это работает.</b> Я нахожу момент, когда Луна возвращается в точку твоего "
    "рождения (в астрологии это называют лунаром), строю карту неба на этот момент "
    "и считаю прогноз на ближайшие ~27 дней. Положения планет — по Swiss Ephemeris.\n\n"
    "Прогноз — повод посмотреть на свой месяц со стороны, а не предсказание судьбы."
)


def _start_kb(has_profile: bool):
    kb = InlineKeyboardBuilder()
    if has_profile:
        kb.button(text="🌙 Мой прогноз", callback_data="show_forecast")
        kb.button(text="✏️ Изменить данные", callback_data="start_forecast")
    else:
        kb.button(text="Начнём ✨", callback_data="start_forecast")
    kb.adjust(1)
    return kb.as_markup()


async def _profile(user_id: int):
    return await asyncio.to_thread(storage.get_profile, user_id)


@router.message(Command("start"), StateFilter("*"))
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    profile = await _profile(message.from_user.id)
    if profile:
        text = f"С возвращением, {profile.name}! ✨\nПоказать прогноз на твой текущий личный месяц?"
    else:
        text = WELCOME_NEW
    await message.answer(text, parse_mode="HTML", reply_markup=_start_kb(bool(profile)))


@router.message(Command("help"), StateFilter("*"))
async def cmd_help(message: types.Message):
    await message.answer(HELP_TEXT, parse_mode="HTML")


@router.message(Command("ping"), StateFilter("*"))
async def cmd_ping(message: types.Message):
    await message.answer("pong")


@router.callback_query(F.data == "start_forecast", StateFilter("*"))
async def cb_start(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await start_questionnaire(callback.message, state, callback.from_user)


async def _send_current(message: types.Message, user: types.User, state: FSMContext):
    await state.clear()
    profile = await _profile(user.id)
    if not profile:
        await start_questionnaire(message, state, user)
        return
    await message.answer("✨ Считаю…")
    try:
        await delivery.send_forecast(message.bot, profile)
    except Exception as e:
        logging.error("Forecast failed for user %s: %s", user.id, e, exc_info=True)
        await message.answer("Не получилось посчитать прогноз. Попробуй ещё раз чуть позже.")


@router.message(Command("forecast"), StateFilter("*"))
async def cmd_forecast(message: types.Message, state: FSMContext):
    await _send_current(message, message.from_user, state)


@router.callback_query(F.data == "show_forecast", StateFilter("*"))
async def cb_forecast(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await _send_current(callback.message, callback.from_user, state)


@router.callback_query(F.data == "expert")
async def cb_expert(callback: types.CallbackQuery):
    await callback.answer()
    profile = await _profile(callback.from_user.id)
    if not profile:
        await callback.message.answer("Сначала ответь на вопросы: /start")
        return
    await callback.message.answer(await delivery.expert_text(profile), parse_mode="HTML")


@router.message(Command("profile"), StateFilter("*"))
async def cmd_profile(message: types.Message, state: FSMContext):
    await state.clear()
    p = await _profile(message.from_user.id)
    if not p:
        await start_questionnaire(message, state, message.from_user)
        return
    time_line = p.birth_time if p.time_known else "неизвестно (считаю на 12:00)"
    kb = InlineKeyboardBuilder()
    kb.button(text="✏️ Изменить данные", callback_data="start_forecast")
    await message.answer(
        f"👤 <b>Твои данные</b>\n"
        f"Дата рождения: {p.birth_date}\n"
        f"Время рождения: {time_line}\n"
        f"Город рождения: {p.birth_city}\n"
        f"Где ты сейчас: {p.cur_city}\n"
        f"Напоминания: {'включены' if p.reminders_on else 'выключены'}",
        parse_mode="HTML", reply_markup=kb.as_markup(),
    )


@router.message(Command("reminders"), StateFilter("*"))
async def cmd_reminders(message: types.Message):
    p = await _profile(message.from_user.id)
    if not p:
        await message.answer("Сначала ответь на вопросы: /start")
        return
    await asyncio.to_thread(storage.set_reminders, p.user_id, not p.reminders_on)
    if p.reminders_on:
        await message.answer("Напоминания выключены. Включить снова: /reminders")
    else:
        await message.answer("Напоминания включены: пришлю прогноз, когда начнётся новый личный месяц.")


@router.message(Command("delete"), StateFilter("*"))
async def cmd_delete(message: types.Message):
    kb = InlineKeyboardBuilder()
    kb.button(text="Да, удалить", callback_data="delete_yes")
    kb.button(text="Отмена", callback_data="delete_no")
    await message.answer(
        "Удалить твои данные и все прогнозы? Это нельзя отменить.",
        reply_markup=kb.as_markup(),
    )


@router.callback_query(F.data == "delete_yes")
async def cb_delete_yes(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.clear()
    await asyncio.to_thread(storage.delete_user, callback.from_user.id)
    await callback.message.edit_text("Готово: твои данные и прогнозы удалены. Вернуться можно в любой момент: /start")


@router.callback_query(F.data == "delete_no")
async def cb_delete_no(callback: types.CallbackQuery):
    await callback.answer()
    await callback.message.edit_text("Хорошо, ничего не удаляю.")


@router.message(Command("premium"), StateFilter("*"))
async def cmd_premium(message: types.Message):
    p = await _profile(message.from_user.id)
    if p and p.is_premium():
        await message.answer(f"✨ Звездица+ активна до {p.premium_until[:10]}.")
        return
    tail = (
        "Оплата откроется совсем скоро."
        if delivery.paywall_enabled()
        else "Пока весь прогноз доступен бесплатно."
    )
    await message.answer(
        "✨ <b>Звездица+</b>: живой разбор месяца «как хочешь / как будет», "
        "начало и финал месяца, а скоро — советы по работе, деньгам и отношениям "
        f"и прогнозы для близких.\n{tail}",
        parse_mode="HTML",
    )
