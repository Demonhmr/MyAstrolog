# Выкладка Звездицы на VPS

С 18.11.2026 бот живёт на AdminVPS (Россия, `137.22.150.127`, вход `ssh volpen`) рядом с «Волпенем».
Код — `/opt/zvezditsa` (клон ветки `zvezditsa`), настройки — `/opt/zvezditsa/.env` (права 600).
Docker-проект называется `zvezditsa` (контейнер `zvezditsa_bot`), с n8n Волпеня не пересекается.
Бот работает через long polling: входящие порты и nginx ему не нужны.

Старый VPS `85.198.99.41` (Бегет) больше не используется.

## 0. Что подготовить заранее

1. **Новый бот** в @BotFather: `/newbot` → имя «Звездица», username `zvezditsa_bot`. Скопировать токен.
   Там же: `/setdescription`, `/setabouttext`, `/setuserpic` (золотая звезда). Для оплаты звёздами ничего подключать не нужно.
2. **Нейросеть.** С российского сервера OpenRouter, OpenAI и Anthropic отвечают 403 («Access denied by security policy»).
   Нужен OpenAI-совместимый адрес, доступный из России, — он задаётся в `LLM_BASE_URL`, код менять не нужно.
   Без ключа бот работает: текст берётся из справочника.
3. **Реквизиты** для документов: ФИО, статус (самозанятый / ИП), ИНН, почта — заменить жёлтые пометки в `landing/*.html`.

## 1. Бот

```bash
ssh volpen
cd /opt/zvezditsa
git pull
nano .env
#   BOT_TOKEN=<токен @zvezditsa_bot>
#   LLM_API_KEY=<ключ>   LLM_BASE_URL=<адрес>   LLM_MODEL=<модель>
#   SUPPORT_CONTACT=<почта поддержки>
#   PAYWALL_ENABLED=false               # включить, когда документы заполнены и опубликованы

docker compose up -d --build
docker compose logs -f --tail=30
# ждём строки: DB: /app/storage/zvezditsa.db · LLM: on (...) · Bot: @zvezditsa_bot
```

База лежит в docker-томе `zvezditsa_zvezditsa_data` и переживает пересборку. Резервная копия:

```bash
docker run --rm -v zvezditsa_zvezditsa_data:/d -v /root:/b alpine cp /d/zvezditsa.db /b/zvezditsa-$(date +%F).db
```

## 2. Проверка в Telegram

1. `/start` → «Начнём» → 4 вопроса → приходят 4 сообщения и карта.
2. «Подробно для знатоков» → планеты и баллы.
3. `/profile`, `/reminders`, `/delete` → работают.
4. С `PAYWALL_ENABLED=true`: `/premium` → кнопки «Месяц — 200 ★», «Год — 1700 ★».

## 3. Лендинг zvezditsa.ru

Статические файлы — папка `landing/`. На AdminVPS сайты заводятся в FASTPANEL (как volpen.ru):
сайт `zvezditsa.ru` (+www), файлы из `landing/` — в его папку, SSL Let's Encrypt — кнопкой в панели.
Чтобы работали адреса без `.html`, в `*.includes` сайта: `location / { try_files $uri $uri.html $uri/ =404; }`.
DNS: A-записи домена на `137.22.150.127`.
Ссылки на документы в боте по умолчанию: `https://zvezditsa.ru/privacy.html`, `/consent.html`, `/oferta.html`.
