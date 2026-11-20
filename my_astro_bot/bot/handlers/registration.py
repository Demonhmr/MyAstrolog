"""
bot/handlers/registration.py — анкета Звездицы.

Четыре вопроса: дата рождения → время (или «не знаю») → город рождения →
где ты сейчас (или «там же»). Имя берётся из Telegram. После анкеты профиль
сохраняется и сразу отправляется прогноз.
"""

import asyncio
import html
import logging
import os
from datetime import datetime
from functools import partial

from aiogram import Router, types, F
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot import delivery
from core import storage
from core.astrology import utcnow_naive
from core.geocoder import geocode_city

router = Router()

UNKNOWN_TIME = "12:00"


class Questionnaire(StatesGroup):
    consent = State()
    birth_date = State()
    birth_time = State()
    birth_city = State()
    current_city = State()


def display_name(user: types.User) -> str:
    name = (user.first_name or "").strip() or "друг"
    return html.escape(name[:40], quote=False)


# Редакция согласия бота. Меняется — пользователи с другой версией принимают его заново (/start, /forecast).
CONSENT_VERSION = "bot-v2-2026-11-21"


def legal_links() -> str:
    privacy = os.getenv("PRIVACY_URL", "https://zvezditsa.ru/bot/privacy")
    consent = os.getenv("CONSENT_URL", "https://zvezditsa.ru/bot/consent")
    return f'<a href="{privacy}">политике</a> и <a href="{consent}">согласии на обработку данных</a>'


def needs_consent(profile) -> bool:
    return profile.consent_version != CONSENT_VERSION


def consent_kb(yes_data: str):
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Согласен(на)", callback_data=yes_data)
    kb.button(text="Не сейчас", callback_data="consent_no")
    kb.adjust(1)
    return kb.as_markup()


CONSENT_TEXT = (
    "Чтобы посчитать прогноз, мне нужны дата, время и город рождения и город, где ты сейчас. "
    "Я храню их на сервере в России, а прогнозы присылаю через Telegram (его серверы — за границей). "
    "Подробно — в {links}.\n\n"
    "Удалить данные и отозвать согласие можно в любой момент: /delete"
)


async def start_questionnaire(message: types.Message, state: FSMContext, user: types.User):
    await state.clear()
    await state.update_data(name=display_name(user))
    await message.answer(
        CONSENT_TEXT.format(links=legal_links()),
        parse_mode="HTML", disable_web_page_preview=True, reply_markup=consent_kb("consent_yes"),
    )
    await state.set_state(Questionnaire.consent)


async def ask_consent_again(message: types.Message):
    """Профиль есть, но согласие принято в старой редакции."""
    await message.answer(
        "Я обновила документы о данных. " + CONSENT_TEXT.format(links=legal_links()),
        parse_mode="HTML", disable_web_page_preview=True, reply_markup=consent_kb("consent_renew"),
    )


@router.callback_query(F.data == "consent_yes", StateFilter("*"))
async def cb_consent_yes(callback: types.CallbackQuery, state: FSMContext):
    # без фильтра по состоянию: после перезапуска бота состояние анкеты теряется, а кнопка остаётся
    await callback.answer()
    await callback.message.edit_reply_markup(reply_markup=None)
    await state.clear()
    await state.update_data(
        name=display_name(callback.from_user),
        consent_at=utcnow_naive().isoformat(timespec="seconds"),
    )
    await callback.message.answer(
        "Когда ты родился(ась)? Напиши дату в формате <b>ДД.ММ.ГГГГ</b>, например 15.01.1990",
        parse_mode="HTML",
    )
    await state.set_state(Questionnaire.birth_date)


