"""
delivery.py — отправка прогноза пользователю.

Порядок сообщений:
  1. Личный месяц: даты, роль месяца, главная задача
  2. Карта неба
  3. «Как хочешь / как будет» — живой текст (нейросеть) или справочник
  4. Как начнётся и чем закончится месяц
  + кнопка «Подробно для знатоков»
Платный доступ (PAYWALL_ENABLED=true): прошлый личный месяц — бесплатно, остальные —
по оплаченным месяцам (core/periods.py, owner «t:<Telegram ID>»). Закрытый месяц —
только даты и предложение тарифов.
"""

import asyncio
import json
import logging
import os
from typing import Optional

from aiogram import Bot
from aiogram.types import BufferedInputFile
from aiogram.utils.keyboard import InlineKeyboardBuilder

from core import llm, periods, storage, texts, webstore
from core.astrology import utcnow_naive
from core.chart_generator import generate_chart_png
from core.forecast import Forecast, build_forecast
from core.interpretator import ReportInterpretator, DATA_DIR

logger = logging.getLogger(__name__)

_interp = ReportInterpretator()
_interp_data = json.loads((DATA_DIR / "interpretations" / "interpretations.json").read_text("utf-8"))


def paywall_enabled() -> bool:
    return os.getenv("PAYWALL_ENABLED", "false").lower() in ("1", "true", "yes")


def month_access(profile: storage.Profile, index: int = 0):
    """→ (месяц, статус) для месяца с номером index (0 — текущий, −1 — прошлый)."""
    now = utcnow_naive()
    cal = periods.CycleCalendar(profile, now)
    cyc = cal.cycle(index)
    grants = webstore.grants_of(webstore.tg_owner(profile.user_id))
    return cyc, periods.status(cyc, grants, now, paywall_enabled())


def months_overview(profile: storage.Profile, ahead: int = 12) -> list:
    """Личные месяцы от прошлого до ahead-го с их статусами (для /months)."""
    now = utcnow_naive()
    cal = periods.CycleCalendar(profile, now)
    grants = webstore.grants_of(webstore.tg_owner(profile.user_id))
    last = max(ahead, periods.last_granted_index(cal, grants))
    return [(c, periods.status(c, grants, now, paywall_enabled())) for c in cal.cycles(-1, last)]


def brand_footer() -> str:
    username = os.getenv("BOT_USERNAME", "zvezditsa_bot").lstrip("@")
    return f"★ Звездица · @{username}"


def _chart_png(f: Forecast) -> bytes:
    return generate_chart_png(
        planets=f.planets,
        chart_points=f.points,
        name=f.name,
        birth_date=f.start_local.strftime("%d.%m.%Y"),
        birth_time=f.start_local.strftime("%H:%M"),
        city=f.city[:40],
        chart_title="Карта неба на начало личного месяца",
        footer=brand_footer(),
    )


async def get_story(profile: storage.Profile, f: Forecast) -> str:
    """Живой текст из архива, иначе от нейросети (с сохранением), иначе справочник."""
    cached = await asyncio.to_thread(storage.get_story, profile.user_id, f.cycle_start_utc)
    if cached:
        return cached
    prompt = _interp.generate_llm_prompt((f.el_s, f.cr_s), (f.el_h, f.cr_h), f.synth_sign, f.synth_house)
    # Персональные данные (имя, даты, города) в нейросеть не передаём:
    # промпт состоит только из описаний стихий, знаков и домов.
    story = await llm.write_story(prompt)
    if story:
        await asyncio.to_thread(
            storage.save_story, profile.user_id, f.cycle_start_utc, f.cycle_end_utc, story
        )
        return story
    return texts.render_story_fallback(f, _interp_data)


def expert_keyboard(index: int = 0):
    kb = InlineKeyboardBuilder()
    kb.button(text="🔭 Подробно для знатоков", callback_data=f"expert:{index}")
    return kb.as_markup()


def locked_keyboard():
    kb = InlineKeyboardBuilder()
    kb.button(text="✨ Открыть месяц", callback_data="premium")
    kb.button(text="🌘 Прошлый месяц — бесплатно", callback_data="previous")
    kb.adjust(1)
    return kb.as_markup()


async def send_forecast(bot: Bot, profile: storage.Profile, *, new_cycle: bool = False, index: int = 0):
    """Прогноз на месяц index; закрытый месяц — даты и тарифы. → Forecast или None (закрыт)."""
    chat_id = profile.chat_id
    cyc, st = await asyncio.to_thread(month_access, profile, index)
    if index == 0:
        # Следующее напоминание — в момент начала следующего личного месяца
        await asyncio.to_thread(storage.set_next_cycle, profile.user_id, cyc.end)

    if st not in periods.ACCESSIBLE:
        await bot.send_message(
            chat_id, texts.render_locked(cyc, profile.cur_tz, profile.cur_city, st, new_cycle=new_cycle),
            parse_mode="HTML", reply_markup=locked_keyboard(),
        )
        return None

    # середина месяца: расчёт попадает ровно в нужный месяц
    f = await asyncio.to_thread(build_forecast, profile, cyc.start + (cyc.end - cyc.start) / 2)
    await bot.send_message(chat_id, texts.render_summary(f, new_cycle=new_cycle, index=index), parse_mode="HTML")

    try:
        png = await asyncio.to_thread(_chart_png, f)
        await bot.send_photo(
            chat_id, BufferedInputFile(png, filename="zvezditsa_chart.png"),
            caption=texts.chart_caption(f), parse_mode="HTML",
        )
    except Exception as e:
        logger.warning("Chart generation failed: %s", e)

    await bot.send_chat_action(chat_id, "typing")
    story = await get_story(profile, f)
    await bot.send_message(chat_id, texts.render_story_header(f) + "\n" + story, parse_mode="HTML")
    await bot.send_message(
        chat_id, texts.render_dynamics(f, _interp_data),
        parse_mode="HTML", reply_markup=expert_keyboard(index),
    )
    return f


async def expert_text(profile: storage.Profile, index: int = 0) -> Optional[str]:
    cyc, st = await asyncio.to_thread(month_access, profile, index)
    if st not in periods.ACCESSIBLE:
        return None
    f = await asyncio.to_thread(build_forecast, profile, cyc.start + (cyc.end - cyc.start) / 2)
    return texts.render_expert(f)
