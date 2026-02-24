"""
bot/main.py — v2
Entry point: Bot, Dispatcher, middleware, /start, /help, start_forecast callback.
"""

import asyncio
import logging
import os
from dotenv import load_dotenv

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, StateFilter
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram import BaseMiddleware
from typing import Callable, Dict, Any, Awaitable

from bot.handlers import registration


class LoggingMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[types.TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: types.TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        if isinstance(event, types.Update) and event.message:
            logging.info(
                f"UPDATE {event.update_id}: "
                f"user={event.message.from_user.id} text={event.message.text!r:.80}"
            )
        return await handler(event, data)


load_dotenv()

API_TOKEN = os.getenv("BOT_TOKEN")
if not API_TOKEN:
    raise RuntimeError(
        "BOT_TOKEN не задан! Создайте файл .env и добавьте: BOT_TOKEN=ваш_токен"
    )

# Logging: INFO for production, suppress verbose matplotlib output
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logging.getLogger("matplotlib").setLevel(logging.WARNING)
logging.getLogger("geopy").setLevel(logging.WARNING)


WELCOME_TEXT = (
    "Привет! Я бот 🌌 <b>Мой Астро v2</b>.\n\n"
    "Я помогу составить персональный астрологический прогноз на месяц — "
    "на основе метода <b>Лунарного возврата</b>.\n\n"
    "Для расчёта понадобятся:\n"
    "  • Имя\n"
    "  • Дата и время рождения\n"
    "  • Город рождения\n"
    "  • Текущий город\n"
)

HELP_TEXT = (
    "ℹ️ <b>Справка — Мой Астро v2</b>\n\n"
    "<b>Команды:</b>\n"
    "  /start — начать сначала\n"
    "  /help  — эта справка\n"
    "  /ping  — проверка соединения\n\n"
    "<b>Как работает:</b>\n"
    "Бот находит момент Лунарного возврата (когда Луна возвращается "
    "в знак и градус вашего рождения) и строит карту для этого момента. "
    "Это основа прогноза на следующие ~27 дней.\n\n"
    "<b>Карта включает:</b> 10 планет, 12 домов, 6 видов аспектов, ретроградность.\n\n"
    "<b>Данные не сохраняются</b> — каждый сеанс независим."
)


async def main():
    bot = Bot(token=API_TOKEN)
    dp  = Dispatcher(storage=MemoryStorage())

    dp.update.outer_middleware(LoggingMiddleware())
    dp.include_router(registration.router)

    @dp.message(Command("start"), StateFilter("*"))
    async def cmd_start(message: types.Message, state):
        await state.clear()
        builder = InlineKeyboardBuilder()
        builder.button(text="Начинаем! 🚀", callback_data="start_forecast")
        await message.answer(WELCOME_TEXT, parse_mode="HTML", reply_markup=builder.as_markup())

    @dp.message(Command("help"), StateFilter("*"))
    async def cmd_help(message: types.Message):
        await message.answer(HELP_TEXT, parse_mode="HTML")

    @dp.message(Command("ping"), StateFilter("*"))
    async def cmd_ping(message: types.Message):
        await message.answer("pong! 🏓")

    @dp.callback_query(F.data == "start_forecast", StateFilter("*"))
    async def callback_start_forecast(callback: types.CallbackQuery, state):
        await callback.answer()
        await state.clear()
        from bot.handlers.registration import RegistrationStates
        await callback.message.answer("Как тебя зовут?")
        await state.set_state(RegistrationStates.waiting_for_name)

    logging.info("Deleting webhook...")
    await bot.delete_webhook(drop_pending_updates=True)
    logging.info("Starting polling...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