@router.callback_query(F.data == "consent_renew", StateFilter("*"))
async def cb_consent_renew(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await callback.message.edit_reply_markup(reply_markup=None)
    if not await asyncio.to_thread(storage.get_profile, callback.from_user.id):
        await start_questionnaire(callback.message, state, callback.from_user)
        return
    await asyncio.to_thread(
        storage.set_consent, callback.from_user.id, CONSENT_VERSION,
        utcnow_naive().isoformat(timespec="seconds"),
    )
    await callback.message.answer("Спасибо! Твой прогноз: /forecast")


@router.callback_query(F.data == "consent_no", StateFilter("*"))
async def cb_consent_no(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await callback.message.edit_reply_markup(reply_markup=None)
    await state.clear()
    await callback.message.answer(
        "Хорошо. Без согласия я не смогу посчитать прогноз. Передумаешь — /start"
    )


@router.message(Questionnaire.consent)
async def consent_pending(message: types.Message):
    await message.answer("Сначала нажми «Согласен(на)» выше или «Не сейчас».")


# ── 1. Дата рождения ──────────────────────────────────────────────────────────

@router.message(Questionnaire.birth_date)
async def got_birth_date(message: types.Message, state: FSMContext):
    raw = (message.text or "").strip()
    try:
        dt = datetime.strptime(raw, "%d.%m.%Y")
    except ValueError:
        await message.answer("Не получилось прочитать дату. Напиши так: 15.01.1990")
        return
    if not (1900 <= dt.year <= datetime.now().year):
        await message.answer("Проверь год рождения, пожалуйста.")
        return
    await state.update_data(birth_date=raw)

    kb = InlineKeyboardBuilder()
    kb.button(text="Не знаю время", callback_data="time_unknown")
    await message.answer(
        "Во сколько? Напиши время в формате <b>ЧЧ:ММ</b>, например 14:30.\n"
        "<i>Время сильно влияет на точность: оно определяет, когда начнётся твой месяц.</i>",
        parse_mode="HTML", reply_markup=kb.as_markup(),
    )
    await state.set_state(Questionnaire.birth_time)


# ── 2. Время рождения ─────────────────────────────────────────────────────────

async def _ask_birth_city(message: types.Message, state: FSMContext):
    await message.answer("В каком городе ты родился(ась)? Например: Москва, Алматы, London")
    await state.set_state(Questionnaire.birth_city)


@router.message(Questionnaire.birth_time)
async def got_birth_time(message: types.Message, state: FSMContext):
    raw = (message.text or "").strip().replace(".", ":")
    try:
        datetime.strptime(raw, "%H:%M")
    except ValueError:
        await message.answer("Напиши время так: 14:30. Или нажми «Не знаю время».")
        return
    await state.update_data(birth_time=raw, time_known=True)
    await _ask_birth_city(message, state)


@router.callback_query(F.data == "time_unknown", Questionnaire.birth_time)
async def time_unknown(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.update_data(birth_time=UNKNOWN_TIME, time_known=False)
    await callback.message.answer(
        "Хорошо, посчитаю на полдень. Прогноз будет приблизительным: "
        "начало месяца может сдвинуться на несколько часов. "
        "Узнаешь точное время — обнови данные командой /profile."
    )
    await _ask_birth_city(callback.message, state)


# ── 3. Город рождения ─────────────────────────────────────────────────────────

async def _geocode(message: types.Message, city: str, date_context):
    """Возвращает результат геокодера или None (пользователю уже ответили)."""
    await message.answer("🔍 Ищу город…")
    try:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, partial(geocode_city, city, date_context=date_context))
    except ValueError as e:
        await message.answer(str(e))
    except Exception as e:
        logging.error("Geocoding failed for %r: %s", city, e, exc_info=True)
        await message.answer("Сервис городов сейчас не отвечает. Попробуй отправить название ещё раз через минуту.")
    return None


@router.message(Questionnaire.birth_city)
async def got_birth_city(message: types.Message, state: FSMContext):
    city = (message.text or "").strip()[:80]
    if not city:
        return
    data = await state.get_data()
    d, m, y = map(int, data["birth_date"].split("."))
    hh, mm = map(int, data["birth_time"].split(":"))
    geo = await _geocode(message, city, datetime(y, m, d, hh, mm))
    if not geo:
        return  # остаёмся на этом шаге
    await state.update_data(
        birth_city=geo["display_name"][:80], birth_lat=geo["lat"], birth_lon=geo["lon"],
        birth_utc_offset=geo["utc_offset_hours"], birth_tz=geo["timezone_name"],
    )

    kb = InlineKeyboardBuilder()
    kb.button(text="В городе рождения", callback_data="same_city")
    await message.answer(
        "И последнее: где ты сейчас живёшь?\n"
        "<i>Личный месяц считается на то место, где ты находишься.</i>",
        parse_mode="HTML", reply_markup=kb.as_markup(),
    )
    await state.set_state(Questionnaire.current_city)


# ── 4. Где ты сейчас ──────────────────────────────────────────────────────────

@router.message(Questionnaire.current_city)
async def got_current_city(message: types.Message, state: FSMContext):
    city = (message.text or "").strip()[:80]
    if not city:
        return
    geo = await _geocode(message, city, None)
    if not geo:
        return
    await state.update_data(
        cur_city=geo["display_name"][:80], cur_lat=geo["lat"], cur_lon=geo["lon"],
        cur_tz=geo["timezone_name"],
    )
    await finish(message, state, message.from_user)


@router.callback_query(F.data == "same_city", Questionnaire.current_city)
async def same_city(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    data = await state.get_data()
    await state.update_data(
        cur_city=data["birth_city"], cur_lat=data["birth_lat"], cur_lon=data["birth_lon"],
        cur_tz=data["birth_tz"],
    )
    await finish(callback.message, state, callback.from_user)


# ── Сохранение и прогноз ──────────────────────────────────────────────────────

async def finish(message: types.Message, state: FSMContext, user: types.User):
    data = await state.get_data()
    await state.clear()
    old = await asyncio.to_thread(storage.get_profile, user.id)
    profile = storage.Profile(
        user_id=user.id,
        chat_id=message.chat.id,
        name=data["name"],
        birth_date=data["birth_date"],
        birth_time=data["birth_time"],
        time_known=data.get("time_known", True),
        birth_city=data["birth_city"],
        birth_lat=data["birth_lat"],
        birth_lon=data["birth_lon"],
        birth_utc_offset=data["birth_utc_offset"],
        birth_tz=data["birth_tz"],
        cur_city=data["cur_city"],
        cur_lat=data["cur_lat"],
        cur_lon=data["cur_lon"],
        cur_tz=data["cur_tz"],
        reminders_on=old.reminders_on if old else True,
        premium_until=old.premium_until if old else None,
        consent_version=CONSENT_VERSION,
        consent_at=data.get("consent_at") or utcnow_naive().isoformat(timespec="seconds"),
    )
    await asyncio.to_thread(storage.save_profile, profile)
    await message.answer("✨ Запомнила. Считаю твой личный месяц…")
    try:
        await delivery.send_forecast(message.bot, profile)
    except Exception as e:
        logging.error("Forecast failed for user %s: %s", user.id, e, exc_info=True)
        await message.answer("Не получилось посчитать прогноз. Попробуй ещё раз: /forecast")
        return
    await message.answer(
        "Когда начнётся твой следующий личный месяц, я пришлю новый прогноз сама. "
        "Отключить напоминания: /reminders"
    )
