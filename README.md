# 🌙 MyAstro Bot v2

Telegram-бот для составления персонального астрологического прогноза на месяц методом **Лунарного возврата**.

## Возможности

- 🪐 Расчёт позиций 10 планет (включая Уран, Нептун, Плутон)
- 🔄 Определение ретроградности через сравнение позиций за 24 часа
- 🗺 PNG-карта колеса Лунарного возврата с аспектами (6 видов)
- 📊 Расчёт доминант по стихиям и крестам
- 🤖 Генерация структурированного промта для ChatGPT / Claude
- 📍 Два города: рождения + текущий (для точного расчёта)

## Стек

| Компонент | Технология |
|-----------|-----------|
| Bot API | aiogram 3.x |
| Астрономия | ephem |
| Геокодинг | Nominatim (OpenStreetMap) |
| Часовые пояса | TimezoneFinder (offline) |
| Карты | matplotlib (Agg) |
| Деплой | Docker + docker-compose |

## Запуск локально

```bash
# 1. Клонировать
git clone https://github.com/DemonHMR/MyAstrologV2.git
cd MyAstrologV2/my_astro_bot

# 2. Создать .env
cp .env.example .env
# вставить BOT_TOKEN

# 3. Установить зависимости
pip install -r requirements.txt

# 4. Запустить
python -m bot.main
```

## Запуск через Docker

```bash
cd MyAstrologV2
docker-compose up -d
```

## FSM поток данных

```
/start → Начинаем! 🚀
    ↓
Имя → Дата рождения → Время → Город рождения → Текущий город
    ↓
📊 Данные расчёта → 🗺 Карта PNG → 🌙 Прогноз → 📅 Динамика → 🤖 LLM-промт
    ↓
🔄 Начнём заново!
```

## Переменные окружения

| Переменная | Описание |
|-----------|---------|
| `BOT_TOKEN` | Токен бота от @BotFather |

## Структура

```
my_astro_bot/
├── bot/
│   ├── main.py              # точка входа, /start, /help, /ping
│   └── handlers/
│       └── registration.py  # FSM, 5 состояний
├── core/
│   ├── astrology.py         # AstrologyEngine, Lunar Return
│   ├── calculator.py        # AstroCalculator, доминанты
│   ├── chart_generator.py   # matplotlib wheel chart
│   ├── geocoder.py          # Nominatim + TimezoneFinder
│   └── interpretator.py     # ReportInterpretator
├── data/
│   ├── interpretations/     # interpretations.json
│   └── prompts/             # шаблоны LLM-промта
├── Dockerfile
├── docker-compose.yml
└── requirements.txt
```
