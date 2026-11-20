# Звездица — приложение для Android

Нативная оболочка (Java, без сторонних библиотек) вокруг веб-приложения `START_URL` (сейчас `https://zvezditsa.ru/app/`).
Анкета, прогноз и карта — те же, что в браузере: обновили сайт — обновилось и приложение, пересобирать APK не нужно.
Основа взята из оболочки Волпеня (`~/projects/MK/android`), без оплаты и ссылок-приглашений.

## Что делает оболочка (`app/src/main/java/ru/zvezditsa/app/`)

| Что | Как |
|---|---|
| Приложение на весь экран | WebView грузит START_URL; полоски цвета неба под строкой состояния и навигацией (Android 15+ рисует под ними) |
| **Напоминание о новом личном месяце** | страница зовёт `ZVAndroid.setReminder("[мс, мс, мс]")` — начала трёх следующих месяцев; `Reminders` ставит будильник (`setAndAllowWhileIdle`, без точных будильников) на ближайший, `ReminderReceiver` показывает уведомление и ставит следующий; `BootReceiver` восстанавливает после перезагрузки и обновления. Разрешение на уведомления (Android 13+) спрашивается при первом планировании |
| «Поделиться картой» | `assets/bridge.js` подменяет `navigator.share` → `ZVAndroid.shareFile` → системное меню, файл отдаёт `ShareProvider` |
| Кнопка «Назад» | закрыть «для знатоков» → с другого месяца на текущий → настройки → прогноз → свернуть приложение |
| Политика, согласие | открываются окном поверх приложения («← Назад в Звездицу»), ссылка «← В приложение» на странице документа закрывает окно |
| Прочие внешние ссылки | в браузере |
| Нет интернета при первом запуске | экран «Нет связи со Звездицей» + «Повторить»; дальше приложение держит service worker сайта и сохранённый прогноз |
| Сертификаты | `res/xml/network_security_config.xml`: системные корни + `res/raw/extra_roots.pem` (новые корни из Android 14 и ISRG Root X1/X2 — без них Android 7.0 не открыл бы сертификат Let's Encrypt) |

Страница видит приложение по `ZVAndroid/1.0` в User-Agent, по `window.ZVAndroid` и по классу `in-android` у `<html>`.

## Сборка

Инструменты на этой машине: `~/android-tools` (JDK 17, Android SDK 36, Gradle 8.11.1).

```bash
. ~/android-tools/env.sh
cd ~/projects/zvezditsa/android
./gradlew assembleRelease bundleRelease   # APK для RuStore/сайта и AAB
```

Результат: `app/build/outputs/apk/release/app-release.apk`, `app/build/outputs/bundle/release/app-release.aab`.
Готовые копии — в `dist/` (в git не попадают): `zvezditsa-android-1.0.apk/.aab`.

Перед каждым новым релизом поднимите `versionCode` (+1) и `versionName` в `app/build.gradle`.

## Проверка без эмулятора

`node android/tools/bridge-test.js [адрес /app/]` — страница в Chromium с поддельным `window.ZVAndroid`,
настоящим `bridge.js` и `BACK_JS` из `MainActivity.java`: напоминания, «Поделиться», «Назад», «Стереть данные».

## Раздача APK с сайта

`/download/android` → 302 на `/download/zvezditsa-1.0.apk` (nginx, `deploy/nginx-zvezditsa.conf`).
Новая версия — новое имя файла (`scp dist/… volpen:/var/www/zvezditsa/site/download/zvezditsa-1.1.apk`) и правка редиректа.

## Подпись — ВАЖНО

- Ключ: `keystore/zvezditsa-release.jks`, пароли: `keystore.properties` (оба в `.gitignore`, репозиторий публичный — не коммитить).
- **Потеряете ключ — выпустить обновление этого приложения будет нельзя** (в RuStore и при установке APK с сайта). Сохраните оба файла в надёжное место вне этой машины.
- SHA-256 сертификата: `D4:98:29:E2:5C:9F:93:BD:75:17:78:0F:E2:DC:F8:3B:B7:47:02:59:EB:A9:AA:29:15:E0:2C:EA:68:2B:D9:CB`

## Перед публикацией

- `applicationId` = `ru.zvezditsa.app` — после первой публикации в сторе не меняется. Название под иконкой — `res/values/strings.xml`.
- С 1.1 (20.11.2026) приложение грузит https://zvezditsa.ru/app/. Старый адрес sslip (его грузила 1.0) отдаёт 301 на домен —
  держать редирект, пока все не обновятся.
