"""
bot/main.py — запуск Звездицы: база, роутеры, напоминания, long polling.
"""

import asyncio
import logging
import os
from typing import Any, Awaitable, Callable, Dict

from dotenv import load_dotenv
from aiogram import BaseMiddleware, Bot, Dispatcher, types
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand

load_dotenv()

from bot.handlers import common, payments, registration  # noqa: E402  (после load_dotenv)
from bot.scheduler import reminder_loop  # noqa: E402
from core import llm, storage  # noqa: E402


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


COMMANDS = [
    BotCommand(command="forecast", description="Прогноз на мой личный месяц"),
    BotCommand(command="profile", description="Мои данные"),
    BotCommand(command="reminders", description="Напоминания о новом месяце"),
    BotCommand(command="premium", description="Звездица+"),
    BotCommand(command="help", description="Что умеет Звездица"),
    BotCommand(command="paysupport", description="Вопросы по оплате"),
    BotCommand(command="delete", description="Удалить мои данные"),
]


async def main():
    token = os.getenv("BOT_TOKEN")
    if not token:
        raise RuntimeError("BOT_TOKEN не задан! Создайте файл .env и добавьте: BOT_TOKEN=ваш_токен")

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    logging.getLogger("matplotlib").setLevel(logging.WARNING)
    logging.getLogger("geopy").setLevel(logging.WARNING)

    storage.init_db()
    logging.info("DB: %s", storage.db_path())
    logging.info("LLM: %s", "on (" + os.getenv("LLM_MODEL", llm.DEFAULT_MODEL) + ")"
                 if llm.is_configured() else "off — тексты из справочника")

    bot = Bot(token=token)
    me = await bot.get_me()
    os.environ.setdefault("BOT_USERNAME", me.username or "")
    logging.info("Bot: @%s", me.username)

    dp = Dispatcher(storage=MemoryStorage())
    dp.update.outer_middleware(LoggingMiddleware())
    dp.include_router(payments.router)
    dp.include_router(common.router)
    dp.include_router(registration.router)

    await bot.set_my_commands(COMMANDS)
    await bot.delete_webhook(drop_pending_updates=True)

    reminders = asyncio.create_task(reminder_loop(bot))
    try:
        await dp.start_polling(bot)
    finally:
        reminders.cancel()


if __name__ == "__main__":
    asyncio.run(main())
