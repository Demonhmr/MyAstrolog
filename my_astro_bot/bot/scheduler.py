"""
scheduler.py — напоминания о начале нового личного месяца.

Раз в CHECK_EVERY секунд ищет пользователей, у которых наступил момент
next_cycle_utc, и присылает им прогноз на новый месяц. Новый месяц берётся
с запасом GRACE после расчётного момента: старт и конец цикла считаются
независимо и могут расходиться на секунды.
"""

import asyncio
import logging
from datetime import timedelta

from aiogram import Bot
from aiogram.exceptions import TelegramForbiddenError, TelegramBadRequest

from bot import delivery
from core import storage
from core.astrology import utcnow_naive

logger = logging.getLogger(__name__)

CHECK_EVERY = 300                 # секунд между проверками
GRACE = timedelta(minutes=10)
PAUSE_BETWEEN_USERS = 1.0         # бережём лимиты Telegram и нейросети


async def run_once(bot: Bot) -> int:
    """Одна проверка. Возвращает число отправленных прогнозов."""
    due = await asyncio.to_thread(storage.due_profiles, utcnow_naive() - GRACE)
    sent = 0
    for profile in due:
        try:
            f = await delivery.send_forecast(bot, profile, new_cycle=True)
            sent += 1
            logger.info("Reminder sent: user=%s new cycle %s", profile.user_id, f.cycle_start_utc)
        except TelegramForbiddenError:
            # пользователь заблокировал бота — больше не пишем
            await asyncio.to_thread(storage.set_reminders, profile.user_id, False)
            logger.info("User %s blocked the bot, reminders off", profile.user_id)
        except TelegramBadRequest as e:
            if "chat not found" in str(e).lower():
                await asyncio.to_thread(storage.set_reminders, profile.user_id, False)
                logger.warning("Chat of %s not found, reminders off", profile.user_id)
            else:
                logger.error("Reminder to %s rejected: %s", profile.user_id, e)
                await asyncio.to_thread(
                    storage.set_next_cycle, profile.user_id, utcnow_naive() + timedelta(days=1)
                )
        except Exception as e:
            # не даём одному сбою зациклить рассылку: переносим на сутки
            logger.error("Reminder failed for %s: %s", profile.user_id, e, exc_info=True)
            await asyncio.to_thread(
                storage.set_next_cycle, profile.user_id, utcnow_naive() + timedelta(days=1)
            )
        await asyncio.sleep(PAUSE_BETWEEN_USERS)
    return sent


async def reminder_loop(bot: Bot):
    while True:
        try:
            await run_once(bot)
        except Exception as e:
            logger.error("Reminder loop error: %s", e, exc_info=True)
        await asyncio.sleep(CHECK_EVERY)
