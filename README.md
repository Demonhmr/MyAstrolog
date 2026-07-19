# 🌙 MyAstro Bot v3

Telegram-бот для составления персонального астрологического прогноза на месяц методом **Лунарного возврата**.

## Возможности

- 🪐 Расчёт позиций 10 планет на Swiss Ephemeris (pyswisseph)
- 🔄 Определение ретроградности по скорости планеты
- 🗺 PNG-карта колеса Лунарного возврата с аспектами (7 видов)
- 📊 Расчёт доминант по стихиям и крестам, синтетический знак и дом
- 📅 Динамика месяца: ASC/MC + дома их управителей
- 🤖 Генерация структурированного промта для ChatGPT / Claude

## Стек

| Компонент | Технология |
|-----------|-----------|
| Bot API | aiogram 3.x |
| Астрономия | pyswisseph (Swiss Ephemeris) |
| Геокодинг | Nominatim (OpenStreetMap) |
| Часовые пояса | TimezoneFinder (offline) |
| Карты | matplotlib (Agg, OO API) |
| Деплой | Docker + docker-compose |

## Запуск локально

```bash
# 1. Клонировать
git clone https://github.com/Demonhmr/MyAstrolog.git
cd MyAstrolog

# 2. Создать .env в корне репозитория
cp .env.example .env
# вставить BOT_TOKEN

# 3. Установить зависимости
cd my_astro_bot
pip install -r requirements.txt

# 4. Запустить (из папки my_astro_bot)
python -m bot.main
```

## Запуск через Docker

```bash
cd MyAstrolog
cp .env.example .env   # вставить BOT_TOKEN
docker compose up -d --build
```

## FSM поток данных

```
/start → Начинаем! 🚀
    ↓
Имя → Дата рождения → Время → Город рождения
    ↓
📊 Данные расчёта → 🗺 Карта PNG → 🌙 Прогноз → 📅 Динамика → 🤖 LLM-промт
    ↓
🔄 Начнём заново!
```

Карта строится по городу рождения (упрощённый поток — текущее местоположение не запрашивается). Бот выбирает лунарный цикл, **содержащий сегодняшний день**.

## Переменные окружения

| Переменная | Описание |
|-----------|---------|
| `BOT_TOKEN` | Токен бота от @BotFather |

## Тесты

```bash
cd my_astro_bot
pip install -r requirements-dev.txt
pytest
```

## Структура

```
MyAstrolog/
├── my_astro_bot/
│   ├── bot/
│   │   ├── main.py              # точка входа, /start, /help, /ping
│   │   └── handlers/
│   │       └── registration.py  # FSM, 4 состояния
│   ├── core/
│   │   ├── astrology.py         # AstrologyEngine (pyswisseph), Lunar Return, управители
│   │   ├── calculator.py        # AstroCalculator, доминанты, проверка суммы 26
│   │   ├── chart_generator.py   # matplotlib wheel chart (потокобезопасный)
│   │   ├── geocoder.py          # Nominatim + TimezoneFinder
│   │   └── interpretator.py     # ReportInterpretator
│   ├── data/
│   │   ├── interpretations/     # interpretations.json
│   │   └── prompts/             # шаблоны LLM-промта
│   ├── tests/                   # pytest
│   └── requirements.txt
├── Dockerfile
├── docker-compose.yml
└── .env.example                 # → скопировать в .env
```
