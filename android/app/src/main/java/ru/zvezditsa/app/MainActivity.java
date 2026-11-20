package ru.zvezditsa.app;

import android.Manifest;
import android.annotation.SuppressLint;
import android.app.Activity;
import android.content.ClipData;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.graphics.Color;
import android.graphics.Insets;
import android.graphics.Typeface;
import android.net.Uri;
import android.net.http.SslError;
import android.os.Build;
import android.os.Bundle;
import android.util.Base64;
import android.util.TypedValue;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.view.WindowInsets;
import android.view.WindowInsetsController;
import android.webkit.RenderProcessGoneDetail;
import android.webkit.SslErrorHandler;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Button;
import android.widget.FrameLayout;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.TextView;
import android.widget.Toast;
import android.window.OnBackInvokedDispatcher;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;

/**
 * Звездица — это веб-приложение с сайта (тот же код, что и в браузере).
 * Здесь только «оболочка»: окно на весь экран, системные полосы, кнопка «Назад»,
 * меню «Поделиться» для карты, документы поверх приложения, экран «нет связи»
 * и нативное напоминание о начале нового личного месяца (ReminderReceiver).
 */
public class MainActivity extends Activity {

    /** «Назад» внутри страницы: настройки → прогноз, анкета → настройки, другой месяц → текущий, иначе выход. */
    private static final String BACK_JS =
        "(function(){" +
        " var h=location.hash.slice(1), p=false;" +
        " try{p=!!localStorage.getItem('zv.profile');}catch(e){}" +
        " var ex=document.querySelector('details.expert[open]');" +
        " if(h==='settings'){location.hash='#month';return 'h';}" +
        " if(h==='form'&&p){location.hash='#settings';return 'h';}" +
        " if(ex&&h!=='form'){ex.open=false;return 'h';}" +
        " var now=document.getElementById('m-now');" +
        " if(now&&!now.hidden&&h!=='form'){now.click();return 'h';}" +
        " return 'exit';" +
        "})()";

    private static final int REQ_NOTIF = 7;

    private WebView web;          // приложение
    private WebView docWeb;       // документы (политика, согласие) поверх приложения
    private View docLayer;
    private View errorLayer;
    private View statusBg, navBg;
    private String bridgeJs = "";
    private boolean loadFailed;

    // ---------------------------------------------------------------- запуск

    @Override
    protected void onCreate(Bundle saved) {
        super.onCreate(saved);
        bridgeJs = readAsset("bridge.js");
        buildUi();
        setupEdgeToEdge();
        setupBack();
        Reminders.ensureChannel(this);

        if (saved != null && web.restoreState(saved) != null) return;
        web.loadUrl(BuildConfig.START_URL + "#month");
    }

