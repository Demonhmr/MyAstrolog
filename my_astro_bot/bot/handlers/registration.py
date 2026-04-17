"""
bot/handlers/registration.py — v2
FSM flow: name → birth_date → birth_time → birth_city → current_city → result.
All audit fixes applied: html.escape, lon_ecl rename, get_running_loop, html.escape.
"""

import asyncio
import html
import logging
import os
from datetime import datetime
from functools import partial
import pytz

from aiogram import Router, types, F
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import BufferedInputFile
from aiogram.utils.keyboard import InlineKeyboardBuilder

from core.astrology import AstrologyEngine
from core.calculator import AstroCalculator
from core.interpretator import ReportInterpretator
from core.chart_generator import generate_chart_png
from core.geocoder import geocode_city


router = Router()

SIGN_RU = {
    "Aries": "Овен ♈", "Taurus": "Телец ♉", "Gemini": "Близнецы ♊",
    "Cancer": "Рак ♋", "Leo": "Лев ♌", "Virgo": "Дева ♍",
    "Libra": "Весы ♎", "Scorpio": "Скорпион ♏", "Sagittarius": "Стрелец ♐",
    "Capricorn": "Козерог ♑", "Aquarius": "Водолей ♒", "Pisces": "Рыбы ♓",
}


# ── FSM States ────────────────────────────────────────────────────────────────

class RegistrationStates(StatesGroup):
    waiting_for_name       = State()
    waiting_for_birth_date = State()
    waiting_for_birth_time = State()
    waiting_for_birth_city = State()


# ── /forecast command (legacy entry) ─────────────────────────────────────────

