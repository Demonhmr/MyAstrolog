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

docker compose --profile bot up -d --build bot     # без --profile bot бот не стартует
docker compose --profile bot logs -f --tail=30 bot
# ждём строки: DB: /app/storage/zvezditsa.db · LLM: on (...) · Bot: @zvezditsa_bot
```

Если после `LLM: ...` строка `Bot: @zvezditsa_bot` не появляется — бот не достучался до Telegram.
С AdminVPS адрес `api.telegram.org` из DNS (149.154.166.110) заблокирован, поэтому в `docker-compose.yml`
у бота закреплён рабочий 149.154.167.220 (`extra_hosts`). Если перестанет отвечать и он — подобрать другой:
`curl --resolve api.telegram.org:443:<ip> https://api.telegram.org/bot0:x/getMe` → 401 значит адрес живой.

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

Статические файлы — папка `landing/` → `/var/www/zvezditsa/site/` (вне FASTPANEL, свой nginx-конфиг
`deploy/nginx-zvezditsa.conf`; адреса без `.html` работают через try_files). Домен на reg.ru, A-записи @ и www → `137.22.150.127`,
сертификат certbot (webroot `/var/www/zvezditsa/acme`, имя `zvezditsa.ru`, продлевается сам).
Документы бота — `landing/bot/` → https://zvezditsa.ru/bot/privacy, `/bot/consent`, `/bot/oferta` (ссылки по умолчанию в коде,
переопределяются PRIVACY_URL / CONSENT_URL / TERMS_URL). Документы сайта и приложения — `landing/privacy.html`, `consent.html`.
Выкладка документов: `scp -r landing/bot volpen:/var/www/zvezditsa/site/` (и `landing/privacy.html` при правке).
Меняется смысл согласия бота — поднять `CONSENT_VERSION` в `bot/handlers/registration.py` (и версию на странице согласия):
пользователи со старой версией примут его заново при /start или /forecast.
