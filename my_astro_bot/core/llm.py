"""
llm.py — живой текст прогноза через OpenAI-совместимый API (по умолчанию OpenRouter).

Настройки (.env):
  LLM_API_KEY   — ключ; без него бот работает на текстах из справочника
  LLM_MODEL     — модель, по умолчанию anthropic/claude-sonnet-5.5
  LLM_BASE_URL  — по умолчанию https://openrouter.ai/api/v1
"""

import html
import logging
import os
import re
from typing import Optional

import aiohttp

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "anthropic/claude-sonnet-5.5"
DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"
MAX_CHARS = 3500  # с запасом до лимита Telegram в 4096 символов

SYSTEM_PROMPT = (
    "Ты — Звездица, тёплый и умный персональный астролог в Telegram. "
    "Пиши по-русски, обращайся на «ты», живо и конкретно, с бытовыми примерами "
    "и лёгким юмором, как в примерах ниже. Не используй астрологические термины "
    "(стихии, кресты, дома, знаки, планеты) — переводи их в жизненные ситуации. "
    "Не обещай событий как неизбежных, не давай медицинских, юридических и "
    "финансовых рекомендаций. Если пол человека неизвестен, пиши нейтрально. "
    "Не используй markdown, звёздочки и решётки: только обычный текст, абзацы "
    "и списки через «—». Строго следуй структуре из задания. "
    f"Объём — не больше {MAX_CHARS - 500} символов."
)

# Заголовки разделов из шаблона — выделяем их жирным в Telegram
_HEADINGS = (
    "Как ты себя чувствуешь:", "Ты хочешь:", "А жизнь тебе:",
    "Что происходит с тобой:", "Чему учат обстоятельства:",
)


def is_configured() -> bool:
    return bool(os.getenv("LLM_API_KEY"))


def to_telegram_html(text: str) -> str:
    """Экранирует ответ модели и выделяет заголовки разделов."""
    t = text.strip()
    t = re.sub(r"\*\*(.*?)\*\*", r"\1", t)          # на случай markdown
    t = re.sub(r"^#+\s*", "", t, flags=re.MULTILINE)
    t = html.escape(t, quote=False)
    for h in _HEADINGS:
        t = t.replace(h, f"<b>{h}</b>")
    t = re.sub(r"^(Внутри — .*)$", r"<b>\1</b>", t, count=1, flags=re.MULTILINE)
    t = re.sub(r"^(Снаружи — .*)$", r"<b>\1</b>", t, count=1, flags=re.MULTILINE)
    t = re.sub(r"\n{3,}", "\n\n", t)
    if len(t) > MAX_CHARS:
        cut = t[:MAX_CHARS]
        t = cut[: cut.rfind("\n")] if "\n" in cut else cut
    return t


async def write_story(user_prompt: str, name: str = "") -> Optional[str]:
    """
    Возвращает готовый Telegram-HTML текст или None, если нейросеть
    не настроена или не ответила (тогда бот берёт текст из справочника).
    """
    key = os.getenv("LLM_API_KEY")
    if not key:
        return None
    base = os.getenv("LLM_BASE_URL", DEFAULT_BASE_URL).rstrip("/")
    model = os.getenv("LLM_MODEL", DEFAULT_MODEL)

    who = f"Человека зовут {name}. " if name else ""
    payload = {
        "model": model,
        "temperature": 0.8,
        "max_tokens": 2000,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": who + user_prompt},
        ],
    }
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "X-Title": "Zvezditsa",
    }
    try:
        timeout = aiohttp.ClientTimeout(total=90)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(f"{base}/chat/completions", json=payload, headers=headers) as resp:
                data = await resp.json(content_type=None)
                if resp.status != 200:
                    logger.error("LLM HTTP %s: %s", resp.status, str(data)[:300])
                    return None
        text = data["choices"][0]["message"]["content"]
        if not text or len(text.strip()) < 200:
            logger.error("LLM returned too short text: %r", text)
            return None
        return to_telegram_html(text)
    except Exception as e:  # сеть, таймаут, неожиданный формат ответа
        logger.error("LLM request failed: %s", e)
        return None
