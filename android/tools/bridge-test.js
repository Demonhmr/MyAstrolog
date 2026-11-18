// Проверка моста Android без эмулятора: страница в Chromium с поддельным window.ZVAndroid,
// настоящий assets/bridge.js и BACK_JS из MainActivity.java.
// node android/tools/bridge-test.js [адрес приложения]
const fs = require('fs'), path = require('path');
const { chromium } = require('/tmp/pw-check/node_modules/playwright-core');
const BASE = process.argv[2] || 'https://zvezditsa.137-22-150-127.sslip.io/app/';
const root = path.join(__dirname, '..');
const bridge = fs.readFileSync(path.join(root, 'app/src/main/assets/bridge.js'), 'utf8');
const java = fs.readFileSync(path.join(root, 'app/src/main/java/ru/zvezditsa/app/MainActivity.java'), 'utf8');
const m = java.match(/BACK_JS =\s*([\s\S]*?);\n/);
const BACK_JS = eval(m[1]);   // склейка строк Java совпадает с JS

const PROFILE = { birth_date: '1990-01-15', birth_time: '14:30',
  birth_place: { name: 'Москва, Россия', lat: 55.7558, lon: 37.6173, tz: 'Europe/Moscow' }, current_place: null,
  consent: { version: 'web-v1-2026-11-18', at: new Date().toISOString() } };

(async () => {
  const b = await chromium.launch({ executablePath: require('os').homedir() + '/.cache/ms-playwright/chromium-1134/chrome-linux/chrome' });
  const ctx = await b.newContext({ viewport: { width: 390, height: 844 }, userAgent: 'Mozilla/5.0 (Linux; Android 14) ZVAndroid/1.0' });
  await ctx.addInitScript((p) => {
    window.__calls = [];
    window.ZVAndroid = {
      setReminder: (j) => window.__calls.push(['setReminder', j]),
      cancelReminder: () => window.__calls.push(['cancelReminder']),
      appVersion: () => '1.0',
      shareFile: (b64, mime, name, text) => { window.__calls.push(['shareFile', b64.length, mime, name, text]); return true; }
    };
    if (!localStorage.getItem('zv.profile')) localStorage.setItem('zv.profile', JSON.stringify(p));
  }, PROFILE);
  const page = await ctx.newPage();
  const errors = [];
  page.on('pageerror', e => errors.push(e.message));
  const ok = (c, msg) => { console.log((c ? 'OK   ' : 'FAIL ') + msg); if (!c) process.exitCode = 1; };
  const calls = () => page.evaluate(() => window.__calls);
  const back = () => page.evaluate(BACK_JS);

  await page.goto(BASE + '#month');
  await page.evaluate(bridge);   // так делает onPageCommitVisible
  await page.waitForSelector('#m-chart:not([hidden])', { timeout: 20000 });
  ok(await page.evaluate(() => document.documentElement.classList.contains('in-android')), 'класс in-android');
  ok(await page.isVisible('#m-reminder'), 'переключатель напоминания виден в приложении');
  await page.waitForFunction(() => window.__calls.some(c => c[0] === 'setReminder'), null, { timeout: 15000 });
  const rem = (await calls()).find(c => c[0] === 'setReminder');
  const times = JSON.parse(rem[1]);
  const end = await page.evaluate(() => JSON.parse(localStorage.getItem('zv.last')).report.cycle.end_utc);
  ok(times.length === 3 && times[0] === Date.parse(end) && times[0] < times[1] && times[1] < times[2],
     'setReminder: 3 момента, первый = конец текущего месяца: ' + times.map(t => new Date(t).toISOString()).join(', '));
  const gaps = [times[1] - times[0], times[2] - times[1]].map(g => g / 86400000);
  ok(gaps.every(g => g > 26.5 && g < 28.5), 'между напоминаниями ~27 дней: ' + gaps.map(g => g.toFixed(2)).join(', '));

  // повторный заход не дёргает оболочку
  await page.reload(); await page.evaluate(bridge);
  await page.waitForSelector('#m-chart:not([hidden])', { timeout: 20000 });
  await page.waitForTimeout(1500);
  ok((await calls()).filter(c => c[0] === 'setReminder').length === 0, 'после перезагрузки повторно не планирует');

  await page.click('#m-reminder-on');   // выключить
  ok((await calls()).some(c => c[0] === 'cancelReminder'), 'выключение → cancelReminder');
  await page.click('#m-reminder-on');   // включить снова
  await page.waitForFunction(() => window.__calls.some(c => c[0] === 'setReminder'), null, { timeout: 15000 });
  ok(true, 'включение → setReminder');

  ok(await page.isVisible('#m-share'), 'кнопка «Поделиться картой» видна');
  await page.click('#m-share');
  await page.waitForFunction(() => window.__calls.some(c => c[0] === 'shareFile'), null, { timeout: 5000 });
  const sh = (await calls()).find(c => c[0] === 'shareFile');
  ok(sh[1] > 100000 && sh[2] === 'image/png' && sh[3] === 'zvezditsa-karta.png', 'shareFile: PNG ' + sh[1] + ' симв. base64, ' + sh[3]);

  // «Назад»
  await page.click('.expert summary');
  ok((await back()).includes('h') && !(await page.evaluate(() => document.querySelector('details.expert').open)), 'Назад закрывает «для знатоков»');
  await page.click('#m-next');
  await page.waitForSelector('#m-now:not([hidden])');
  ok((await back()).includes('h'), 'Назад с другого месяца → текущий');
  await page.waitForSelector('#m-now', { state: 'hidden' });
  await page.evaluate(() => { location.hash = '#settings'; });
  await page.waitForSelector('[data-screen=settings]:not([hidden])');
  ok((await page.textContent('#s-version')).includes('приложение для Android 1.0'), 'версия приложения в настройках');
  ok(await page.isVisible('#s-reminder'), 'напоминание в настройках');
  await back(); await page.waitForSelector('[data-screen=month]:not([hidden])');
  ok(true, 'Назад из настроек → прогноз');
  ok((await back()).includes('exit'), 'Назад на прогнозе → свернуть приложение');

  // «Стереть данные» отменяет напоминание
  await page.evaluate(() => { window.__calls = []; location.hash = '#settings'; });
  page.once('dialog', d => d.accept());
  await page.click('#s-erase');
  await page.waitForSelector('[data-screen=form]:not([hidden])');
  ok((await calls()).some(c => c[0] === 'cancelReminder'), '«Стереть» → cancelReminder');
  ok((await back()).includes('exit'), 'Назад на анкете без профиля → свернуть');

  ok(errors.length === 0, 'ошибок на странице нет' + (errors.length ? ': ' + errors.join(' | ') : ''));
  await b.close();
})().catch(e => { console.error(e); process.exit(1); });
