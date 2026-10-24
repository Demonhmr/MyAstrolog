"""
delivery.py — отправка прогноза пользователю.

Порядок сообщений:
  1. Личный месяц: даты, роль месяца, главная задача
  2. Карта неба
  3. «Как хочешь / как будет» — живой текст (нейросеть) или справочник
  4. Как начнётся и чем закончится месяц
  + кнопка «Подробно для знатоков»
Без подписки при включённом платном доступе — только 1, 2 и приглашение.
"""

import asyncio
import json
import logging
import os

from aiogram import Bot
from aiogram.types import BufferedInputFile
from aiogram.utils.keyboard import InlineKeyboardBuilder

from core import llm, storage, texts
from core.chart_generator import generate_chart_png
from core.forecast import Forecast, build_forecast
from core.interpretator import ReportInterpretator, DATA_DIR

logger = logging.getLogger(__name__)

_interp = ReportInterpretator()
_interp_data = json.loads((DATA_DIR / "interpretations" / "interpretations.json").read_text("utf-8"))


def paywall_enabled() -> bool:
    return os.getenv("PAYWALL_ENABLED", "false").lower() in ("1", "true", "yes")


def has_full_access(profile: storage.Profile) -> bool:
    return not paywall_enabled() or profile.is_premium()


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


def expert_keyboard():
    kb = InlineKeyboardBuilder()
    kb.button(text="🔭 Подробно для знатоков", callback_data="expert")
    return kb.as_markup()


async def send_forecast(bot: Bot, profile: storage.Profile, *, new_cycle: bool = False) -> Forecast:
    chat_id = profile.chat_id
    f = await asyncio.to_thread(build_forecast, profile)

    await bot.send_message(chat_id, texts.render_summary(f, new_cycle=new_cycle), parse_mode="HTML")

    try:
        png = await asyncio.to_thread(_chart_png, f)
        await bot.send_photo(
            chat_id, BufferedInputFile(png, filename="zvezditsa_chart.png"),
            caption=texts.chart_caption(f), parse_mode="HTML",
        )
    except Exception as e:
        logger.warning("Chart generation failed: %s", e)

    if has_full_access(profile):
        await bot.send_chat_action(chat_id, "typing")
        story = await get_story(profile, f)
        await bot.send_message(chat_id, texts.render_story_header(f) + "\n" + story, parse_mode="HTML")
        await bot.send_message(
            chat_id, texts.render_dynamics(f, _interp_data),
            parse_mode="HTML", reply_markup=expert_keyboard(),
        )
    else:
        await bot.send_message(chat_id, texts.render_teaser(), parse_mode="HTML")

    # Следующее напоминание — в момент начала следующего личного месяца
    await asyncio.to_thread(storage.set_next_cycle, profile.user_id, f.cycle_end_utc)
    return f


async def expert_text(profile: storage.Profile) -> str:
    f = await asyncio.to_thread(build_forecast, profile)
    return texts.render_expert(f)