    @Override
    protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        setIntent(intent);
        if (intent != null && intent.getBooleanExtra(Reminders.EXTRA_FROM_NOTIF, false)) {
            // нажали на напоминание, когда приложение уже открыто: показать новый месяц
            closeDoc();
            web.loadUrl(BuildConfig.START_URL + "#month");
        }
    }

    @Override protected void onResume() {
        super.onResume();
        web.onResume();
        if (docWeb != null) docWeb.onResume();
    }
    @Override protected void onPause() { web.onPause(); if (docWeb != null) docWeb.onPause(); super.onPause(); }
    @Override protected void onSaveInstanceState(Bundle out) { super.onSaveInstanceState(out); web.saveState(out); }

    @Override
    protected void onDestroy() {
        if (web != null) web.destroy();
        if (docWeb != null) docWeb.destroy();
        super.onDestroy();
    }

    // ---------------------------------------------------------------- экран

    private int dp(float v) { return Math.round(TypedValue.applyDimension(TypedValue.COMPLEX_UNIT_DIP, v, getResources().getDisplayMetrics())); }

    private void buildUi() {
        int night = getColor(R.color.night);

        LinearLayout column = new LinearLayout(this);
        column.setOrientation(LinearLayout.VERTICAL);
        column.setBackgroundColor(night);

        statusBg = new View(this);
        statusBg.setBackgroundColor(night);
        column.addView(statusBg, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0));

        FrameLayout content = new FrameLayout(this);
        column.addView(content, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f));

        navBg = new View(this);
        navBg.setBackgroundColor(night);
        column.addView(navBg, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0));

        web = makeWebView(true);
        web.addJavascriptInterface(new Bridge(), "ZVAndroid");
        content.addView(web, new FrameLayout.LayoutParams(-1, -1));

        docLayer = buildDocLayer();
        docLayer.setVisibility(View.GONE);
        content.addView(docLayer, new FrameLayout.LayoutParams(-1, -1));

        errorLayer = buildErrorLayer();
        errorLayer.setVisibility(View.GONE);
        content.addView(errorLayer, new FrameLayout.LayoutParams(-1, -1));

        setContentView(column);
    }

    @SuppressLint("SetJavaScriptEnabled")
    private WebView makeWebView(boolean main) {
        WebView w = new WebView(this);
        w.setBackgroundColor(getColor(main ? R.color.night : R.color.doc_band));
        w.setOverScrollMode(View.OVER_SCROLL_NEVER);
        WebSettings s = w.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);           // профиль и последний прогноз хранятся в localStorage
        s.setSupportZoom(false);
        s.setBuiltInZoomControls(false);
        s.setDisplayZoomControls(false);
        s.setAllowFileAccess(false);
        s.setAllowContentAccess(false);
        s.setSupportMultipleWindows(false);     // target="_blank" — в том же окне, разбираем в shouldOverrideUrlLoading
        s.setUserAgentString(s.getUserAgentString() + " ZVAndroid/" + BuildConfig.VERSION_NAME);
        WebView.setWebContentsDebuggingEnabled(BuildConfig.DEBUG);

        w.setWebChromeClient(new WebChromeClient());   // нужен, чтобы работали alert/confirm
        w.setWebViewClient(main ? new AppClient() : new DocClient());
        w.setDownloadListener((url, ua, cd, mime, len) -> {
            if (url.startsWith("http")) openExternal(Uri.parse(url));
        });
        return w;
    }

    private View buildDocLayer() {
        LinearLayout box = new LinearLayout(this);
        box.setOrientation(LinearLayout.VERTICAL);
        box.setBackgroundColor(getColor(R.color.doc_band));
        box.setClickable(true);

        TextView back = new TextView(this);
        back.setText(R.string.doc_back);
        back.setTextColor(Color.WHITE);
        back.setTextSize(TypedValue.COMPLEX_UNIT_SP, 16);
        back.setTypeface(Typeface.DEFAULT_BOLD);
        back.setGravity(Gravity.CENTER_VERTICAL);
        back.setPadding(dp(16), 0, dp(16), 0);
        back.setBackgroundColor(getColor(R.color.night));
        back.setOnClickListener(v -> closeDoc());
        box.addView(back, new LinearLayout.LayoutParams(-1, dp(52)));
        return box;
    }

    private View buildErrorLayer() {
        LinearLayout box = new LinearLayout(this);
        box.setOrientation(LinearLayout.VERTICAL);
        box.setGravity(Gravity.CENTER);
        box.setPadding(dp(32), dp(32), dp(32), dp(32));
        box.setBackgroundColor(getColor(R.color.night));
        box.setClickable(true);

        ImageView img = new ImageView(this);
        img.setImageResource(R.mipmap.ic_launcher);
        box.addView(img, new LinearLayout.LayoutParams(dp(96), dp(96)));

        TextView title = new TextView(this);
        title.setText(R.string.offline_title);
        title.setTextColor(Color.WHITE);
        title.setTextSize(TypedValue.COMPLEX_UNIT_SP, 22);
        title.setTypeface(Typeface.SERIF, Typeface.BOLD);
        title.setGravity(Gravity.CENTER);
        title.setPadding(0, dp(20), 0, dp(8));
        box.addView(title);

        TextView text = new TextView(this);
        text.setText(R.string.offline_text);
        text.setTextColor(getColor(R.color.moon_dim));
        text.setTextSize(TypedValue.COMPLEX_UNIT_SP, 15);
        text.setGravity(Gravity.CENTER);
        box.addView(text);

        Button retry = new Button(this);
        retry.setText(R.string.retry);
        retry.setAllCaps(false);
        retry.setTextSize(TypedValue.COMPLEX_UNIT_SP, 16);
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(-2, -2);
        lp.topMargin = dp(24);
        box.addView(retry, lp);
        retry.setOnClickListener(v -> {
            errorLayer.setVisibility(View.GONE);
            String url = web.getUrl();
            if (url == null || url.startsWith("about:") || url.startsWith("data:")) web.loadUrl(BuildConfig.START_URL + "#month");
            else web.reload();
        });
        return box;
    }

    /** Android 15+ рисует приложение под системными полосами — подкладываем под них полоски цвета неба. */
    private void setupEdgeToEdge() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.R) return;   // до Android 11 цвета полос берутся из темы
        getWindow().setDecorFitsSystemWindows(false);
        WindowInsetsController c = getWindow().getInsetsController();
        if (c != null) c.setSystemBarsAppearance(0,
            WindowInsetsController.APPEARANCE_LIGHT_STATUS_BARS | WindowInsetsController.APPEARANCE_LIGHT_NAVIGATION_BARS);
        View column = (View) statusBg.getParent();
        column.setOnApplyWindowInsetsListener((v, insets) -> {
            Insets bars = insets.getInsets(WindowInsets.Type.systemBars() | WindowInsets.Type.displayCutout());
            Insets ime = insets.getInsets(WindowInsets.Type.ime());
            setHeight(statusBg, bars.top);
            setHeight(navBg, Math.max(bars.bottom, ime.bottom));   // клавиатура не закрывает поля анкеты
            v.setPadding(bars.left, 0, bars.right, 0);
            return WindowInsets.CONSUMED;
        });
    }

    private static void setHeight(View v, int h) {
        ViewGroup.LayoutParams lp = v.getLayoutParams();
        if (lp.height != h) { lp.height = h; v.setLayoutParams(lp); }
    }

    // ---------------------------------------------------------------- «Назад»

    private void setupBack() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            getOnBackInvokedDispatcher().registerOnBackInvokedCallback(OnBackInvokedDispatcher.PRIORITY_DEFAULT, this::handleBack);
        }
    }

    @SuppressWarnings("deprecation")
    @Override
    public void onBackPressed() { handleBack(); }   // Android 12 и старше

    private void handleBack() {
        if (docLayer.getVisibility() == View.VISIBLE) {
            if (docWeb != null && docWeb.canGoBack()) docWeb.goBack(); else closeDoc();
            return;
        }
        if (errorLayer.getVisibility() == View.VISIBLE) { moveTaskToBack(true); return; }
        Uri u = web.getUrl() != null ? Uri.parse(web.getUrl()) : null;
        if (u == null || !isAppUrl(u)) {
            if (web.canGoBack()) web.goBack(); else web.loadUrl(BuildConfig.START_URL + "#month");
            return;
        }
        web.evaluateJavascript(BACK_JS, res -> {
            if (res == null || res.contains("exit")) moveTaskToBack(true);
        });
    }

    // ---------------------------------------------------------------- ссылки

    /** Свои адреса: текущий и будущий домен — чтобы после переезда сайта версия 1.0 не открывала его в браузере. */
    // старый адрес оставлен: ссылки на него редиректят на zvezditsa.ru и должны открываться внутри приложения
    private static final String[] HOSTS = { BuildConfig.SITE_HOST, "zvezditsa.137-22-150-127.sslip.io" };

    private static boolean isSiteHost(Uri u) {
        String h = u.getHost();
        if (h == null) return false;
        for (String s : HOSTS) if (h.equals(s) || h.equals("www." + s)) return true;
        return false;
    }

    private static boolean isAppUrl(Uri u) {
        String p = u.getPath();
        return "https".equals(u.getScheme()) && isSiteHost(u) && p != null && p.startsWith("/app");
    }

    private void openDoc(String url) {
        if (docWeb == null) {
            docWeb = makeWebView(false);
            ((LinearLayout) docLayer).addView(docWeb, new LinearLayout.LayoutParams(-1, 0, 1f));
        }
        docWeb.loadUrl(url);
        docLayer.setVisibility(View.VISIBLE);
    }

    private void closeDoc() {
        if (docLayer.getVisibility() != View.VISIBLE) return;
        docLayer.setVisibility(View.GONE);
        if (docWeb != null) { docWeb.loadUrl("about:blank"); docWeb.clearHistory(); }
    }

    private boolean openExternal(Uri uri) {
        try {
            Intent i = new Intent(Intent.ACTION_VIEW, uri);
            i.addCategory(Intent.CATEGORY_BROWSABLE);
            startActivity(i);
            return true;
        } catch (Exception e) {
            Toast.makeText(this, R.string.no_app, Toast.LENGTH_SHORT).show();
            return false;
        }
    }

    /** Решает, где открыть ссылку. true — открыли сами, WebView грузить не должен. */
    private boolean route(WebView view, WebResourceRequest req) {
        Uri u = req.getUrl();
        String scheme = u.getScheme();
        if (!"http".equals(scheme) && !"https".equals(scheme)) { openExternal(u); return true; }   // mailto: и т. п.
        if (view == docWeb) {
            if (isAppUrl(u)) { closeDoc(); return true; }      // «← В приложение» со страницы документа
            if (isSiteHost(u)) return false;
            openExternal(u); return true;
        }
        if (isAppUrl(u)) return false;
        if (isSiteHost(u)) { openDoc(u.toString()); return true; }   // политика, согласие — поверх приложения
        if (!req.hasGesture() || req.isRedirect()) return false;
        openExternal(u); return true;   // чужие сайты — в браузере
    }

    private class AppClient extends WebViewClient {
        @Override public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest req) { return route(view, req); }

        @Override public void onPageStarted(WebView view, String url, android.graphics.Bitmap favicon) { loadFailed = false; }

        @Override public void onPageCommitVisible(WebView view, String url) { inject(view, url); }

        @Override public void onPageFinished(WebView view, String url) {
            inject(view, url);
            if (!loadFailed) errorLayer.setVisibility(View.GONE);
        }

        @Override public void onReceivedError(WebView view, WebResourceRequest req, WebResourceError err) {
            if (!req.isForMainFrame()) return;
            loadFailed = true;
            errorLayer.setVisibility(View.VISIBLE);
        }

        @Override public boolean onRenderProcessGone(WebView view, RenderProcessGoneDetail detail) {
            recreate();   // движок страницы упал — перезапускаем экран вместо падения приложения
            return true;
        }

        /** Сертификат не прошёл проверку — такую страницу никогда не открываем. */
        @Override public void onReceivedSslError(WebView view, SslErrorHandler handler, SslError error) {
            handler.cancel();
        }

        private void inject(WebView view, String url) {
            if (url != null && isAppUrl(Uri.parse(url))) view.evaluateJavascript(bridgeJs, null);
        }
    }

    private class DocClient extends WebViewClient {
        @Override public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest req) { return route(view, req); }
        @Override public boolean onRenderProcessGone(WebView view, RenderProcessGoneDetail detail) { recreate(); return true; }
        @Override public void onReceivedSslError(WebView view, SslErrorHandler handler, SslError error) { handler.cancel(); }
    }

    // ---------------------------------------------------------------- уведомления

    private void askNotificationPermission() {
        if (Build.VERSION.SDK_INT < 33) return;
        if (checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) == PackageManager.PERMISSION_GRANTED) return;
        requestPermissions(new String[]{Manifest.permission.POST_NOTIFICATIONS}, REQ_NOTIF);
    }

    @Override
    public void onRequestPermissionsResult(int code, String[] perms, int[] results) {
        super.onRequestPermissionsResult(code, perms, results);
        if (code == REQ_NOTIF && (results.length == 0 || results[0] != PackageManager.PERMISSION_GRANTED)) {
            Toast.makeText(this, R.string.notif_denied, Toast.LENGTH_LONG).show();
        }
    }

    // ---------------------------------------------------------------- мост для страницы (window.ZVAndroid)

    private class Bridge {
        /**
         * Запланировать напоминания о начале следующих личных месяцев.
         * timesJson — JSON-массив моментов в миллисекундах UTC, например [1764618900000, 1766980800000].
         */
        @android.webkit.JavascriptInterface
        public void setReminder(String timesJson) {
            Reminders.save(MainActivity.this, timesJson);
            Reminders.scheduleNext(MainActivity.this);
            runOnUiThread(MainActivity.this::askNotificationPermission);
        }

        @android.webkit.JavascriptInterface
        public void cancelReminder() {
            Reminders.cancel(MainActivity.this);
        }

        @android.webkit.JavascriptInterface
        public String appVersion() { return BuildConfig.VERSION_NAME; }

        /** Картинка карты → системное меню «Поделиться». */
        @android.webkit.JavascriptInterface
        public boolean shareFile(String base64, String mime, String name, String text) {
            try {
                byte[] bytes = Base64.decode(base64, Base64.DEFAULT);
                File dir = new File(getCacheDir(), ShareProvider.DIR);
                if (!dir.exists() && !dir.mkdirs()) return false;
                File[] old = dir.listFiles();
                if (old != null) for (File f : old) //noinspection ResultOfMethodCallIgnored
                    f.delete();
                String safe = name == null ? "karta.png" : name.replaceAll("[^A-Za-z0-9._-]", "_");
                if (safe.isEmpty()) safe = "karta.png";
                File out = new File(dir, safe);
                try (FileOutputStream fo = new FileOutputStream(out)) { fo.write(bytes); }

                Uri uri = Uri.parse("content://" + getPackageName() + ".share/" + Uri.encode(safe));
                String type = mime == null || mime.isEmpty() ? "image/png" : mime;
                Intent send = new Intent(Intent.ACTION_SEND);
                send.setType(type);
                send.putExtra(Intent.EXTRA_STREAM, uri);
                if (text != null && !text.isEmpty()) send.putExtra(Intent.EXTRA_TEXT, text);
                send.setClipData(ClipData.newUri(getContentResolver(), safe, uri));
                send.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);
                runOnUiThread(() -> startActivity(Intent.createChooser(send, getString(R.string.share_card))));
                return true;
            } catch (Exception e) {
                return false;
            }
        }
    }

    private String readAsset(String name) {
        try (InputStream in = getAssets().open(name); ByteArrayOutputStream out = new ByteArrayOutputStream()) {
            byte[] buf = new byte[8192];
            int n;
            while ((n = in.read(buf)) > 0) out.write(buf, 0, n);
            return out.toString(StandardCharsets.UTF_8.name());
        } catch (Exception e) {
            return "";
        }
    }
}
