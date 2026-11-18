/* Звездица — веб-приложение (оно же внутри Android-оболочки).
   Профиль хранится только на устройстве (localStorage), сервер /api/ ничего не запоминает.
   Android-оболочка добавляет window.ZVAndroid: setReminder(utcMs, title, text), cancelReminder(), appVersion(). */
(function () {
  'use strict';

  var APP_VERSION = '1.0';
  var API = '../api';
  var CONSENT_VERSION = 'web-v1-2026-11-18';
  var KEY = { profile: 'zv.profile', last: 'zv.last', chart: 'zv.chart', reminder: 'zv.reminder' };
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
  function api(method, path, body, raw) {
    var ctrl = ('AbortController' in window) ? new AbortController() : null;
    var timer = ctrl && setTimeout(function () { ctrl.abort(); }, 25000);
    return fetch(API + path, {
      method: method,
      headers: body ? { 'Content-Type': 'application/json' } : {},
      body: body ? JSON.stringify(body) : undefined,
      signal: ctrl ? ctrl.signal : undefined
    }).then(function (res) {
      if (!res.ok) {
        return res.json().catch(function () { return {}; }).then(function (j) {
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

  // ── профиль ─────────────────────────────────────────────────────────────
  var profile = store.get(KEY.profile);

  function requestBody(at) {
    var b = {
      birth_date: profile.birth_date,
      birth_time: profile.birth_time,
      birth_place: profile.birth_place,
      current_place: profile.current_place || null
    };
    if (at) b.at = at;
    return b;
  }
  function profileKey() { return JSON.stringify(requestBody(null)); }
  function shortCity(place) { return place ? place.name.split(',')[0] : ''; }
  function fmtBirthDate(iso) { var p = iso.split('-'); return p[2] + '.' + p[1] + '.' + p[0]; }

  // ── экраны ──────────────────────────────────────────────────────────────
  function route() {
    var name = location.hash.replace('#', '') || 'month';
    if (['form', 'month', 'settings'].indexOf(name) < 0) name = 'month';
    if (!profile) name = 'form';
    $$('.screen').forEach(function (s) { s.hidden = s.getAttribute('data-screen') !== name; });
    $('#to-settings').hidden = !profile || name === 'settings';
    if (name === 'form') openForm();
    if (name === 'month') openMonth();
    if (name === 'settings') openSettings();
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
    return { get: function () { return value; }, set: set, setError: setError, focus: function () { (value ? $('[data-act=change]', root) : q).focus(); } };
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

  function openForm() {
    var editing = !!profile;
    $('#form-title').textContent = editing ? 'Мои данные' : 'Узнай свой личный месяц';
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

    profile = {
      birth_date: date, birth_time: time, birth_place: bp, current_place: cp,
      consent: { version: CONSENT_VERSION, at: new Date().toISOString() }
    };
    store.set(KEY.profile, profile);
    store.del(KEY.last); store.del(KEY.chart);
    viewAt = null; loadedKey = null;
    location.hash = '#month';
    if (location.hash === '#month') route();
  });

  // ── прогноз ─────────────────────────────────────────────────────────────
  var viewAt = null;           // null — текущий месяц, иначе ISO-момент внутри нужного
  var loadedKey = null;        // что сейчас на экране (профиль + at)
  var current = null;          // текущий месяц: {start_utc, end_utc}
  var chartUrl = null, chartBlob = null;

  function openMonth() {
    var key = profileKey() + '|' + (viewAt || '');
    if (key === loadedKey) return;
    loadMonth();
  }

  function loadMonth() {
    var at = viewAt;
    var key = profileKey() + '|' + (at || '');
    var body = $('#m-body');
    body.setAttribute('aria-busy', 'true');
    $('#m-offline').hidden = true;
    var cached = store.get(KEY.last);
    if (!at && cached && cached.key === profileKey() && !loadedKey) renderMonth(cached.report, true);

    api('POST', '/forecast', requestBody(at)).then(function (rep) {
      loadedKey = key;
      if (!at) {
        current = { start_utc: rep.cycle.start_utc, end_utc: rep.cycle.end_utc };
        store.set(KEY.last, { key: profileKey(), report: rep, saved: Date.now() });
        syncReminder(rep);
      }
      renderMonth(rep, false);
      loadChart(at);
    }, function (e) {
      if (e.offline && !at && cached && cached.key === profileKey()) {
        renderMonth(cached.report, true);
        $('#m-offline').hidden = false;
        var saved = store.get(KEY.chart);
        if (saved && saved.key === profileKey()) showChart(saved.data);
      } else {
        toast(e.message);
        if (at) { viewAt = null; }
      }
    }).finally(function () { body.setAttribute('aria-busy', 'false'); });
  }

  function cycleLabel(rep) {
    if (!current) return 'Твой личный месяц';
    var near = function (a, b) { return Math.abs(Date.parse(a) - Date.parse(b)) < 3600000; };
    var c = rep.cycle;
    if (near(c.start_utc, current.start_utc)) return 'Твой личный месяц';
    if (near(c.start_utc, current.end_utc)) return 'Следующий личный месяц';
    if (near(c.end_utc, current.start_utc)) return 'Прошлый личный месяц';
    return c.start_utc > current.start_utc ? 'Будущий личный месяц' : 'Давний личный месяц';
  }

  function renderMonth(rep, fromCache) {
    var c = rep.cycle;
    $('#m-eyebrow').textContent = cycleLabel(rep);
    $('#m-dates').textContent = c.start_text.split(',')[0] + ' — ' + c.end_text.split(',')[0];
    $('#m-city').textContent = 'С ' + c.start_text + ' до ' + c.end_text + ' · по времени: ' + c.city.split(',')[0];
    $('#m-time-warn').hidden = rep.time_known;
    $('#m-now').hidden = !viewAt;

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
    $('#m-next-date').textContent = 'Начнётся ' + c.end_text;
    $('#m-reminder').hidden = !(isCurrent && reminderSupported());
    $('#m-reminder-on').checked = reminderOn();

    // кнопки «прошлый/следующий» считают от показанного месяца
    $('#m-prev').dataset.start = c.start_utc;
    $('#m-next').dataset.end = c.end_utc;
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

  // ── напоминание (только в Android-приложении) ─────────────────────────
  function reminderSupported() { return !!(android && android.setReminder); }
  function reminderOn() { var v = store.get(KEY.reminder); return v === null ? true : !!v; }
  function syncReminder(rep) {
    if (!reminderSupported()) return;
    try {
      if (reminderOn()) {
        android.setReminder(String(Date.parse(rep.cycle.end_utc)),
          'Начался твой новый личный месяц',
          'Посмотри роль и главную задачу месяца');
      } else android.cancelReminder();
    } catch (e) { /* старая оболочка */ }
  }
  function setReminder(on) {
    store.set(KEY.reminder, on);
    $('#m-reminder-on').checked = on; $('#s-reminder-on').checked = on;
    var last = store.get(KEY.last);
    if (last && last.report) syncReminder(last.report);
    else if (!on && reminderSupported()) android.cancelReminder();
    toast(on ? 'Напомним, когда начнётся новый месяц' : 'Напоминание выключено');
  }
  $('#m-reminder-on').addEventListener('change', function (e) { setReminder(e.target.checked); });
  $('#s-reminder-on').addEventListener('change', function (e) { setReminder(e.target.checked); });

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
    var v = 'Звездица ' + APP_VERSION;
    try { if (android && android.appVersion) v += ' · приложение для Android ' + android.appVersion(); } catch (e) { /* нет */ }
    $('#s-version').textContent = v;
  }
  $('#s-edit').addEventListener('click', function () { location.hash = '#form'; });
  $('#s-erase').addEventListener('click', function () {
    if (!confirm('Стереть твои данные и сохранённые прогнозы с этого устройства?')) return;
    [KEY.profile, KEY.last, KEY.chart, KEY.reminder].forEach(store.del);
    try { if (reminderSupported()) android.cancelReminder(); } catch (e) { /* нет */ }
    profile = null; loadedKey = null; viewAt = null; current = null;
    $('#profile-form').reset(); birthCity.set(null); curCity.set(null);
    fTime.disabled = false; $('#h-time').hidden = true; $('#cur-city').hidden = true;
    toast('Данные стёрты');
    location.hash = '#form';
  });

  // ── старт ───────────────────────────────────────────────────────────────
  if (android) document.documentElement.classList.add('in-android');
  if ('serviceWorker' in navigator && location.protocol === 'https:') {
    navigator.serviceWorker.register('sw.js').catch(function () { /* без офлайна */ });
  }
  route();
})();
