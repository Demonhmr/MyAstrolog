# Выкладка Звездицы на VPS

VPS: `85.198.99.41` (Бегет, Россия), код в `/opt/MyAstrolog`. Ветка с новой версией — `zvezditsa`.

## 0. Что подготовить заранее

1. **Новый бот** в @BotFather: `/newbot` → имя «Звездица», username `zvezditsa_bot`. Скопировать токен.
   Там же: `/setdescription`, `/setabouttext`, `/setuserpic` (золотая звезда), а для оплаты звёздами ничего подключать не нужно.
2. **Ключ OpenRouter** (старый в `~/projects/OpenRouter.txt` просрочен): openrouter.ai → Keys → Create. Пополнить баланс на несколько долларов: один прогноз на Sonnet стоит около 2–3 ₽.
3. **Реквизиты** для документов: ФИО, статус (самозанятый / ИП), ИНН, почта — заменить жёлтые пометки в `landing/*.html`.

## 1. Бот

```bash
ssh root@85.198.99.41
cd /opt/MyAstrolog
docker compose down                    # остановить старого бота (контейнер myastro_bot)
git fetch && git checkout zvezditsa && git pull

# .env — в корне репозитория
[ -f my_astro_bot/.env ] && mv my_astro_bot/.env .env
cp -n .env.example .env
nano .env
#   BOT_TOKEN=<токен @zvezditsa_bot>
#   LLM_API_KEY=<ключ OpenRouter>
#   SUPPORT_CONTACT=<почта поддержки>
#   PAYWALL_ENABLED=false               # включить, когда документы заполнены и опубликованы

docker compose up -d --build
docker compose logs -f --tail=30
# ждём строки: DB: /app/storage/zvezditsa.db · LLM: on (...) · Bot: @zvezditsa_bot
```

База лежит в docker-томе `zvezditsa_data` и переживает пересборку. Резервная копия:

```bash
docker run --rm -v myastrolog_zvezditsa_data:/d -v /root:/b alpine cp /d/zvezditsa.db /b/zvezditsa-$(date +%F).db
```

## 2. Проверка в Telegram

1. `/start` → «Начнём» → 4 вопроса → приходят 4 сообщения и карта.
2. «Подробно для знатоков» → планеты и баллы.
3. `/profile`, `/reminders`, `/delete` → работают.
4. С `PAYWALL_ENABLED=true`: `/premium` → кнопки «Месяц — 200 ★», «Год — 1700 ★».

## 3. Лендинг zvezditsa.ru

Статические файлы — папка `landing/`. Пример для nginx на том же VPS:

```nginx
server {
    server_name zvezditsa.ru www.zvezditsa.ru;
    root /opt/MyAstrolog/landing;
    index index.html;
    location / { try_files $uri $uri.html $uri/ =404; }
}
```

Затем `certbot --nginx -d zvezditsa.ru -d www.zvezditsa.ru`. DNS: A-записи домена на `85.198.99.41`.
Ссылки на документы в боте по умолчанию: `https://zvezditsa.ru/privacy.html`, `/consent.html`, `/oferta.html`.
