# syntax=docker/dockerfile:1
FROM python:3.12-slim

# --- Системные зависимости ---
# fonts-dejavu-core: Unicode-символы планет (☉☽♂♃ и т.д.) для matplotlib
# libglib2.0-0, libsm6, libxext6, libxrender1: зависимости matplotlib на Linux
RUN apt-get update && apt-get install -y --no-install-recommends \
    fonts-dejavu-core \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# --- Python зависимости (отдельный слой для кэширования) ---
COPY my_astro_bot/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# --- Исходный код ---
COPY my_astro_bot/ .

# Matplotlib non-interactive backend
ENV MPLBACKEND=Agg

# Запуск бота
CMD ["python", "-m", "bot.main"]
