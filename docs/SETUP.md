# MyAstro Bot — подробная инструкция по запуску

Три сценария: **продакшен на VPS** (Docker), **локальный запуск для разработки** и **обновление уже работающего бота**.

---

## 0. Что понадобится

| Сценарий | Требования |
|----------|-----------|
| Продакшен | Любой Linux VPS с Docker + Docker Compose (публичный IP/домен НЕ нужен — бот работает через long polling) |
| Разработка | Python 3.11+ (нужен компилятор C для pyswisseph: `sudo apt install gcc g++ python3-dev`) |

### Токен бота (нужен в любом сценарии)

1. Открой [@BotFather](https://t.me/BotFather) в Telegram.
2. `/newbot` → придумай имя и username бота.
3. Скопируй выданный **BOT_TOKEN** (вида `1234567890:AA...`).

> Все команды ниже выполняются в терминале той машины, где будет работать бот
> (для VPS — сначала `ssh root@<IP-сервера>`), из папки проекта, если не указано иное.

---

## 1. Продакшен: VPS + Docker (рекомендуется)

```bash
# 1. Получить код
git clone https://github.com/Demonhmr/MyAstrolog.git
cd MyAstrolog
git checkout modernization        # пока изменения не смержены в main

# 2. Создать .env В КОРНЕ репозитория (не в my_astro_bot!)
cp .env.example .env
nano .env                         # вставить BOT_TOKEN=твой_токен

# 3. Собрать и запустить
docker compose up -d --build
```

Проверка:

```bash
docker compose ps                 # контейнер myastro_bot — Up
docker compose logs -f bot        # в логе: "Starting polling..."
```

Затем в Telegram: открой своего бота → `/start` → пройди цепочку
(имя → дата → время → город) → должны прийти данные расчёта, PNG-карта,
прогноз, динамика и файл с промтом. Команда `/ping` должна ответить «pong! 🏓».

Полезные команды:

```bash
docker compose logs -f bot        # логи в реальном времени
docker compose restart bot        # перезапуск
docker compose down               # остановить
docker compose up -d --build      # пересобрать после изменения кода
```

> Первая генерация карты после пересборки может занять 30–60 секунд —
> matplotlib строит кэш шрифтов. Кэш хранится в Docker-томе, поэтому
> последующие рестарты быстрые.

---

## 2. Обновление уже работающего бота

```bash
cd MyAstrolog                     # папка проекта на VPS (например /opt/MyAstrolog)
git pull                          # или git checkout modernization
docker compose up -d --build
docker compose logs -f bot        # убедиться что запустился
```

⚠️ После этого обновления `.env` ожидается **в корне репозитория** (рядом с
`docker-compose.yml`), а не в `my_astro_bot/`. Если файл лежал по-старому:
`mv my_astro_bot/.env .env`

⚠️ Не запускай две копии бота с одним токеном (например, локально и на VPS
одновременно) — Telegram отдаёт обновления только одному подключению,
и боты будут «отбирать» их друг у друга с ошибками Conflict.

---

## 3. Локальный запуск (разработка, без Docker)

```bash
git clone https://github.com/Demonhmr/MyAstrolog.git
cd MyAstrolog
git checkout modernization

cp .env.example .env              # вставить BOT_TOKEN (лучше отдельный тестовый бот!)

cd my_astro_bot
python3 -m venv .venv
source .venv/bin/activate         # Windows: .venv\Scripts\activate
pip install -r requirements.txt

python -m bot.main                # запуск из папки my_astro_bot
```

Остановка — `Ctrl+C`. Файл `.env` в корне репозитория подхватится автоматически
(python-dotenv ищет его вверх по дереву папок).

---

## 4. Тесты

```bash
cd my_astro_bot
pip install -r requirements-dev.txt
pytest                            # 19 тестов, сети не требуют
```

---

## 5. Типовые проблемы

| Симптом | Причина и решение |
|---------|-------------------|
| `RuntimeError: BOT_TOKEN не задан` | Нет `.env` или он не в корне репозитория: `cp .env.example .env` и вставь токен |
| Бот молчит в Telegram | Смотри `docker compose logs -f bot`. Ошибка `Unauthorized` — неверный токен; `Conflict` — запущена вторая копия бота с тем же токеном |
| «Город не найден», хотя город существует | Попробуй другое написание (русское/английское). Если «сервис временно недоступен» — Nominatim перегружен, подожди минуту |
| Карта генерируется очень долго | Нормально только для первого запроса после пересборки (кэш шрифтов). Если каждый раз — проверь, что том `matplotlib_cache` на месте: `docker volume ls` |
| `pip install` падает на pyswisseph | Нужен компилятор: `sudo apt install gcc g++ python3-dev` (в Docker уже включено) |
| Символы планет ☉☽ на карте — квадратики | Локально: установи шрифты `sudo apt install fonts-dejavu-core` (в Docker уже включено) |
