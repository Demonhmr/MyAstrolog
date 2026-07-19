# 🐳 Docker & VPS Деплой — MyAstro Bot

## Обзор

Бот работает в **одном контейнере** (long polling, без webhook), не требует внешнего домена или SSL. Достаточно любого Linux VPS с Docker.

---

## Структура Docker-файлов

```
my_astro_bot/
├── Dockerfile
├── docker-compose.yml
├── .env                 ← вставить BOT_TOKEN
└── .dockerignore
```

---

## Dockerfile

```dockerfile
# syntax=docker/dockerfile:1
FROM python:3.12-slim

# --- Системные зависимости для matplotlib и Unicode-шрифтов ---
RUN apt-get update && apt-get install -y --no-install-recommends \
        fonts-dejavu-core \
        libglib2.0-0 \
        libsm6 \
        libxext6 \
        libxrender1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# --- Зависимости Python ---
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# --- Исходный код ---
COPY . .

# Matplotlib non-interactive backend (уже прописан в chart_generator.py, но дублируем)
ENV MPLBACKEND=Agg

CMD ["python", "-m", "bot.main"]
```

> [!IMPORTANT]
> `fonts-dejavu-core` обязателен — без него matplotlib не может отрисовать Unicode-символы планет (☉☽♂ и т.д.) и упадёт с ошибкой пустого глифа.

---

## docker-compose.yml

```yaml
services:
  bot:
    build: .
    container_name: myastro_bot
    restart: unless-stopped
    env_file:
      - .env
    volumes:
      # Кэш шрифтов matplotlib — чтобы не пересобирать при каждом рестарте
      - matplotlib_cache:/root/.cache/matplotlib
    logging:
      driver: "json-file"
      options:
        max-size: "10m"
        max-file: "3"

volumes:
  matplotlib_cache:
```

---

## .env.example

```dotenv
BOT_TOKEN=1234567890:ABCDefGhIJKlmNOpQRSTUVWxyz
```

---

## .dockerignore

```
.venv/
__pycache__/
*.pyc
*.pyo
.env
test_chart*.png
_debug.json
*.md
.git/
```

---

## Деплой на VPS (пошагово)

> [!IMPORTANT]
> **VPS для этого проекта:** `85.198.99.41` · `root` · пароль: см. у владельца
> **Репо:** https://github.com/Demonhmr/MyAstrolog

### 1. Подключись к серверу

```bash
# Через PowerShell / терминал Windows:
ssh root@85.198.99.41
# Введи пароль вручную
```

Или открой **PuTTY**: Host `85.198.99.41`, Port `22`.

---

### 2. Установи Docker (если не установлен)

```bash
# Проверь:
docker --version 2>/dev/null || echo "НЕТ — нужно установить"

# Если нет:
curl -fsSL https://get.docker.com | sh
systemctl enable docker
systemctl start docker
```

---

### 3. Клонируй репо

```bash
cd /opt
git clone https://github.com/Demonhmr/MyAstrolog.git
cd MyAstrolog
```

---

### 4. Создай `.env` с токеном боta

```bash
cat > my_astro_bot/.env << 'EOF'
BOT_TOKEN=ВАШ_ТОКЕН_ЗДЕСЬ
EOF
```

> [!CAUTION]
> Не коммить `.env` в Git — он уже добавлен в `.gitignore`.

---

### 5. Запусти через Docker Compose

```bash
cd /opt/MyAstrolog
docker compose up -d --build
```

Первая сборка занимает ~2-5 минут (скачивает Python, устанавливает зависимости).

---

### 6. Проверь что работает

```bash
# Логи в реальном времени
docker compose logs -f --tail=30

# Ожидаемый результат:
# [INFO] aiogram.dispatcher: Run polling for bot @MyAstro_v1_bot
```

---

### Управление контейнером

```bash
docker compose ps              # статус
docker compose logs -f         # логи
docker compose restart         # перезапуск
docker compose down            # остановить

# Обновить код:
git pull
docker compose up -d --build
```

---

## Управление контейнером

```bash
# Остановить
docker compose down

# Перезапустить
docker compose restart bot

# Обновить код и пересобрать
git pull
docker compose up -d --build

# Просмотр последних 100 строк лога
docker compose logs --tail=100 bot
```

---

## Рекомендуемые параметры VPS

| Параметр | Минимум | Рекомендуется |
|----------|---------|---------------|
| CPU | 1 vCPU | 2 vCPU |
| RAM | 512 МБ | 1 ГБ |
| Диск | 5 ГБ | 10 ГБ |
| ОС | Ubuntu 22.04 | Ubuntu 22.04 LTS |

> [!NOTE]
> matplotlib при первом рендере кэширует шрифты — это занимает ~30-60 сек при первом запросе к боту. При следующих запусках (кэш в volume) — 2-3 сек.

---

## Production-улучшения (опционально)

### Заменить MemoryStorage на Redis

FSM-состояния сейчас хранятся в памяти и сбрасываются при перезапуске. Для продакшна:

```yaml
# docker-compose.yml — добавить:
services:
  redis:
    image: redis:7-alpine
    restart: unless-stopped
    volumes:
      - redis_data:/data

  bot:
    # ...
    environment:
      - REDIS_URL=redis://redis:6379
    depends_on:
      - redis

volumes:
  redis_data:
```

```python
# bot/main.py — заменить:
from aiogram.fsm.storage.redis import RedisStorage
import os

redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
storage = RedisStorage.from_url(redis_url)
dp = Dispatcher(storage=storage)
```

```
# requirements.txt — добавить:
aiogram[redis]
```

### Мониторинг (опционально)

```yaml
# Добавить healthcheck в docker-compose.yml:
  bot:
    healthcheck:
      test: ["CMD", "python", "-c", "import asyncio; asyncio.run(__import__('aiogram').Bot(token=__import__('os').getenv('BOT_TOKEN')).get_me())"]
      interval: 60s
      timeout: 10s
      retries: 3
```
