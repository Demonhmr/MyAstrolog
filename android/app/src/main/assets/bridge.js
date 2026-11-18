/* Встраивается в страницу приложением Android (MainActivity).
   В WebView нет системного «Поделиться» для файлов — подменяем navigator.share нативным мостом window.ZVAndroid.
   Код сайта при этом не меняется: app.js сам вызывает navigator.share. */
(function () {
  var A = window.ZVAndroid;
  if (!A || window.__zvAndroid) return;
  window.__zvAndroid = true;
  document.documentElement.classList.add('in-android');

  function def(obj, name, fn) {
    try { Object.defineProperty(obj, name, { value: fn, configurable: true, writable: true }); } catch (e) { obj[name] = fn; }
  }

  def(navigator, 'canShare', function (data) { return !!(data && data.files && data.files.length); });
  def(navigator, 'share', function (data) {
    data = data || {};
    var text = [data.text, data.url].filter(Boolean).join(' ');
    return new Promise(function (resolve, reject) {
      var f = data.files && data.files[0];
      if (!f) { reject(new Error('nothing to share')); return; }
      var r = new FileReader();
      r.onload = function () {
        var s = String(r.result), b64 = s.slice(s.indexOf(',') + 1);
        if (A.shareFile(b64, f.type || 'image/png', f.name || 'karta.png', text)) resolve();
        else reject(new Error('share failed'));
      };
      r.onerror = function () { reject(r.error || new Error('read failed')); };
      r.readAsDataURL(f);
    });
  });
})();
