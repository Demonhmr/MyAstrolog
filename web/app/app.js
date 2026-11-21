/* Звездица — веб-приложение (оно же внутри Android-оболочки).
   Без входа профиль и дневник хранятся только на устройстве (localStorage), сервер /api/ ничего не запоминает.
   Со входом (код на почту) данные рождения, дневник и оплаченные месяцы живут на сервере.
   Android-оболочка добавляет window.ZVAndroid: setReminder(JSON-массив мс UTC), cancelReminder(), appVersion(), shareFile(). */
(function () {
  'use strict';

  var APP_VERSION = '1.1';
  var API = '../api';
  var CONSENT_VERSION = 'web-v2-2026-11-21';
  var KEY = {
    profile: 'zv.profile', last: 'zv.last', chart: 'zv.chart', reminder: 'zv.reminder', remKey: 'zv.remkey',
    auth: 'zv.auth', diary: 'zv.diary', diaryCache: 'zv.diary.cache', pay: 'zv.pay', after: 'zv.after'
  };
  var android = window.ZVAndroid || null;

  // ── мелочи ──────────────────────────────────────────────────────────────
  function $(sel, root) { return (root || document).querySelector(sel); }
  function $$(sel, root) { return Array.prototype.slice.call((root || document).querySelectorAll(sel)); }
  function h(tag, attrs) {
    var el = document.createElement(tag);
    if (attrs) Object.keys(attrs).forEach(function (k) {
      if (k === 'text') el.textContent = attrs[k];
      else if (k === 'class') el.className = attrs[k];
      else el.setAttribute(k, attrs[k]);
    });
    for (var i = 2; i < arguments.length; i++) {
      var c = arguments[i];
      if (c == null) continue;
      el.appendChild(typeof c === 'string' ? document.createTextNode(c) : c);
    }
    return el;
  }
  var store = {
    get: function (k) { try { var v = localStorage.getItem(k); return v ? JSON.parse(v) : null; } catch (e) { return null; } },
    set: function (k, v) { try { localStorage.setItem(k, JSON.stringify(v)); return true; } catch (e) { return false; } },
    del: function (k) { try { localStorage.removeItem(k); } catch (e) { /* нет хранилища */ } }
  };
  var toastTimer;
  function toast(msg) {
    var t = $('#toast');
    t.textContent = msg; t.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { t.hidden = true; }, 4500);
  }
  function newId() {
    var a = new Uint8Array(9);
    (window.crypto || window.msCrypto).getRandomValues(a);
    return 'e' + Array.prototype.map.call(a, function (b) { return ('0' + b.toString(16)).slice(-2); }).join('');
  }
  var MONTHS = ['января', 'февраля', 'марта', 'апреля', 'мая', 'июня', 'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря'];
  function isoToday() {
    var d = new Date();
    return d.getFullYear() + '-' + ('0' + (d.getMonth() + 1)).slice(-2) + '-' + ('0' + d.getDate()).slice(-2);
  }
  function fmtDay(iso) {
    var p = iso.split('-'), y = +p[0];
    return (+p[2]) + ' ' + MONTHS[+p[1] - 1] + (y !== new Date().getFullYear() ? ' ' + y : '');
  }
  function localDay(isoWithOffset) { return isoWithOffset.slice(0, 10); }   // '2026-11-04T18:21:47+03:00' → дата в поясе месяца

  // ── сервер ──────────────────────────────────────────────────────────────
  var auth = store.get(KEY.auth);          // {token, email}
  var cfg = null;                          // /api/config: тарифы, платный ли доступ, аккаунт

  function api(method, path, body, raw) {
    var ctrl = ('AbortController' in window) ? new AbortController() : null;
    var timer = ctrl && setTimeout(function () { ctrl.abort(); }, 25000);
    var headers = body ? { 'Content-Type': 'application/json' } : {};
    if (auth && auth.token) headers.Authorization = 'Bearer ' + auth.token;
    return fetch(API + path, {
      method: method, headers: headers,
      body: body ? JSON.stringify(body) : undefined,
      signal: ctrl ? ctrl.signal : undefined
    }).then(function (res) {
      if (!res.ok) {
        return res.json().catch(function () { return {}; }).then(function (j) {
          if (res.status === 401 && auth) dropAuth(true);
          var e = new Error(j.error || 'Что-то пошло не так. Попробуй ещё раз.');
          e.status = res.status; throw e;
        });
      }
      return raw ? res.blob() : res.json();
    }, function () {
      var e = new Error('Нет связи с сервером. Проверь интернет и попробуй ещё раз.');
      e.offline = true; throw e;
    }).finally(function () { if (timer) clearTimeout(timer); });
  }

  function dropAuth(expired) {
    auth = null; store.del(KEY.auth); store.del(KEY.diaryCache);
    if (cfg) { cfg.account = null; cfg.locked = false; }
    if (expired) toast('Вход устарел. Войди по почте ещё раз.');
    loadedKey = null; diaryLoaded = false; periodsKey = null;
  }

  function applyConfig(c) {
    var before = JSON.stringify([cfg && cfg.paywall, cfg && cfg.locked]);
    cfg = c;
    if (c.account && c.profile) {
      // со входом главный — профиль на сервере (с него считаются и оплаченные месяцы)
      var local = profile ? JSON.stringify(stripConsent(profile)) : '';
      if (local !== JSON.stringify(c.profile)) {
        profile = Object.assign({}, c.profile, { consent: { version: CONSENT_VERSION, at: new Date().toISOString() } });
        store.set(KEY.profile, profile);
        store.del(KEY.last); store.del(KEY.chart);
        loadedKey = null;
      }
    }
    if (JSON.stringify([c.paywall, c.locked]) !== before) { loadedKey = null; periodsKey = null; }
  }
  function stripConsent(p) {
    return { birth_date: p.birth_date, birth_time: p.birth_time, birth_place: p.birth_place, current_place: p.current_place || null };
  }

  var ready = null;   // загрузка настроек и синхронизация профиля (один раз за запуск или вход)
  function loadConfig() {
    ready = api('GET', '/config').then(function (c) {
      applyConfig(c);
      if (c.account && !c.profile && profile) return pushProfile();
    }).catch(function () { /* без сети — работаем по сохранённому */ });
    return ready;
  }
  function pushProfile() {
    return api('PUT', '/profile', stripConsent(profile)).then(function (c) { applyConfig(c); });
  }
  function paywall() { return !!(cfg && cfg.paywall); }

  // ── профиль ─────────────────────────────────────────────────────────────
  var profile = store.get(KEY.profile);

  function requestBody(at) {
    var b = stripConsent(profile);
    if (at) b.at = at;
    return b;
  }
  function profileKey() { return JSON.stringify(stripConsent(profile)) + '|' + (auth ? auth.email : ''); }
  function fmtBirthDate(iso) { var p = iso.split('-'); return p[2] + '.' + p[1] + '.' + p[0]; }

  // ── экраны ──────────────────────────────────────────────────────────────
  var SCREENS = ['form', 'month', 'settings', 'diary', 'login', 'plans'];
  function route() {
    var name = location.hash.replace('#', '') || 'month';
    if (SCREENS.indexOf(name) < 0) name = 'month';
    if (!profile && (name === 'month' || name === 'settings')) name = 'form';
    $$('.screen').forEach(function (s) { s.hidden = s.getAttribute('data-screen') !== name; });
    $('#to-settings').hidden = name === 'settings' || (!profile && name === 'form');
    $('#to-diary').hidden = name === 'diary' || (!profile && name === 'form');
    if (name === 'form') openForm();
    if (name === 'month') openMonth();
    if (name === 'settings') openSettings();
    if (name === 'diary') openDiary();
    if (name === 'login') openLogin();
    if (name === 'plans') openPlans();
    window.scrollTo(0, 0);
  }
  window.addEventListener('hashchange', route);

  // ── анкета ──────────────────────────────────────────────────────────────
  function cityPicker(root) {
    var q = $('input[type=search]', root), btn = $('[data-act=find]', root);
    var list = $('.city-results', root), chosen = $('.city-chosen', root), err = $('.err', root);
    var value = null;

    function setError(msg) { err.textContent = msg || ''; err.hidden = !msg; q.setAttribute('aria-invalid', msg ? 'true' : 'false'); }
    function set(v) {
      value = v; list.innerHTML = ''; setError('');
      $('span', chosen).textContent = v ? v.name : '';
      chosen.hidden = !v;
      q.parentNode.hidden = !!v;
    }
    function find() {
      var text = q.value.trim();
      if (text.length < 2) { setError('Напиши название города'); q.focus(); return; }
      setError(''); btn.disabled = true; btn.textContent = 'Ищем…'; list.innerHTML = '';
      api('GET', '/cities?q=' + encodeURIComponent(text)).then(function (r) {
        var found = r.cities || [];
        if (!found.length) { setError('Не нашли такой город. Попробуй написать иначе: «Нижний Новгород», «Saint Petersburg».'); return; }
        if (found.length === 1) { set(found[0]); return; }
        found.forEach(function (c) {
          var parts = c.name.split(', ');
          var b = h('button', { type: 'button', class: 'city-opt', role: 'radio', 'aria-checked': 'false' },
            parts[0], h('small', { text: parts.slice(1).join(', ') }));
          b.addEventListener('click', function () { set(c); });
          list.appendChild(b);
        });
        list.firstChild.focus();
      }, function (e) { setError(e.message); })
        .finally(function () { btn.disabled = false; btn.textContent = 'Найти'; });
    }
    btn.addEventListener('click', find);
    q.addEventListener('keydown', function (e) { if (e.key === 'Enter') { e.preventDefault(); find(); } });
    $('[data-act=change]', root).addEventListener('click', function () { set(null); q.focus(); q.select(); });
    function lock(on) { $('[data-act=change]', root).hidden = !!on; }
    return { get: function () { return value; }, set: set, setError: setError, lock: lock };
  }

  var birthCity = cityPicker($('#birth-city'));
  var curCity = cityPicker($('#cur-city'));
  var fDate = $('#f-date'), fTime = $('#f-time'), fUnknown = $('#f-time-unknown'), fConsent = $('#f-consent');

  function fieldError(id, input, msg) {
    var e = $('#' + id); e.textContent = msg || ''; e.hidden = !msg;
    if (input) input.setAttribute('aria-invalid', msg ? 'true' : 'false');
  }

  fDate.addEventListener('input', function () {
    var d = fDate.value.replace(/\D/g, '').slice(0, 8);
    var out = d.slice(0, 2);
    if (d.length > 2) out += '.' + d.slice(2, 4);
    if (d.length > 4) out += '.' + d.slice(4);
    fDate.value = out;
    fieldError('e-date', fDate, '');
  });
  fUnknown.addEventListener('change', function () {
    fTime.disabled = fUnknown.checked;
    $('#h-time').hidden = !fUnknown.checked;
    fieldError('e-time', fTime, '');
  });
  $$('input[name=where]').forEach(function (r) {
    r.addEventListener('change', function () { $('#cur-city').hidden = $('input[name=where]:checked').value !== 'other'; });
  });
  $('#f-cancel').addEventListener('click', function () { location.hash = '#settings'; });

  function parseDate(s) {
    var m = /^(\d{2})\.(\d{2})\.(\d{4})$/.exec(s);
    if (!m) return null;
    var d = +m[1], mo = +m[2], y = +m[3];
    var dt = new Date(Date.UTC(y, mo - 1, d));
    if (dt.getUTCFullYear() !== y || dt.getUTCMonth() !== mo - 1 || dt.getUTCDate() !== d) return null;
    if (y < 1900 || dt > new Date()) return null;
    return m[3] + '-' + m[2] + '-' + m[1];
  }

  function birthLocked() { return !!(auth && cfg && cfg.locked); }

  function openForm() {
    var editing = !!profile;
    var locked = editing && birthLocked();
    $('#form-title').textContent = editing ? 'Мои данные' : 'Узнай свой личный месяц';
    $('#form-lead').textContent = auth
      ? 'Звездица считает его по дате, времени и месту рождения. Данные хранятся в твоём аккаунте.'
      : 'Звездица считает его по дате, времени и месту рождения. Данные хранятся только на этом устройстве.';
    $('#form-locked').hidden = !locked;
    $('#f-cancel').hidden = !editing;
    $('#f-submit').textContent = editing ? 'Сохранить и пересчитать' : 'Рассчитать мой месяц';
    if (editing) {
      fDate.value = fmtBirthDate(profile.birth_date);
      fUnknown.checked = !profile.birth_time;
      fTime.value = profile.birth_time || '';
      fTime.disabled = fUnknown.checked; $('#h-time').hidden = !fUnknown.checked;
      birthCity.set(profile.birth_place);
      var other = !!profile.current_place;
      $('input[name=where][value=' + (other ? 'other' : 'same') + ']').checked = true;
      $('#cur-city').hidden = !other;
      curCity.set(profile.current_place || null);
      fConsent.checked = true;
    }
    fDate.disabled = locked; fUnknown.disabled = locked; if (locked) fTime.disabled = true;
    birthCity.lock(locked);
  }

  $('#profile-form').addEventListener('submit', function (e) {
    e.preventDefault();
    var firstBad = null;
    function bad(el) { if (!firstBad) firstBad = el; }

    var date = parseDate(fDate.value.trim());
    if (!date) { fieldError('e-date', fDate, 'Напиши дату как 15.01.1990'); bad(fDate); } else fieldError('e-date', fDate, '');

    var time = null;
    if (!fUnknown.checked) {
      if (!/^\d{2}:\d{2}$/.test(fTime.value)) { fieldError('e-time', fTime, 'Укажи время или отметь «Не знаю точное время»'); bad(fTime); }
      else { time = fTime.value; fieldError('e-time', fTime, ''); }
    }

    var bp = birthCity.get();
    if (!bp) { birthCity.setError('Найди и выбери город рождения'); bad($('#f-birth-q')); }

    var other = $('input[name=where]:checked').value === 'other';
    var cp = other ? curCity.get() : null;
    if (other && !cp) { curCity.setError('Найди и выбери город, где ты сейчас'); bad($('#f-cur-q')); }

    if (!fConsent.checked) { fieldError('e-consent', fConsent, 'Без согласия Звездица не сможет посчитать прогноз'); bad(fConsent); }
    else fieldError('e-consent', fConsent, '');

    if (firstBad) { firstBad.focus(); return; }

    var next = {
      birth_date: date, birth_time: time, birth_place: bp, current_place: cp,
      consent: { version: CONSENT_VERSION, at: new Date().toISOString() }
    };
    function done() {
      profile = next;
      store.set(KEY.profile, profile);
      store.del(KEY.last); store.del(KEY.chart);
      viewAt = null; loadedKey = null; periodsKey = null; cyclesCache = null;
      location.hash = '#month';
      if (location.hash === '#month') route();
    }
    if (!auth) { done(); return; }
    var btn = $('#f-submit'); btn.disabled = true;
    api('PUT', '/profile', stripConsent(next)).then(function (c) { applyConfig(c); done(); },
      function (err) { toast(err.message); }).finally(function () { btn.disabled = false; });
  });

  // ── прогноз ─────────────────────────────────────────────────────────────
  var viewAt = null;           // null — текущий месяц, иначе ISO-момент внутри нужного
  var loadedKey = null;        // что сейчас на экране (профиль + at)
  var current = null;          // текущий месяц: {start_utc, end_utc}
  var shown = null;            // показанный месяц: {start, end, start_utc, end_utc}
  var chartUrl = null, chartBlob = null;

  function openMonth() {
    var key = profileKey() + '|' + (viewAt || '');
    if (key === loadedKey) { renderMonthDiary(); return; }
    loadMonth();
  }

  function loadMonth() {
    var at = viewAt;
    var key = profileKey() + '|' + (at || '');
    var body = $('#m-body');
    body.setAttribute('aria-busy', 'true');
    $('#m-offline').hidden = true;
    var cached = store.get(KEY.last);
    if (!at && cached && cached.key === profileKey() && !loadedKey) renderAny(cached.report, true);

    (ready || Promise.resolve()).then(function () {
      return api('POST', '/forecast', requestBody(at));
    }).then(function (rep) {
      loadedKey = key;
      var idx = rep.access ? rep.access.index : (at ? null : 0);
      if (idx === 0 || (!at && idx == null)) {
        current = { start_utc: rep.cycle.start_utc, end_utc: rep.cycle.end_utc };
        if (!rep.locked) store.set(KEY.last, { key: profileKey(), report: rep, saved: Date.now() });
        else store.del(KEY.last);
        syncReminder(rep);
      }
      renderAny(rep, false);
      if (!rep.locked) loadChart(at);
      loadPeriods();
    }, function (e) {
      if (e.offline && !at && cached && cached.key === profileKey()) {
        renderAny(cached.report, true);
        $('#m-offline').hidden = false;
        var saved = store.get(KEY.chart);
        if (saved && saved.key === profileKey()) showChart(saved.data);
      } else {
        toast(e.message);
        if (at) { viewAt = null; }
        if (e.status === 409 && auth) location.hash = '#form';
      }
    }).finally(function () { body.setAttribute('aria-busy', 'false'); });
  }

  function cycleLabel(rep) {
    var i = rep.access ? rep.access.index : null;
    if (i === 0) return 'Твой личный месяц';
    if (i === 1) return 'Следующий личный месяц';
    if (i === -1) return 'Прошлый личный месяц';
    if (i != null) return i > 0 ? 'Будущий личный месяц' : 'Давний личный месяц';
    if (!current) return 'Твой личный месяц';
    var near = function (a, b) { return Math.abs(Date.parse(a) - Date.parse(b)) < 3600000; };
    var c = rep.cycle;
    if (near(c.start_utc, current.start_utc)) return 'Твой личный месяц';
    if (near(c.start_utc, current.end_utc)) return 'Следующий личный месяц';
    if (near(c.end_utc, current.start_utc)) return 'Прошлый личный месяц';
    return c.start_utc > current.start_utc ? 'Будущий личный месяц' : 'Давний личный месяц';
  }

  function renderHero(rep) {
    var c = rep.cycle;
    shown = { start: c.start, end: c.end, start_utc: c.start_utc, end_utc: c.end_utc };
    $('#m-eyebrow').textContent = cycleLabel(rep);
    $('#m-dates').textContent = c.start_text.split(',')[0] + ' — ' + c.end_text.split(',')[0];
    $('#m-city').textContent = 'С ' + c.start_text + ' до ' + c.end_text + ' · по времени: ' + c.city.split(',')[0];
    $('#m-time-warn').hidden = rep.time_known;
    $('#m-now').hidden = !viewAt;
    // кнопки «прошлый/следующий» считают от показанного месяца
    $('#m-prev').dataset.start = c.start_utc;
    $('#m-next').dataset.end = c.end_utc;
  }

  function renderAny(rep, fromCache) {
    if (rep.locked) renderLocked(rep); else renderMonth(rep, fromCache);
  }

  function renderLocked(rep) {
    renderHero(rep);
    $('#m-body').hidden = true;
    $('#m-locked').hidden = false;
    var st = rep.access.status, c = rep.cycle;
    var isPrev = rep.access.index === -1;
    $('#l-plans').hidden = st !== 'locked';
    $('#l-prev').hidden = isPrev;
    if (st === 'paid_later') {
      $('#l-eyebrow').textContent = 'Месяц оплачен';
      $('#l-title').textContent = 'Откроется ' + c.start_text;
      $('#l-text').textContent = 'Прогноз появится в момент, когда начнётся этот личный месяц. Посмотреть заранее можно с годовой подпиской.';
    } else if (st === 'closed') {
      $('#l-eyebrow').textContent = 'Месяц прошёл';
      $('#l-title').textContent = 'Этот месяц не был открыт';
      $('#l-text').textContent = 'Бесплатно доступен только прошлый личный месяц. Тарифы открывают текущий и следующие месяцы.';
    } else {
      $('#l-eyebrow').textContent = 'Месяц закрыт';
      $('#l-title').textContent = 'Прогноз на этот месяц — по тарифу';
      $('#l-text').textContent = 'Роль месяца, главная задача, «как хочешь и как будет», карта неба и разбор для знатоков. От 150 ₽ за месяц.';
    }
    $('#m-offline').hidden = true;
  }

  function renderMonth(rep, fromCache) {
    renderHero(rep);
    $('#m-body').hidden = false;
    $('#m-locked').hidden = true;

    $('#m-role-title').textContent = rep.role ? rep.role.title : 'Не удалось определить';
    $('#m-role-sign').textContent = rep.role ? '· ' + rep.role.sign_ru + ' ' + rep.role.symbol + '︎' : '';
    $('#m-role-text').textContent = rep.role ? rep.role.text : '';
    $('#m-task-title').textContent = rep.task ? rep.task.title : 'Не удалось определить';
    $('#m-task-text').textContent = rep.task ? rep.task.text : '';
    $('#m-inner').textContent = rep.climate.inner;
    $('#m-outer').textContent = rep.climate.outer;

    var story = $('#m-story'); story.innerHTML = '';
    if (rep.story.source === 'llm') {
      // текст нейросети сервер уже экранировал, разрешаем только <b>
      var safe = h('div', { class: 'stack' });
      safe.innerHTML = String(rep.story.text).replace(/<(?!\/?b>)/g, '&lt;').replace(/\n/g, '<br>');
      story.appendChild(safe);
    } else {
      rep.story.sections.forEach(function (s) {
        var box = h('div', null, h('h3', { text: s.title }));
        if (s.items) { var ul = h('ul'); s.items.forEach(function (i) { ul.appendChild(h('li', { text: i })); }); box.appendChild(ul); }
        if (s.text) box.appendChild(h('p', { text: s.text }));
        story.appendChild(box);
      });
    }

    var dyn = $('#m-dyn'); dyn.innerHTML = '';
    [['Начало месяца', rep.dynamics.start], ['Финал месяца', rep.dynamics.end]].forEach(function (p) {
      dyn.appendChild(h('div', { class: 'dyn' },
        h('h3', { text: p[0] }),
        h('p', { text: p[1].text }),
        p[1].sphere ? h('p', { class: 'sphere', text: 'Сфера: ' + p[1].sphere.toLowerCase() }) : null));
    });

    renderExpert(rep.expert);

    var isCurrent = !viewAt;
    $('#m-next-date').textContent = 'Начнётся ' + rep.cycle.end_text;
    $('#m-next-card').hidden = !isCurrent;
    $('#m-reminder').hidden = !(isCurrent && reminderSupported());
    $('#m-reminder-on').checked = reminderOn();
    renderMonthDiary();
    if (!fromCache) $('#m-offline').hidden = true;
  }

  function renderExpert(x) {
    var box = $('#m-expert'); box.innerHTML = '';
    box.appendChild(h('p', { class: 'fine', text: x.method + '. Начало цикла: ' + x.cycle_start_utc.replace('T', ' ').replace('Z', ' UTC') }));
    var tb = h('tbody');
    x.planets.forEach(function (p) {
      tb.appendChild(h('tr', null,
        h('td', { text: p.name_ru }),
        h('td', { text: p.sign_ru + ' ' + p.deg + '°' + (p.min < 10 ? '0' : '') + p.min + '′' + (p.retro ? ' ℞' : '') }),
        h('td', { text: String(p.house) })));
    });
    box.appendChild(h('table', null, h('thead', null, h('tr', null, h('th', { text: 'Планета' }), h('th', { text: 'Знак' }), h('th', { text: 'Дом' }))), tb));
    function sc(list) { return list.map(function (kv) { return kv[0] + ' ' + kv[1]; }).join(' · '); }
    var dl = h('dl');
    function row(k, v) { dl.appendChild(h('dt', { text: k })); dl.appendChild(h('dd', { text: v })); }
    row('Знаки, стихии', sc(x.sign_scores.elements));
    row('Знаки, кресты', sc(x.sign_scores.crosses));
    row('Дома, стихии', sc(x.house_scores.elements));
    row('Дома, кресты', sc(x.house_scores.crosses));
    row('Синтетический знак', (x.synth_sign.sign_ru || '—') + ' (' + x.synth_sign.element + ' + ' + x.synth_sign.cross + ')');
    row('Синтетический дом', (x.synth_house.house || '—') + ' (' + x.synth_house.element + ' + ' + x.synth_house.cross + ')');
    row('Асцендент', x.asc.sign_ru + ' ' + x.asc.deg + '°, управитель ' + (x.asc.ruler_ru || '—') + ' в ' + (x.asc.ruler_house || '—') + ' доме');
    row('MC', x.mc.sign_ru + ' ' + x.mc.deg + '°, управитель ' + (x.mc.ruler_ru || '—') + ' в ' + (x.mc.ruler_house || '—') + ' доме');
    box.appendChild(dl);
  }

  function showChart(src) {
    var img = $('#m-chart');
    img.onload = function () { img.hidden = false; $('#m-chart-wait').hidden = true; };
    img.src = src;
  }

  function loadChart(at) {
    var img = $('#m-chart');
    img.hidden = true; $('#m-chart-wait').hidden = false; $('#m-chart-wait').textContent = 'Рисуем карту…';
    $('#m-share').hidden = true;
    if (chartUrl) { URL.revokeObjectURL(chartUrl); chartUrl = null; }
    api('POST', '/chart', requestBody(at), true).then(function (blob) {
      if (at !== viewAt) return;              // пока рисовали, пользователь ушёл на другой месяц
      chartBlob = blob;
      chartUrl = URL.createObjectURL(blob);
      showChart(chartUrl);
      $('#m-share').hidden = !canShareFiles();
      if (!at) {
        var r = new FileReader();
        r.onload = function () { store.set(KEY.chart, { key: profileKey(), data: r.result }); };
        r.readAsDataURL(blob);
      }
    }, function () { $('#m-chart-wait').textContent = 'Карту нарисовать не получилось. Обнови страницу позже.'; });
  }

  function canShareFiles() {
    if (android && android.shareFile) return true;   // мост оболочки (как у Волпеня)
    try { return !!(navigator.canShare && navigator.canShare({ files: [new File([''], 'x.png', { type: 'image/png' })] })); }
    catch (e) { return false; }
  }
  $('#m-share').addEventListener('click', function () {
    if (!chartBlob) return;
    var file = new File([chartBlob], 'zvezditsa-karta.png', { type: 'image/png' });
    navigator.share({ files: [file], title: 'Моя карта неба', text: 'Мой личный месяц — Звездица' })
      .catch(function (e) { if (e && e.name !== 'AbortError') toast('Не получилось поделиться'); });
  });

  function shiftIso(iso, minutes) { return new Date(Date.parse(iso) + minutes * 60000).toISOString(); }
  function midIso(a, b) { return new Date((Date.parse(a) + Date.parse(b)) / 2).toISOString(); }
  function go(at) { viewAt = at; loadMonth(); window.scrollTo(0, 0); }
  $('#m-prev').addEventListener('click', function () {
    var start = $('#m-prev').dataset.start;
    if (start) go(shiftIso(start, -60));
  });
  $('#m-next').addEventListener('click', function () {
    var end = $('#m-next').dataset.end;
    if (end) go(shiftIso(end, 1));
  });
  $('#m-now').addEventListener('click', function () { go(null); });
  $('#l-prev').addEventListener('click', function () {
    if (!current) { go(null); return; }
    go(shiftIso(current.start_utc, -60));
  });

  // ── список личных месяцев (когда доступ платный) ──────────────────────
  var periodsKey = null, periodsData = null, periodsAll = false;
  var STATUS = { free: 'бесплатно', paid: 'открыт', paid_later: 'оплачен · откроется в начале', locked: 'закрыт', closed: 'прошёл', open: 'открыт' };
  function loadPeriods() {
    if (!paywall()) { $('#m-periods').hidden = true; return; }
    var key = profileKey() + '|' + (cfg && cfg.locked);
    if (key === periodsKey && periodsData) { renderPeriods(); return; }
    api('POST', '/periods', requestBody(null)).then(function (r) {
      periodsKey = key; periodsData = r; renderPeriods();
    }, function () { $('#m-periods').hidden = true; });
  }
  function renderPeriods() {
    var r = periodsData;
    if (!r || !r.paywall) { $('#m-periods').hidden = true; return; }
    var ol = $('#m-periods-list'); ol.innerHTML = '';
    var hidden = 0;
    r.items.forEach(function (it) {
      // свёрнуто: прошлый, текущий, 3 следующих и оплаченные; остальное — по кнопке
      if (!periodsAll && it.index > 3 && it.status === 'locked') { hidden++; return; }
      var on = shown && Math.abs(Date.parse(it.start_utc) - Date.parse(shown.start_utc)) < 6 * 3600000;
      var label = it.index === 0 ? 'сейчас · ' : (it.index === -1 ? 'прошлый · ' : '');
      var b = h('button', { type: 'button', class: 'period ' + it.status + (on ? ' on' : '') },
        h('span', { class: 'p-dates', text: it.start_date + ' — ' + it.end_date }),
        h('span', { class: 'p-st', text: label + STATUS[it.status] }));
      b.addEventListener('click', function () { go(it.index === 0 ? null : midIso(it.start_utc, it.end_utc)); });
      ol.appendChild(h('li', null, b));
    });
    if (hidden) {
      var more = h('button', { type: 'button', class: 'link', text: 'Показать ещё ' + hidden });
      more.addEventListener('click', function () { periodsAll = true; renderPeriods(); });
      ol.appendChild(h('li', null, more));
    }
    $('#m-periods').hidden = false;
  }

  // ── напоминание (только в Android-приложении) ─────────────────────────
  function reminderSupported() { return !!(android && android.setReminder); }
  function reminderOn() { var v = store.get(KEY.reminder); return v === null ? true : !!v; }
  // Оболочке передаём начало трёх следующих месяцев — напоминания придут, даже если приложение долго не открывать
  function syncReminder(rep, force) {
    if (!reminderSupported()) return;
    if (!reminderOn()) { try { android.cancelReminder(); } catch (e) { /* нет */ } return; }
    var key = profileKey() + '|' + rep.cycle.end_utc;
    if (!force && store.get(KEY.remKey) === key) return;
    var ends = [rep.cycle.end_utc];
    // закрытый месяц тоже отдаёт даты — напоминание о новом месяце работает и без оплаты
    function more(end) { return api('POST', '/forecast', requestBody(shiftIso(end, 1))).then(function (r) { ends.push(r.cycle.end_utc); return r.cycle.end_utc; }); }
    more(rep.cycle.end_utc).then(more).catch(function () { /* хватит и одного */ }).then(function () {
      try {
        android.setReminder(JSON.stringify(ends.map(function (e) { return Date.parse(e); })));
        store.set(KEY.remKey, key);
      } catch (e) { /* старая оболочка */ }
    });
  }
  function setReminder(on) {
    store.set(KEY.reminder, on);
    $('#m-reminder-on').checked = on; $('#s-reminder-on').checked = on;
    var last = store.get(KEY.last);
    store.del(KEY.remKey);
    if (last && last.report) syncReminder(last.report, true);
    else if (!on && reminderSupported()) android.cancelReminder();
    toast(on ? 'Напомним, когда начнётся новый месяц' : 'Напоминание выключено');
  }
  $('#m-reminder-on').addEventListener('change', function (e) { setReminder(e.target.checked); });
  $('#s-reminder-on').addEventListener('change', function (e) { setReminder(e.target.checked); });

  // ── дневник ─────────────────────────────────────────────────────────────
  // Без входа записи — в localStorage (zv.diary), со входом — на сервере (копия для офлайна — zv.diary.cache).
  var diary = [];               // [{id, day, text, created_at, updated_at}], новые сверху
  var diaryLoaded = false, diaryOffline = false;
  var editing = null;           // id записи, которую правим
  var cyclesCache = null;       // {from, to, items} — границы месяцев для группировки

  function sortDiary() {
    diary.sort(function (a, b) { return a.day < b.day ? 1 : a.day > b.day ? -1 : (a.created_at < b.created_at ? 1 : -1); });
  }
  function loadDiary() {
    if (!auth) {
      diary = store.get(KEY.diary) || []; sortDiary(); diaryLoaded = true; diaryOffline = false;
      return Promise.resolve();
    }
    return api('GET', '/diary').then(function (r) {
      diary = r.entries; diaryLoaded = true; diaryOffline = false;
      store.set(KEY.diaryCache, { email: auth.email, entries: diary });
    }, function (e) {
      var c = store.get(KEY.diaryCache);
      diary = (c && auth && c.email === auth.email) ? c.entries : [];
      diaryOffline = !!e.offline; diaryLoaded = !e.offline;
      if (!e.offline) throw e;
    });
  }
  function saveLocal() { store.set(KEY.diary, diary); }

  function upsertEntry(entry) {
    if (!auth) {
      var now = new Date().toISOString().slice(0, 19);
      var old = diary.filter(function (x) { return x.id === entry.id; })[0];
      if (old) { old.day = entry.day; old.text = entry.text; old.updated_at = now; }
      else diary.push({ id: entry.id, day: entry.day, text: entry.text, created_at: now, updated_at: now });
      sortDiary(); saveLocal();
      return Promise.resolve();
    }
    return api('PUT', '/diary/' + entry.id, { day: entry.day, text: entry.text }).then(function (saved) {
      diary = diary.filter(function (x) { return x.id !== saved.id; }); diary.push(saved); sortDiary();
      store.set(KEY.diaryCache, { email: auth.email, entries: diary });
    });
  }
  function deleteEntry(id) {
    if (!auth) { diary = diary.filter(function (x) { return x.id !== id; }); saveLocal(); return Promise.resolve(); }
    return api('DELETE', '/diary/' + id).then(function () {
      diary = diary.filter(function (x) { return x.id !== id; });
      store.set(KEY.diaryCache, { email: auth.email, entries: diary });
    });
  }

  function openDiary(prefillDay) {
    $('#d-guest').hidden = !!auth;
    if (!editing) resetDiaryForm(prefillDay || pendingDay);
    pendingDay = null;
    (diaryLoaded ? Promise.resolve() : loadDiary()).then(renderDiary, function (e) { toast(e.message); renderDiary(); });
  }
  var pendingDay = null;
  function resetDiaryForm(day) {
    editing = null;
    $('#d-form-title').textContent = 'Новая запись';
    $('#d-day').value = day || isoToday();
    $('#d-text').value = ''; $('#d-count').textContent = '0';
    $('#d-cancel').hidden = true; $('#d-err').hidden = true;
    $('#d-save').textContent = 'Сохранить';
  }
  $('#d-text').addEventListener('input', function () { $('#d-count').textContent = String($('#d-text').value.length); });
  $('#d-cancel').addEventListener('click', function () { resetDiaryForm(); });
  $('#diary-form').addEventListener('submit', function (e) {
    e.preventDefault();
    var day = $('#d-day').value, text = $('#d-text').value.trim();
    var err = $('#d-err');
    if (!/^\d{4}-\d{2}-\d{2}$/.test(day)) { err.textContent = 'Выбери дату'; err.hidden = false; return; }
    if (!text) { err.textContent = 'Напиши, что было'; err.hidden = false; $('#d-text').focus(); return; }
    err.hidden = true;
    var btn = $('#d-save'); btn.disabled = true;
    var wasEditing = !!editing;
    upsertEntry({ id: editing || newId(), day: day, text: text }).then(function () {
      toast(wasEditing ? 'Запись изменена' : 'Записано');
      resetDiaryForm(); renderDiary(); renderMonthDiary();
    }, function (er) { err.textContent = er.message; err.hidden = false; })
      .finally(function () { btn.disabled = false; });
  });

  function diaryGroups(cb) {
    // группы по личным месяцам; без профиля или без сети — по календарным месяцам
    if (!diary.length) { cb([]); return; }
    var from = diary[diary.length - 1].day, to = diary[0].day;
    function byCalendar() {
      var g = [], cur = null;
      diary.forEach(function (e) {
        var k = e.day.slice(0, 7);
        if (!cur || cur.key !== k) { cur = { key: k, title: MONTHS_NOM[+k.slice(5) - 1] + ' ' + k.slice(0, 4), items: [] }; g.push(cur); }
        cur.items.push(e);
      });
      return g;
    }
    function byCycles(items) {
      var g = [];
      items.slice().reverse().forEach(function (c) {
        var a = localDay(c.start), b = localDay(c.end);
        var its = diary.filter(function (e) { return e.day >= a && e.day < b; });
        if (its.length) g.push({ key: c.start_utc, title: c.start_date + ' — ' + c.end_date, cycle: c, items: its });
      });
      var covered = {}; g.forEach(function (x) { x.items.forEach(function (e) { covered[e.id] = 1; }); });
      if (diary.some(function (e) { return !covered[e.id]; })) return byCalendar();
      return g;
    }
    if (!profile) { cb(byCalendar()); return; }
    if (cyclesCache && cyclesCache.key === profileKey() && cyclesCache.from <= from && cyclesCache.to >= to) { cb(byCycles(cyclesCache.items)); return; }
    var body = requestBody(null); body.from = from; body.to = to;
    api('POST', '/cycles', body).then(function (r) {
      cyclesCache = { key: profileKey(), from: from, to: to, items: r.items };
      cb(byCycles(r.items));
    }, function () { cb(byCalendar()); });
  }
  var MONTHS_NOM = ['Январь', 'Февраль', 'Март', 'Апрель', 'Май', 'Июнь', 'Июль', 'Август', 'Сентябрь', 'Октябрь', 'Ноябрь', 'Декабрь'];

  function entryNode(e, withActions) {
    var li = h('article', { class: 'entry' },
      h('p', { class: 'entry-day', text: fmtDay(e.day) }),
      h('p', { class: 'entry-text', text: e.text }));
    if (withActions) {
      var edit = h('button', { type: 'button', class: 'link', text: 'Изменить' });
      var del = h('button', { type: 'button', class: 'link danger-link', text: 'Удалить' });
      edit.addEventListener('click', function () {
        editing = e.id;
        $('#d-form-title').textContent = 'Изменить запись';
        $('#d-day').value = e.day; $('#d-text').value = e.text; $('#d-count').textContent = String(e.text.length);
        $('#d-cancel').hidden = false; $('#d-save').textContent = 'Сохранить изменения';
        window.scrollTo(0, 0); $('#d-text').focus();
      });
      del.addEventListener('click', function () {
        if (!confirm('Удалить запись за ' + fmtDay(e.day) + '?')) return;
        deleteEntry(e.id).then(function () { if (editing === e.id) resetDiaryForm(); renderDiary(); renderMonthDiary(); toast('Запись удалена'); },
          function (er) { toast(er.message); });
      });
      li.appendChild(h('div', { class: 'row entry-actions' }, edit, del));
    }
    return li;
  }

  function renderDiary() {
    $('#d-offline').hidden = !diaryOffline;
    $('#d-save').disabled = diaryOffline;
    $('#d-empty').hidden = diary.length > 0;
    var box = $('#d-list');
    diaryGroups(function (groups) {
      box.innerHTML = '';
      groups.forEach(function (g) {
        var sec = h('section', { class: 'stack' }, h('h2', { class: 'title-3', text: g.cycle ? 'Личный месяц ' + g.title : g.title }));
        g.items.forEach(function (e) { sec.appendChild(entryNode(e, !diaryOffline)); });
        box.appendChild(sec);
      });
    });
  }

  function renderMonthDiary() {
    if (!shown) return;
    var a = localDay(shown.start), b = localDay(shown.end);
    var draw = function () {
      var its = diary.filter(function (e) { return e.day >= a && e.day < b; });
      var ul = $('#m-diary-list'); ul.innerHTML = '';
      its.slice(0, 20).forEach(function (e) { ul.appendChild(h('li', null, entryNode(e, false))); });
      $('#m-diary-empty').hidden = its.length > 0;
      var today = isoToday();
      $('#m-diary-add').dataset.day = (today >= a && today < b) ? today : a;
    };
    if (diaryLoaded || !auth) { if (!diaryLoaded) loadDiary().then(draw); else draw(); }
    else loadDiary().then(draw, draw);
  }
  $('#m-diary-add').addEventListener('click', function (e) {
    pendingDay = e.currentTarget.dataset.day || null;
    editing = null;
  });

  // ── вход по почте ──────────────────────────────────────────────────────
  var lgEmail = $('#lg-email'), lgCode = $('#lg-code'), lgStep = 'email', resendTimer = null;
  function lgErr(id, msg) { var e = $('#' + id); e.textContent = msg || ''; e.hidden = !msg; }
  function openLogin() {
    if (auth) { location.hash = '#settings'; return; }
    setStep(lgStep);
  }
  function setStep(step) {
    lgStep = step;
    var code = step === 'code';
    $('#lg-code-box').hidden = !code;
    $('#lg-resend').hidden = !code; $('#lg-change').hidden = !code;
    lgEmail.disabled = code;
    $('#lg-submit').textContent = code ? 'Войти' : 'Получить код';
    ['lg-email-err', 'lg-consent-err', 'lg-code-err'].forEach(function (i) { lgErr(i, ''); });
    if (code) { lgCode.value = ''; lgCode.focus(); }
  }
  function sendCode() {
    var email = lgEmail.value.trim();
    if (!/^[^@\s]+@[^@\s]+\.[^@\s]{2,}$/.test(email)) { lgErr('lg-email-err', 'Проверь адрес почты'); lgEmail.focus(); return Promise.resolve(); }
    if (!$('#lg-consent').checked) { lgErr('lg-consent-err', 'Без согласия войти не получится'); return Promise.resolve(); }
    return api('POST', '/auth/code', { email: email }).then(function (r) {
      setStep('code');
      $('#lg-code-hint').textContent = 'Отправили код на ' + email + '. Он действует ' + r.ttl_min + ' минут. Письма нет — проверь «Спам».';
      var btn = $('#lg-resend'); btn.disabled = true;
      clearTimeout(resendTimer); resendTimer = setTimeout(function () { btn.disabled = false; }, 60000);
    }, function (e) { lgErr(lgStep === 'code' ? 'lg-code-err' : 'lg-email-err', e.message); });
  }
  $('#login-form').addEventListener('submit', function (e) {
    e.preventDefault();
    var btn = $('#lg-submit'); btn.disabled = true;
    var p = lgStep === 'email' ? sendCode() : login();
    p.finally(function () { btn.disabled = false; });
  });
  $('#lg-resend').addEventListener('click', function () { sendCode(); });
  $('#lg-change').addEventListener('click', function () { setStep('email'); lgEmail.focus(); });
  lgCode.addEventListener('input', function () {
    lgCode.value = lgCode.value.replace(/\D/g, '').slice(0, 6);
    if (lgCode.value.length === 6 && lgStep === 'code') $('#lg-submit').click();
  });
  function login() {
    var code = lgCode.value.trim();
    if (!/^\d{6}$/.test(code)) { lgErr('lg-code-err', 'Код — 6 цифр из письма'); return Promise.resolve(); }
    return api('POST', '/auth/login', { email: lgEmail.value.trim(), code: code, agree: $('#lg-consent').checked })
      .then(function (r) {
        auth = { token: r.token, email: r.account.email };
        store.set(KEY.auth, auth);
        applyConfig(r);
        loadedKey = null; periodsKey = null; diaryLoaded = false; cyclesCache = null;
        return afterLogin(r).then(function () {
          setStep('email'); lgCode.value = '';
          toast(r.new ? 'Аккаунт создан' : 'Вход выполнен');
          var after = store.get(KEY.after); store.del(KEY.after);
          location.hash = after || (profile ? '#month' : '#form');
        });
      }, function (e) { lgErr('lg-code-err', e.message); });
  }
  function afterLogin(r) {
    var steps = [];
    // профиль с устройства → в аккаунт, если там ещё пусто
    if (!r.profile && profile) steps.push(pushProfile().catch(function (e) { toast(e.message); }));
    // записи дневника с устройства → в аккаунт
    var local = store.get(KEY.diary) || [];
    if (local.length) {
      steps.push(api('POST', '/diary/import', { entries: local.map(function (e) {
        return { id: e.id, day: e.day, text: e.text, created_at: e.created_at ? e.created_at + 'Z' : null };
      }) }).then(function (res) {
        store.del(KEY.diary); diary = res.entries; diaryLoaded = true;
        store.set(KEY.diaryCache, { email: auth.email, entries: diary });
      }).catch(function () { toast('Записи дневника перенесём позже'); }));
    }
    ready = Promise.all(steps);
    return ready;
  }

  // ── тарифы и оплата ────────────────────────────────────────────────────
  function openPlans() {
    var list = $('#p-list'); list.innerHTML = '';
    if (!cfg) {
      list.appendChild(h('p', { class: 'muted', text: 'Загружаем тарифы…' }));
      (ready || loadConfig()).then(function () { if (location.hash === '#plans') openPlans(); });
      return;
    }
    var payable = paywall() && cfg.pay_ready;
    $('#p-not-ready').hidden = !paywall() || cfg.pay_ready;
    if (!paywall()) {
      $('#p-not-ready').hidden = false;
      $('#p-not-ready').textContent = 'Сейчас все прогнозы открыты бесплатно. Тарифы заработают позже.';
    } else {
      $('#p-not-ready').textContent = 'Оплата скоро заработает. Пока можно посмотреть прошлый месяц бесплатно.';
    }
    cfg.plans.forEach(function (p) {
      var btn = h('button', { type: 'button', class: 'btn' + (p.preview ? '' : ' ghost'),
        text: auth ? 'Оплатить ' + p.rub + ' ₽' : 'Войти и оплатить' });
      btn.disabled = !payable;
      btn.addEventListener('click', function () { buy(p, btn); });
      list.appendChild(h('article', { class: 'card plan' + (p.preview ? ' best' : '') },
        h('div', { class: 'row between' }, h('h2', { class: 'card-title-sm', text: p.title }), h('p', { class: 'price', text: p.rub + ' ₽' })),
        h('p', { class: 'muted', text: p.text }),
        p.months > 1 ? h('p', { class: 'fine', text: Math.round(p.rub / p.months) + ' ₽ за месяц' }) : null,
        btn));
    });
  }
  function buy(p, btn) {
    if (!auth) { store.set(KEY.after, '#plans'); location.hash = '#login'; return; }
    if (!profile) { location.hash = '#form'; return; }
    btn.disabled = true;
    (ready || Promise.resolve()).then(function () {
      return api('POST', '/pay', { plan: p.code });
    }).then(function (r) {
      store.set(KEY.pay, { inv: r.inv, plan: p.code, at: Date.now() });
      var f = h('form', { method: 'POST', action: r.action });
      Object.keys(r.fields).forEach(function (k) { f.appendChild(h('input', { type: 'hidden', name: k, value: r.fields[k] })); });
      document.body.appendChild(f);
      f.submit();
    }, function (e) { toast(e.message); btn.disabled = false; });
  }
  function checkPayReturn() {
    var m = /[?&]pay=(ok|fail|check)/.exec(location.search);
    if (!m) return;
    history.replaceState(null, '', location.pathname + location.hash);
    var pend = store.get(KEY.pay);
    if (m[1] === 'fail') { toast('Оплата не прошла или отменена. Деньги не списаны.'); return; }
    if (!pend || !auth) return;
    toast('Проверяем оплату…');
    var tries = 0;
    (function poll() {
      api('GET', '/pay/' + pend.inv).then(function (r) {
        if (r.status === 'paid') {
          store.del(KEY.pay);
          toast('Оплата прошла. Открыто месяцев: ' + r.granted);
          cfg && (cfg.locked = true);
          loadedKey = null; periodsKey = null; viewAt = null;
          location.hash = '#month'; route();
        } else if (++tries < 30) setTimeout(poll, 2000);
        else toast('Оплата ещё не подтверждена. Обнови страницу через пару минут.');
      }, function () { if (++tries < 30) setTimeout(poll, 3000); });
    })();
  }

  // ── настройки ───────────────────────────────────────────────────────────
  function openSettings() {
    var dl = $('#s-facts'); dl.innerHTML = '';
    function row(k, v) { dl.appendChild(h('dt', { text: k })); dl.appendChild(h('dd', { text: v })); }
    row('Дата рождения', fmtBirthDate(profile.birth_date));
    row('Время', profile.birth_time || 'не знаю');
    row('Город рождения', profile.birth_place.name);
    row('Где сейчас', profile.current_place ? profile.current_place.name : 'там же');
    $('#s-reminder').hidden = !reminderSupported();
    $('#s-reminder-on').checked = reminderOn();
    $('#s-account-text').textContent = auth
      ? 'Вход по почте: ' + auth.email + '. Данные рождения, дневник и оплаченные месяцы хранятся в аккаунте.'
      : 'Вход не выполнен: данные и дневник хранятся только на этом устройстве. Вход нужен для оплаты и чтобы данные были на всех устройствах.';
    $('#s-login').hidden = !!auth; $('#s-logout').hidden = !auth;
    $('#s-plans').hidden = !paywall();
    $('#s-delete').hidden = !auth;
    $('#s-erase-text').textContent = auth
      ? 'Удалит данные и сохранённые прогнозы с этого устройства и выйдет из аккаунта. В аккаунте всё останется.'
      : 'Удалит дату, время и города рождения, дневник и сохранённые прогнозы с этого устройства. На сервере они не хранятся.';
    var v = 'Звездица ' + APP_VERSION;
    try { if (android && android.appVersion) v += ' · приложение для Android ' + android.appVersion(); } catch (e) { /* нет */ }
    $('#s-version').textContent = v;
  }
  $('#s-edit').addEventListener('click', function () { location.hash = '#form'; });
  $('#s-logout').addEventListener('click', function () {
    api('POST', '/auth/logout').catch(function () { /* всё равно выходим */ });
    dropAuth(false);
    diary = store.get(KEY.diary) || []; diaryLoaded = false;
    loadConfig().then(function () { openSettings(); });
    toast('Выход выполнен');
    openSettings();
  });
  function eraseLocal() {
    [KEY.profile, KEY.last, KEY.chart, KEY.reminder, KEY.remKey, KEY.diary, KEY.diaryCache, KEY.pay, KEY.after].forEach(store.del);
    try { if (reminderSupported()) android.cancelReminder(); } catch (e) { /* нет */ }
    profile = null; loadedKey = null; viewAt = null; current = null; diary = []; diaryLoaded = false; cyclesCache = null;
    $('#profile-form').reset(); birthCity.set(null); curCity.set(null);
    fTime.disabled = false; $('#h-time').hidden = true; $('#cur-city').hidden = true;
  }
  $('#s-erase').addEventListener('click', function () {
    if (!confirm(auth ? 'Стереть данные с этого устройства и выйти из аккаунта?' : 'Стереть твои данные, дневник и сохранённые прогнозы с этого устройства?')) return;
    if (auth) { api('POST', '/auth/logout').catch(function () {}); dropAuth(false); }
    eraseLocal();
    toast('Данные стёрты');
    loadConfig();
    location.hash = '#form';
  });
  $('#s-delete-btn').addEventListener('click', function () {
    if (!confirm('Удалить аккаунт? С сервера удалятся данные рождения, дневник и оплаченные месяцы. Это нельзя отменить.')) return;
    api('DELETE', '/account').then(function () {
      dropAuth(false); eraseLocal();
      toast('Аккаунт удалён');
      loadConfig();
      location.hash = '#form';
    }, function (e) { toast(e.message); });
  });

  // ── старт ───────────────────────────────────────────────────────────────
  if (android) document.documentElement.classList.add('in-android');
  if ('serviceWorker' in navigator && location.protocol === 'https:') {
    navigator.serviceWorker.register('sw.js').catch(function () { /* без офлайна */ });
  }
  loadConfig().then(function () {
    if (location.hash === '#plans' || location.hash === '#settings') route();
  });
  checkPayReturn();
  route();
})();