@router.message(Command("forecast"), StateFilter("*"))
async def cmd_forecast(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("Как тебя зовут?")
    await state.set_state(RegistrationStates.waiting_for_name)


# ── Step 1: Name ──────────────────────────────────────────────────────────────

@router.message(RegistrationStates.waiting_for_name)
async def process_name(message: types.Message, state: FSMContext):
    safe_name = html.escape(message.text.strip()[:64])
    if not safe_name:
        await message.answer("Имя не может быть пустым. Введи своё имя:")
        return
    await state.update_data(name=safe_name)
    await message.answer("Введи дату рождения в формате <b>ДД.ММ.ГГГГ</b>\n(например: 15.01.1990)",
                         parse_mode="HTML")
    await state.set_state(RegistrationStates.waiting_for_birth_date)


# ── Step 2: Birth date ────────────────────────────────────────────────────────

@router.message(RegistrationStates.waiting_for_birth_date)
async def process_birth_date(message: types.Message, state: FSMContext):
    try:
        datetime.strptime(message.text.strip(), "%d.%m.%Y")
        await state.update_data(birth_date=message.text.strip())
        await message.answer(
            "Введи время рождения в формате <b>ЧЧ:ММ</b>\n"
            "(например: 14:30). Если неизвестно — введи <b>12:00</b>",
            parse_mode="HTML",
        )
        await state.set_state(RegistrationStates.waiting_for_birth_time)
    except ValueError:
        await message.answer("Неверный формат даты. Используй формат ДД.ММ.ГГГГ (например: 15.01.1990)")


# ── Step 3: Birth time ────────────────────────────────────────────────────────

@router.message(RegistrationStates.waiting_for_birth_time)
async def process_birth_time(message: types.Message, state: FSMContext):
    try:
        datetime.strptime(message.text.strip(), "%H:%M")
        await state.update_data(birth_time=message.text.strip())
        await message.answer(
            "Введи <b>город рождения</b> (например: Москва, London, Almaty)",
            parse_mode="HTML",
        )
        await state.set_state(RegistrationStates.waiting_for_birth_city)
    except ValueError:
        await message.answer("Неверный формат времени. Используй ЧЧ:ММ (например: 14:30)")


# ── Step 4: Birth city ────────────────────────────────────────────────────────

@router.message(RegistrationStates.waiting_for_birth_city)
async def process_birth_city(message: types.Message, state: FSMContext):
    city_input = message.text.strip()
    # Parse birth date/time to get context for UTC offset (DST correction)
    user_data = await state.get_data()
    try:
        d, m, y = map(int, user_data["birth_date"].split("."))
        hh, mm = map(int, user_data["birth_time"].split(":"))
        dt_context = datetime(y, m, d, hh, mm)
    except Exception:
        dt_context = None

    try:
        geo = geocode_city(city_input, date_context=dt_context)
    except ValueError as e:
        await message.answer(str(e))
        return  # Stay in state, let user retry

    await state.update_data(
        birth_city=city_input,
        birth_city_display=geo["display_name"][:60],
        birth_lat=geo["lat"],
        birth_lon=geo["lon"],
        birth_utc_offset=geo["utc_offset_hours"],
        birth_tz=geo["timezone_name"],
    )
    
    # Trigger calculation immediately using birth city
    await perform_calculation(message, state)


# ── Step 5: Current city → calculation ───────────────────────────────────────

async def perform_calculation(message: types.Message, state: FSMContext):
    user_data = await state.get_data()
    
    cur_lat        = user_data["birth_lat"]
    cur_lon        = user_data["birth_lon"]
    cur_utc_offset = user_data["birth_utc_offset"]
    cur_tz         = user_data["birth_tz"]
    city_display   = user_data["birth_city_display"]

    # Summary
    utc_sign = "+" if cur_utc_offset >= 0 else ""
    summary = (
        f"📋 <b>Данные для расчёта</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"👤 Имя: <b>{user_data['name']}</b>\n"
        f"📅 Дата рождения: <b>{user_data['birth_date']}</b>\n"
        f"🕐 Время рождения: <b>{user_data['birth_time']}</b>\n"
        f"📍 Город: <b>{html.escape(city_display)}</b>\n"
        f"🕰 Часовой пояс: <b>{cur_tz} (UTC{utc_sign}{cur_utc_offset:.1f})</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"⏳ Начинаю расчёт прогноза..."
    )
    await message.answer(summary, parse_mode="HTML")

    # 3. Compute
    engine = AstrologyEngine()
    calc   = AstroCalculator()
    interp = ReportInterpretator("data/interpretations/interpretations.json")

    try:
        d, m, y   = map(int, user_data["birth_date"].split("."))
        hh, mm    = map(int, user_data["birth_time"].split(":"))

        # Lunar Return: natal positions at birth_city, return moment at current_city
        lunar_data = engine.get_lunar_return(
            user_data["name"], y, m, d, hh, mm,
            cur_lat, cur_lon, cur_utc_offset,
        )
        chart = lunar_data["chart_data"]
        planets = engine.get_planets_data(chart)
        points  = engine.get_chart_points(chart)

        # Dates of the cycle
        start_dt = lunar_data["start_date"]
        end_dt   = lunar_data["end_date"]
        # Convert UTC to local city time for display
        local_tz = pytz.timezone(cur_tz)
        start_local = pytz.utc.localize(start_dt).astimezone(local_tz)
        end_local   = pytz.utc.localize(end_dt).astimezone(local_tz)

        # Scores & dominants
        sign_scores, house_scores = calc.calculate_scores(planets)
        el_s, cr_s = calc.get_dominants(sign_scores)
        el_h, cr_h = calc.get_dominants(house_scores)
        synth_s    = calc.get_synthetic_sign(el_s, cr_s)
        synth_h    = calc.get_synthetic_house(el_h, cr_h)

        # --- Message 1: calculation data ---
        planet_lines = []
        for p in planets:
            sign_ru = SIGN_RU.get(p["sign"], p["sign"])
            lon_ecl     = p.get("lon_deg", 0)
            deg_in_sign = lon_ecl % 30
            deg  = int(deg_in_sign)
            mins = int((deg_in_sign - deg) * 60)
            retro = " <i>℞</i>" if p.get("is_retro") else ""
            planet_lines.append(
                f"  • <b>{p['name']}</b>: {sign_ru} {deg}°{mins:02d}'{retro}, Дом <b>{p['house']}</b>"
            )
        planets_text = "\n".join(planet_lines)

        def _scores_line(d): return "  " + " | ".join(f"{k}: {v}" for k, v in sorted(d.items(), key=lambda x: -x[1]))

        synth_s_ru = SIGN_RU.get(synth_s, synth_s) if synth_s else "—"
        asc_ru     = SIGN_RU.get(points["ascendant"], points["ascendant"])
        mc_ru      = SIGN_RU.get(points["midheaven"],  points["midheaven"])

        calc_msg = (
            f"🔢 <b>Данные расчёта (Лунарный возврат)</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"📅 <b>Цикл:</b> {start_local.strftime('%d.%m.%Y %H:%M')} — {end_local.strftime('%d.%m.%Y %H:%M')}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n\n"
            f"🪐 <b>Позиции планет:</b>\n{planets_text}\n\n"
            f"📊 <b>Очки по знакам:</b>\n"
            f"  Стихии: {_scores_line(sign_scores['elements'])}\n"
            f"  Кресты: {_scores_line(sign_scores['crosses'])}\n\n"
            f"🏠 <b>Очки по домам:</b>\n"
            f"  Стихии: {_scores_line(house_scores['elements'])}\n"
            f"  Кресты: {_scores_line(house_scores['crosses'])}\n\n"
            f"🎯 <b>Доминанты:</b>\n"
            f"  Знаки → Стихия: <b>{el_s}</b> · Крест: <b>{cr_s}</b>\n"
            f"  Дома  → Стихия: <b>{el_h}</b> · Крест: <b>{cr_h}</b>\n\n"
            f"✨ <b>Синтетический знак:</b> {synth_s_ru}\n"
            f"🏠 <b>Синтетический дом:</b> {synth_h}\n\n"
            f"📍 <b>Асцендент месяца:</b> {asc_ru}\n"
            f"🎯 <b>MC (Середина неба):</b> {mc_ru}"
        )
        await message.answer(calc_msg, parse_mode="HTML")

        # --- Message 2: chart PNG ---
        try:
            await message.answer("⏳ Генерирую карту, подожди пару секунд…")
            loop      = asyncio.get_running_loop()
            chart_png = await loop.run_in_executor(
                None,
                partial(
                    generate_chart_png,
                    planets=planets,
                    chart_points=points,
                    name=user_data["name"],
                    birth_date=user_data["birth_date"],
                    birth_time=user_data["birth_time"],
                    city=city_display,
                    chart_title="Карта Лунарного возврата",
                ),
            )
            chart_file = BufferedInputFile(chart_png, filename="lunar_return_chart.png")
            await message.answer_photo(
                chart_file,
                caption=(
                    f"🔯 <b>Колесо Лунарного возврата</b>\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"ASC: <b>{asc_ru}</b> · MC: <b>{mc_ru}</b>\n"
                    f"Синт. знак: <b>{synth_s_ru}</b> · Дом: <b>{synth_h}</b>"
                ),
                parse_mode="HTML",
            )
        except Exception as chart_err:
            logging.warning(f"Chart generation failed: {chart_err}")

        # --- Message 3: forecast report ---
        dynamics = {"start_sign": points["ascendant"], "end_sign": points["midheaven"]}
        report   = interp.generate_report((el_s, cr_s), (el_h, cr_h), synth_s, synth_h, dynamics)
        await message.answer(report, parse_mode="HTML")

        # --- Message 4: dynamics ---
        dynamics_report = interp.generate_dynamics_report(dynamics)
        await message.answer(dynamics_report, parse_mode="HTML")

        # --- Message 5: LLM prompt file ---
        llm_prompt  = interp.generate_llm_prompt((el_s, cr_s), (el_h, cr_h), synth_s, synth_h)
        prompt_file = BufferedInputFile(llm_prompt.encode("utf-8"), filename="forecast_prompt.txt")
        await message.answer_document(
            prompt_file,
            caption=(
                "🤖 <b>Промт для нейросети</b>\n"
                "Отправь этот файл (или его текст) в ChatGPT/Claude "
                "для получения литературного прогноза."
            ),
            parse_mode="HTML",
        )

        await state.clear()

        # Final button: restart
        builder = InlineKeyboardBuilder()
        builder.button(text="🔄 Начнём заново!", callback_data="start_forecast")
        await message.answer(
            "✅ <b>Прогноз готов!</b>\nХочешь сделать расчёт для другого человека?",
            parse_mode="HTML",
            reply_markup=builder.as_markup(),
        )

    except Exception as e:
        logging.error(f"Calculation error: {e}", exc_info=True)
        await message.answer(
            f"⚠️ Произошла ошибка при расчёте:\n<code>{html.escape(str(e))}</code>",
            parse_mode="HTML",
        )
        await state.clear()
