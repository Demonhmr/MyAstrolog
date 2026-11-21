// Сквозная проверка дневника, входа по почте, тарифов и оплаты (Robokassa подменена).
// Нужен сервер с WEB_PAYWALL=test, TEST_LOGIN_CODE и тестовыми паролями Robokassa:
//   node web/tools/e2e-paid.js <адрес приложения> <папка для скриншотов> <пароль №2 тестовый>
// Почта — e2e-<время>@test.invalid (писем не получает); в конце аккаунт удаляется.
const crypto = require('crypto');
const { chromium } = require('/tmp/pw-check/node_modules/playwright-core');
const BASE = process.argv[2] || 'http://127.0.0.1:8777/app/';
const OUT = process.argv[3] || require('os').tmpdir();
const PASS2 = process.argv[4] || 'b';
const CODE = process.env.TEST_LOGIN_CODE || '123456';
const exe = require('os').homedir() + '/.cache/ms-playwright/chromium-1134/chrome-linux/chrome';
const ORIGIN = new URL(BASE).origin;

(async () => {
  const browser = await chromium.launch({ executablePath: exe });
  const ctx = await browser.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, locale: 'ru-RU' });
  const page = await ctx.newPage();
  const errors = [];
  page.on('pageerror', e => errors.push('pageerror: ' + e.message));
  page.on('console', m => { if (m.type() === 'error' && !/ERR_INTERNET_DISCONNECTED|status of 4\d\d/.test(m.text())) errors.push('console: ' + m.text()); });
  page.on('dialog', d => d.accept());
  const ok = (cond, msg) => { console.log((cond ? 'OK   ' : 'FAIL ') + msg); if (!cond) process.exitCode = 1; };
  const shot = n => page.screenshot({ path: OUT + '/' + n + '.png', fullPage: true });

  // Robokassa подменяем: запоминаем поля формы
  let rkForm = null;
  await ctx.route('https://auth.robokassa.ru/**', async route => {
    rkForm = Object.fromEntries(new URLSearchParams(route.request().postData() || ''));
    await route.fulfill({ status: 200, contentType: 'text/html', body: '<h1>Robokassa (подмена)</h1>' });
  });

  // ── 1. Гость: анкета ──
  await page.goto(BASE);
  await page.type('#f-date', '15011990');
  await page.fill('#f-time', '14:30');
  await page.fill('#f-birth-q', 'Казань');
  await page.press('#f-birth-q', 'Enter');
  await page.waitForSelector('#birth-city .city-opt, #birth-city .city-chosen:not([hidden])', { timeout: 20000 });
  if (await page.isVisible('#birth-city .city-opt')) await page.click('#birth-city .city-opt >> nth=0');
  await page.check('#f-consent');
  await page.click('#f-submit');
  await page.waitForFunction(() => document.querySelector('#m-dates').textContent.includes('—'), null, { timeout: 20000 });
  ok(await page.isVisible('#m-role-title') && await page.isHidden('#m-locked'), 'гость видит текущий месяц (тарифы для гостей выключены)');
  ok(await page.isHidden('#m-periods'), 'без платного доступа списка месяцев нет');
  ok(await page.isVisible('#m-diary') && await page.isVisible('#m-diary-empty'), 'в месяце — пустой блок дневника');

  // ── 2. Дневник гостя ──
  await page.click('#m-diary-add');
  await page.waitForSelector('[data-screen=diary]:not([hidden])');
  ok(await page.isVisible('#d-guest'), 'дневник гостя: подсказка про вход');
  const today = await page.inputValue('#d-day');
  ok(/^\d{4}-\d{2}-\d{2}$/.test(today), 'дата по умолчанию: ' + today);
  await page.click('#d-save');
  ok(await page.isVisible('#d-err'), 'пустую запись не сохраняет');
  await page.fill('#d-text', 'Сдала проект, вечером позвонил старый друг');
  await page.click('#d-save');
  await page.waitForSelector('#d-list .entry');
  await page.fill('#d-day', '2026-10-01');
  await page.fill('#d-text', 'Старая запись про октябрь');
  await page.click('#d-save');
  await page.waitForFunction(() => document.querySelectorAll('#d-list .entry').length === 2);
  const heads = await page.$$eval('#d-list h2', els => els.map(e => e.textContent));
  ok(heads.length >= 1 && heads[0].startsWith('Личный месяц'), 'записи сгруппированы по личным месяцам: ' + heads.join(' | '));
  // правка
  await page.click('#d-list .entry >> nth=0 >> text=Изменить');
  await page.fill('#d-text', 'Сдала проект! Вечером позвонил старый друг');
  await page.click('#d-save');
  await page.waitForFunction(() => document.querySelector('#d-list').textContent.includes('Сдала проект!'));
  ok(true, 'запись изменена');
  await shot('10-diary-guest');
  ok((await page.evaluate(() => JSON.parse(localStorage.getItem('zv.diary')).length)) === 2, 'записи гостя — в localStorage');
  await page.click('#to-diary').catch(() => {});
  await page.goto(BASE + '#month');
  await page.waitForFunction(() => document.querySelectorAll('#m-diary-list .entry').length >= 1, null, { timeout: 15000 });
  ok(true, 'запись видна в прогнозе месяца');

  // ── 3. Вход: профиль и дневник переезжают в аккаунт ──
  const email = 'e2e-' + Date.now() + '@test.invalid';
  await page.goto(BASE + '#settings');
  await page.click('#s-login');
  await page.fill('#lg-email', email);
  await page.click('#lg-submit');
  ok(await page.isVisible('#lg-consent-err'), 'без согласия код не просит');
  await page.check('#lg-consent');
  await page.click('#lg-submit');
  await page.waitForSelector('#lg-code-box:not([hidden])');
  await page.fill('#lg-code', '000000');
  await page.waitForSelector('#lg-code-err:not([hidden])');
  ok((await page.textContent('#lg-code-err')).includes('Неверный'), 'неверный код: ' + await page.textContent('#lg-code-err'));
  await page.fill('#lg-code', CODE);
  await page.waitForSelector('[data-screen=month]:not([hidden])', { timeout: 15000 });
  ok(await page.evaluate(() => !!JSON.parse(localStorage.getItem('zv.auth')).token), 'вошли, токен сохранён');
  ok(await page.evaluate(() => localStorage.getItem('zv.diary') === null), 'записи с устройства перенесены в аккаунт');

  // тестер: тарифы включены — текущий месяц закрыт
  await page.waitForSelector('#m-locked:not([hidden])', { timeout: 20000 });
  ok((await page.textContent('#l-title')).includes('по тарифу'), 'текущий месяц закрыт');
  await page.waitForSelector('#m-periods:not([hidden])', { timeout: 15000 });
  const st = await page.$$eval('#m-periods-list .p-st', els => els.map(e => e.textContent));
  ok(st[0].includes('бесплатно') && st[1].includes('закрыт') && st.length === 5, 'список месяцев (свёрнут): ' + st.slice(0, 3).join(' / ') + ' … всего ' + st.length);
  await shot('11-locked');
  await page.click('#l-prev');
  await page.waitForFunction(() => document.querySelector('#m-eyebrow').textContent.includes('Прошлый'), null, { timeout: 15000 });
  ok(await page.isVisible('#m-role-title') && await page.isHidden('#m-locked'), 'прошлый месяц открыт бесплатно');
  await page.waitForSelector('#m-chart:not([hidden])', { timeout: 30000 });
  ok(true, 'карта прошлого месяца нарисована');

  // дневник теперь с сервера
  await page.goto(BASE + '#diary');
  await page.waitForFunction(() => document.querySelectorAll('#d-list .entry').length === 2, null, { timeout: 15000 });
  ok(await page.isHidden('#d-guest'), 'дневник аккаунта: 2 записи с сервера');

  // ── 4. Тарифы и оплата ──
  await page.goto(BASE + '#plans');
  await page.waitForSelector('#p-list .plan');
  const plans = await page.$$eval('#p-list .plan .price', els => els.map(e => e.textContent));
  ok(plans.join(',') === '150 ₽,390 ₽,590 ₽,990 ₽,1590 ₽', 'тарифы: ' + plans.join(', '));
  await shot('12-plans');
  await page.click('#p-list .plan >> nth=1 >> button');
  await page.waitForFunction(() => document.body.textContent.includes('Robokassa'), null, { timeout: 15000 });
  ok(rkForm && rkForm.OutSum === '390.00' && rkForm.IsTest === '1', 'форма оплаты ушла в Robokassa: ' + (rkForm && rkForm.OutSum));
  ok(rkForm && decodeURIComponent(rkForm.Receipt).includes('"tax":"none"'), 'в счёте есть чек самозанятого');
  // уведомление Robokassa (как пришло бы на ResultURL)
  const sig = crypto.createHash('sha256').update(`${rkForm.OutSum}:${rkForm.InvId}:${PASS2}:Shp_uid=${rkForm.Shp_uid}`).digest('hex');
  const res = await ctx.request.post(ORIGIN + '/api/robokassa/result', {
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    data: new URLSearchParams({ OutSum: rkForm.OutSum, InvId: rkForm.InvId, SignatureValue: sig, Shp_uid: rkForm.Shp_uid, IsTest: '1' }).toString()
  });
  ok((await res.text()) === 'OK' + rkForm.InvId, 'ResultURL принял оплату');
  // возврат с Robokassa
  await page.goto(ORIGIN + '/app/pay-ok');
  await page.waitForFunction(() => !document.querySelector('#m-body').hidden && document.querySelector('#m-role-title').textContent.length > 3, null, { timeout: 30000 });
  ok((await page.textContent('#m-eyebrow')).includes('Твой личный месяц'), 'после оплаты текущий месяц открыт');
  await page.waitForFunction(() => document.querySelectorAll('#m-periods-list .period.paid').length >= 1, null, { timeout: 15000 });
  const st2 = await page.$$eval('#m-periods-list .p-st', els => els.map(e => e.textContent));
  ok(st2[1].includes('открыт') && st2[2].includes('оплачен') && st2[3].includes('оплачен') && st2[4].includes('закрыт'), 'месяцы после оплаты: ' + st2.slice(0, 5).join(' / '));
  await shot('13-paid');
  // следующий оплаченный — откроется позже
  await page.click('#m-next');
  await page.waitForFunction(() => document.querySelector('#m-eyebrow').textContent.includes('Следующий'), null, { timeout: 15000 });
  ok((await page.textContent('#l-eyebrow')) === 'Месяц оплачен', 'следующий оплаченный месяц: ' + await page.textContent('#l-title'));

  // ── 5. После оплаты дата рождения заблокирована ──
  await page.goto(BASE + '#form');
  await page.waitForSelector('[data-screen=form]:not([hidden])');
  ok(await page.isVisible('#form-locked') && await page.isDisabled('#f-date'), 'данные рождения после оплаты не меняются');

  // ── 6. Удаление аккаунта ──
  await page.goto(BASE + '#settings');
  await page.waitForSelector('#s-delete:not([hidden])');
  await page.click('#s-delete-btn');
  await page.waitForSelector('[data-screen=form]:not([hidden])');
  ok(await page.evaluate(() => localStorage.getItem('zv.auth') === null && localStorage.getItem('zv.profile') === null), 'аккаунт удалён, устройство очищено');

  ok(errors.length === 0, 'ошибок на странице нет' + (errors.length ? ': ' + errors.join(' | ') : ''));
  await browser.close();
})().catch(e => { console.error(e); process.exit(1); });
