# 🔨 Руководство по воссозданию проекта с нуля

Этот документ описывает **полный процесс** создания MyAstro Bot — от пустой папки до работающего бота на VPS.

---

## Шаг 1 — Создание Telegram-бота

1. Открыть [`@BotFather`](https://t.me/BotFather) в Telegram
2. Команда `/newbot`
3. Ввести название (например: `Мой Астро`)
4. Ввести username (например: `MyAstro_v1_bot`)
5. Скопировать **BOT_TOKEN** — он понадобится в `.env`

---

## Шаг 2 — Структура проекта

Создать следующую структуру папок и файлов:

```
my_astro_bot/
├── bot/
│   ├── __init__.py            (пустой)
│   ├── main.py
│   └── handlers/
│       ├── __init__.py        (импорт registration)
│       └── registration.py
├── core/
│   ├── __init__.py            (пустой)
│   ├── astrology.py
│   ├── calculator.py
│   ├── chart_generator.py
│   ├── geocoder.py
│   └── interpretator.py
├── data/
│   ├── interpretations/
│   └── prompts/
├── .env
├── .env.example
└── requirements.txt
```

---

## Шаг 3 — Зависимости

**`requirements.txt`:**
```
aiogram==3.17.0
pyswisseph>=2.10.3
geopy>=2.4.0
timezonefinder>=6.2.0
pydantic==2.10.6
python-dotenv==1.0.1
pytz==2025.1
python-dateutil==2.9.0.post0
requests==2.32.3
matplotlib>=3.10
numpy
```

> [!WARNING]
> **НЕ добавлять `kerykeion`** — она требует `pyswisseph`, который не собирается на Windows Python 3.12 без MSVC Build Tools. Карта реализована через `matplotlib`.

**`.env.example`:**
```dotenv
BOT_TOKEN=your_token_here
```

---

## Шаг 4 — Реализация компонентов

### `bot/__init__.py`
```python
# пустой файл
```

### `bot/handlers/__init__.py`
```python
from bot.handlers import registration
```

### `bot/main.py` — Точка входа

```python
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
    async def __call__(self, handler, event, data):
        if isinstance(event, types.Update) and event.message:
            logging.info(f"UPDATE {event.update_id}: {event.message.from_user.id}: {event.message.text}")
        return await handler(event, data)

load_dotenv()
API_TOKEN = os.getenv("BOT_TOKEN")
logging.basicConfig(level=logging.DEBUG)

async def main():
    bot = Bot(token=API_TOKEN)
    dp = Dispatcher(storage=MemoryStorage())
    dp.update.outer_middleware(LoggingMiddleware())
    dp.include_router(registration.router)

    @dp.message(Command("start"), StateFilter("*"))
    async def cmd_start(message: types.Message):
        builder = InlineKeyboardBuilder()
        builder.button(text="Начинаем! 🚀", callback_data="start_forecast")
        await message.answer(
            "Привет! Я бот 🌌 <b>Мой Астро</b>.\n\n"
            "Я помогу тебе составить персональный астрологический прогноз на месяц (лунар).\n"
            "Для этого мне понадобятся твои данные рождения.",
            parse_mode="HTML", reply_markup=builder.as_markup()
        )

    @dp.callback_query(F.data == "start_forecast", StateFilter("*"))
    async def callback_start_forecast(callback: types.CallbackQuery, state):
        await callback.answer()
        await callback.message.answer("Как тебя зовут?")
        from bot.handlers.registration import RegistrationStates
        await state.set_state(RegistrationStates.waiting_for_name)

    @dp.message(Command("ping"), StateFilter("*"))
    async def cmd_ping(message: types.Message):
        await message.answer("pong!")

    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
```

---

### `core/geocoder.py` — Геокодинг

```python
from datetime import datetime
from geopy.geocoders import Nominatim
from timezonefinder import TimezoneFinder
import pytz

_VALID_PLACE_TYPES = {"city", "town", "village", "municipality", "hamlet", "suburb", "borough"}

def geocode_city(city_name: str) -> dict:
    geolocator = Nominatim(user_agent="my_astro_bot")
    location = geolocator.geocode(city_name, addressdetails=True, language="ru", exactly_one=True)

    if not location:
        raise ValueError(f"Город «{city_name}» не найден.")

    raw = location.raw
    importance = float(raw.get("importance", 0))
    address_type = raw.get("addresstype", "")
    osm_class = raw.get("class", "")
    is_valid = address_type in _VALID_PLACE_TYPES or osm_class == "place" or importance >= 0.4

    if not is_valid:
        raise ValueError(f"«{city_name}» не распознан как населённый пункт.")

    lat, lon = location.latitude, location.longitude
    tf = TimezoneFinder()
    tz_name = tf.timezone_at(lat=lat, lng=lon) or "UTC"
    tz = pytz.timezone(tz_name)
    utc_offset = datetime.now(tz).utcoffset().total_seconds() / 3600

    return {"lat": lat, "lon": lon, "timezone_name": tz_name,
            "utc_offset_hours": utc_offset, "display_name": location.address}
```

---

### `core/astrology.py` — Ключевые концепции

**Лунарный возврат** — момент, когда Луна возвращается в ту же эклиптическую долготу, в которой была в момент рождения. Происходит каждые ~27.3 дня.

Алгоритм поиска (итеративный):
1. Вычислить натальную долготу Луны
2. Начать поиск с текущего момента
3. Итерировать с шагом 0.5-1 дня пока `abs(current_lon - natal_lon) < threshold`
4. Уточнить бинарным поиском

**10 планет:** Sun, Moon, Mercury, Venus, Mars, Jupiter, Saturn, Uranus, Neptune, Pluto

**Ретроградность:** если `lon(+24h) < lon(now)` (с учётом wrap 360°) — планета ретроградна

**Дома (Whole Sign):** Дом 1 = знак ASC, Дом 2 = следующий знак и т.д.

**ASC:** вычисляется через Local Sidereal Time (LST) observer-а

---

### `core/chart_generator.py` — Ключевые концепции

Использует `matplotlib` с backend `Agg` (non-interactive, без display).

**КРИТИЧНО:** вызывать в `asyncio.run_in_executor`, иначе заблокирует event loop Telegram-бота!

```python
import asyncio
from functools import partial
from core.chart_generator import generate_chart_png

loop = asyncio.get_event_loop()
chart_png = await loop.run_in_executor(None, partial(generate_chart_png, ...))
```

**Aspect detection:**
```python
diff = abs(lon1 - lon2) % 360
if diff > 180: diff = 360 - diff
# Проверяем попадание в orb для каждого аспекта
```

---

### `bot/handlers/registration.py` — Требуемые импорты

```python
from aiogram import Router, types, F
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import BufferedInputFile    # ← обязательно top-level!
from datetime import datetime
import logging, os

from core.astrology import AstrologyEngine
from core.calculator import AstroCalculator
from core.interpretator import ReportInterpretator
from core.geocoder import geocode_city
```

> [!CAUTION]
> **Не делать `from aiogram.types import BufferedInputFile` внутри функции!** Python пометит имя как локальное для всей функции, и более ранние обращения к нему (в try-блоке) упадут с `UnboundLocalError`. Импортировать только на уровне модуля.

---

## Шаг 5 — Запуск локально (Windows)

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

# Создать .env с токеном
echo BOT_TOKEN=YOUR_TOKEN > .env

# Запустить
python -m bot.main
```

---

## Шаг 6 — Создание Docker-файлов

Смотри [`DOCKER_DEPLOY.md`](./DOCKER_DEPLOY.md) — там полный Dockerfile, docker-compose.yml и инструкция деплоя на VPS.

---

## Известные проблемы и решения

| Проблема | Причина | Решение |
|---------|---------|---------|
| `kerykeion` не устанавливается | `pyswisseph` требует MSVC (Windows) или gcc (Linux) | Использовать `matplotlib` для карт |
| Карта не отправляется (timeout) | matplotlib блокирует asyncio event loop | `loop.run_in_executor(None, ...)` |
| `UnboundLocalError: BufferedInputFile` | Inline-импорт внутри функции | Импортировать только на уровне модуля |
| Пустые символы планет на Linux | Нет DejaVu шрифтов | `apt install fonts-dejavu-core` |
| Медленный первый рендер | matplotlib строит кэш шрифтов | Смонтировать volume для `/root/.cache/matplotlib` |
| Геокодинг rate limit | Nominatim: 1 req/sec | Добавить `time.sleep(1)` между двумя вызовами geocode_city |

---

## Тест генерации карты

```python
from core.chart_generator import generate_chart_png

planets = [
    {"name": "Sun",  "sign": "Aries",  "house": 1, "lon_deg": 10.0,  "is_retro": False},
    {"name": "Moon", "sign": "Cancer", "house": 4, "lon_deg": 95.0,  "is_retro": False},
    # ... остальные планеты
]
points = {"ascendant": "Aries", "midheaven": "Capricorn"}
png = generate_chart_png(planets, points, "Тест", "15.05.1990", "12:00", "Москва")
open("test.png", "wb").write(png)
print("OK, bytes:", len(png))   # Ожидается > 100 000
```
