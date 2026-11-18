// Сквозная проверка приложения в Chromium с размером телефона.
// node web/tools/e2e.js [адрес] [папка для скриншотов]
const { chromium } = require('/tmp/pw-check/node_modules/playwright-core');
const BASE = process.argv[2] || 'https://zvezditsa.137-22-150-127.sslip.io/app/';
const OUT = process.argv[3] || require('os').tmpdir();
const exe = require('os').homedir() + '/.cache/ms-playwright/chromium-1134/chrome-linux/chrome';

(async () => {
  const browser = await chromium.launch({ executablePath: exe });
  const ctx = await browser.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, locale: 'ru-RU' });
  const page = await ctx.newPage();
  const errors = [];
  page.on('pageerror', e => errors.push('pageerror: ' + e.message));
  page.on('console', m => { if (m.type() === 'error' && !m.text().includes('ERR_INTERNET_DISCONNECTED')) errors.push('console: ' + m.text()); });
  const ok = (cond, msg) => { console.log((cond ? 'OK   ' : 'FAIL ') + msg); if (!cond) process.exitCode = 1; };

  await page.goto(BASE);
  ok(await page.isVisible('[data-screen=form]'), 'без профиля открывается анкета');
  await page.screenshot({ path: OUT + '/01-form.png', fullPage: true });

  // пустая отправка — ошибки
  await page.click('#f-submit');
  ok(await page.isVisible('#e-date'), 'ошибка даты при пустой форме');

  await page.fill('#f-date', '');
  await page.type('#f-date', '15011990');
  ok((await page.inputValue('#f-date')) === '15.01.1990', 'маска даты ставит точки');
  await page.fill('#f-time', '14:30');

  await page.fill('#f-birth-q', 'Березники');
  await page.press('#f-birth-q', 'Enter');
  await page.waitForSelector('#birth-city .city-opt', { timeout: 15000 });
  const opts = await page.$$eval('#birth-city .city-opt', els => els.map(e => e.textContent));
  ok(opts.length > 1, 'несколько вариантов города: ' + opts.length);
  await page.screenshot({ path: OUT + '/02-cities.png', fullPage: true });
  await page.click('#birth-city .city-opt >> nth=0');
  ok(await page.isVisible('#birth-city .city-chosen'), 'город выбран: ' + await page.textContent('#birth-city .city-chosen span'));

  await page.check('input[name=where][value=other]');
  await page.fill('#f-cur-q', 'Москва');
  await page.click('#cur-city [data-act=find]');
  await page.waitForSelector('#cur-city .city-chosen:not([hidden])', { timeout: 15000 });
  ok(true, 'единственный вариант выбран сам: ' + await page.textContent('#cur-city .city-chosen span'));

  await page.check('#f-consent');
  await page.click('#f-submit');
  await page.waitForSelector('[data-screen=month]:not([hidden])');
  await page.waitForFunction(() => document.querySelector('#m-dates').textContent.includes('—'), null, { timeout: 15000 });
  ok(true, 'прогноз: ' + await page.textContent('#m-dates') + ' | ' + await page.textContent('#m-role-title') + ' | ' + await page.textContent('#m-task-title'));
  ok((await page.$$('#m-story h3')).length >= 2, 'текст «как хочешь / как будет» из справочника');
  await page.waitForSelector('#m-chart:not([hidden])', { timeout: 20000 });
  ok(true, 'карта нарисована');
  ok(await page.isHidden('#m-reminder'), 'в браузере переключателя напоминания нет');
  await page.screenshot({ path: OUT + '/03-month.png', fullPage: true });

  const cur = await page.textContent('#m-dates');
  await page.click('#m-next');
  await page.waitForFunction(c => document.querySelector('#m-dates').textContent !== c, cur, { timeout: 15000 });
  ok(await page.isVisible('#m-now'), 'следующий месяц: ' + await page.textContent('#m-dates') + ' (' + await page.textContent('#m-eyebrow') + ')');
  await page.click('#m-now');
  await page.waitForFunction(c => document.querySelector('#m-dates').textContent === c, cur, { timeout: 15000 });
  await page.click('#m-prev');
  await page.waitForFunction(c => document.querySelector('#m-dates').textContent !== c, cur, { timeout: 15000 });
  ok(true, 'прошлый месяц: ' + await page.textContent('#m-dates'));
  await page.click('#m-now');
  await page.waitForFunction(c => document.querySelector('#m-dates').textContent === c, cur, { timeout: 15000 });

  await page.click('.expert summary');
  ok((await page.$$('#m-expert tbody tr')).length === 10, 'для знатоков: 10 планет');
  await page.screenshot({ path: OUT + '/04-expert.png', fullPage: true });

  // перезагрузка — профиль на месте, офлайн — сохранённый прогноз
  await page.reload();
  await page.waitForSelector('[data-screen=month]:not([hidden])');
  ok((await page.textContent('#m-dates')) === cur, 'после перезагрузки прогноз на месте');
  await page.waitForTimeout(1500);
  await ctx.setOffline(true);
  await page.reload().catch(() => {});
  await page.waitForSelector('#m-offline:not([hidden])', { timeout: 15000 }).catch(() => {});
  ok(await page.isVisible('#m-offline'), 'без сети — сохранённый прогноз и пометка');
  ok(await page.isVisible('#m-chart'), 'без сети — сохранённая карта');
  await ctx.setOffline(false);

  await page.goto(BASE + '#settings');
  ok((await page.textContent('#s-facts')).includes('15.01.1990'), 'настройки показывают данные');
  await page.screenshot({ path: OUT + '/05-settings.png', fullPage: true });
  page.once('dialog', d => d.accept());
  await page.click('#s-erase');
  await page.waitForSelector('[data-screen=form]:not([hidden])');
  const left = await page.evaluate(() => Object.keys(localStorage).filter(k => k.startsWith('zv.')));
  ok(left.length === 0, 'после «Стереть» на устройстве ничего не осталось');

  ok(errors.length === 0, 'ошибок в консоли нет' + (errors.length ? ': ' + errors.join(' | ') : ''));
  await browser.close();
})().catch(e => { console.error(e); process.exit(1); });
