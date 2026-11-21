"""
bot/handlers/diary.py — дневник в боте: «дата — запись».

  /diary                  последние записи и подсказка; следующее сообщение станет записью на сегодня
  /diary Текст            запись на сегодня
  /diary 20.11 Текст      запись на дату (ДД.ММ или ДД.ММ.ГГГГ)
Удаление — кнопкой под списком. Записи хранятся в той же таблице, что и дневник сайта
(owner «t:<Telegram ID>»), удаляются вместе с данными по /delete. Текст в журнал не пишется.
"""

import asyncio
import html
import re
import secrets
from datetime import date, datetime

import pytz
from aiogram import Router, types, F
from aiogram.filters import Command, CommandObject, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from core import storage, webstore
from core.texts import fmt_date

router = Router()

SHOW = 10
DATE_RE = re.compile(r"^\s*(\d{1,2})\.(\d{1,2})(?:\.(\d{4}))?\s*[—–:-]?\s*")


class Diary(StatesGroup):
    waiting = State()


def today_for(profile) -> date:
    tz = pytz.timezone(profile.cur_tz) if profile and profile.cur_tz else pytz.timezone("Europe/Moscow")
    return datetime.now(tz).date()


def parse_entry(text: str, today: date):
    """'20.11 Сдала проект' → (date(…, 11, 20), 'Сдала проект'). Ошибка — (None, причина)."""
    text = (text or "").strip()
    day = today
    m = DATE_RE.match(text)
    if m:
        d, mo, y = int(m.group(1)), int(m.group(2)), m.group(3)
        year = int(y) if y else today.year
        try:
            day = date(year, mo, d)
        except ValueError:
            return None, "Не получилось прочитать дату. Напиши так: 20.11 Текст записи"
        if not y and day > today:   # «28.12» в январе — это прошлый год
            day = date(year - 1, mo, d)
        text = text[m.end():].strip()
    if not text:
        return None, "Запись пустая. Напиши, что было: /diary 20.11 Сдала проект"
    if len(text) > webstore.DIARY_MAX_TEXT:
        return None, f"Слишком длинно: не больше {webstore.DIARY_MAX_TEXT} знаков."
    if day.year < 1900:
        return None, "Проверь год."
    return day, text


def _fmt_day(d: date, today: date) -> str:
    return fmt_date(d) + (f" {d.year}" if d.year != today.year else "")


async def _list(message: types.Message, user_id: int, profile):
    owner = webstore.tg_owner(user_id)
    entries = await asyncio.to_thread(webstore.diary_list, owner)
    today = today_for(profile)
    if not entries:
        await message.answer(
            "📔 <b>Дневник</b>\n\nЗдесь пока пусто. Записывай, что происходило, — потом удобно сверить "
            "с прогнозом месяца.\n\n"
            "Напиши запись следующим сообщением (она будет на сегодня) или так:\n"
            "<code>/diary 20.11 Сдала проект</code>",
            parse_mode="HTML",
        )
        return
    lines = [f"📔 <b>Дневник</b> · записей: {len(entries)}", ""]
    kb = InlineKeyboardBuilder()
    for e in entries[:SHOW]:
        d = date.fromisoformat(e["day"])
        lines.append(f"<b>{_fmt_day(d, today)}</b> — {html.escape(e['text'][:500])}")
        kb.button(text=f"🗑 {d:%d.%m}", callback_data=f"dd:{e['id']}")
    if len(entries) > SHOW:
        lines.append(f"\n…и ещё {len(entries) - SHOW}. Все записи — в приложении: https://zvezditsa.ru/app/")
    lines.append("\nНовая запись — следующим сообщением или <code>/diary 20.11 текст</code>")
    kb.adjust(5)
    await message.answer("\n".join(lines), parse_mode="HTML", reply_markup=kb.as_markup(),
                         disable_web_page_preview=True)


async def _save(message: types.Message, profile, text: str):
    today = today_for(profile)
    day, body = parse_entry(text, today)
    if day is None:
        await message.answer(body)   # причина ошибки
        return False
    owner = webstore.tg_owner(message.from_user.id)
    if await asyncio.to_thread(webstore.diary_count, owner) >= webstore.DIARY_MAX_ENTRIES:
        await message.answer("В дневнике слишком много записей — удали старые.")
        return False
    await asyncio.to_thread(webstore.diary_put, owner, secrets.token_urlsafe(9), day.isoformat(), body)
    await message.answer(f"📔 Записала на {_fmt_day(day, today)}. Все записи: /diary")
    return True


@router.message(Command("diary"), StateFilter("*"))
async def cmd_diary(message: types.Message, command: CommandObject, state: FSMContext):
    await state.clear()
    profile = await asyncio.to_thread(storage.get_profile, message.from_user.id)
    if not profile:
        await message.answer("Сначала ответь на 4 вопроса: /start")
        return
    if command.args:
        await _save(message, profile, command.args)
        return
    await _list(message, message.from_user.id, profile)
    await state.set_state(Diary.waiting)


@router.message(Diary.waiting, F.text, ~F.text.startswith("/"))
async def got_entry(message: types.Message, state: FSMContext):
    profile = await asyncio.to_thread(storage.get_profile, message.from_user.id)
    if not profile:
        await state.clear()
        return
    if await _save(message, profile, message.text):
        await state.clear()


@router.callback_query(F.data.startswith("dd:"))
async def cb_delete(callback: types.CallbackQuery):
    entry_id = callback.data[3:]
    ok = await asyncio.to_thread(webstore.diary_delete, webstore.tg_owner(callback.from_user.id), entry_id)
    await callback.answer("Удалено" if ok else "Уже удалено")
    if ok:
        profile = await asyncio.to_thread(storage.get_profile, callback.from_user.id)
        await _list(callback.message, callback.from_user.id, profile)
