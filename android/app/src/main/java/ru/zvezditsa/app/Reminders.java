package ru.zvezditsa.app;

import android.Manifest;
import android.app.AlarmManager;
import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.os.Build;

import org.json.JSONArray;

/**
 * Напоминание «начался новый личный месяц».
 * Страница присылает моменты начала следующих месяцев (мс UTC), они лежат в SharedPreferences.
 * Будильник ставится на ближайший будущий; сработал — показываем уведомление и ставим следующий.
 * Точные будильники не нужны (для них Android 14 требует отдельного разрешения): опоздание на несколько
 * минут в режиме сна для такого напоминания не важно.
 */
final class Reminders {
    static final String EXTRA_FROM_NOTIF = "from_reminder";
    private static final String PREFS = "reminders";
    private static final String KEY_TIMES = "times";
    private static final String CHANNEL = "new_month";
    private static final int NOTIF_ID = 1;

    private Reminders() {}

    static void save(Context c, String timesJson) {
        prefs(c).edit().putString(KEY_TIMES, timesJson == null ? "[]" : timesJson).apply();
    }

    static void cancel(Context c) {
        prefs(c).edit().remove(KEY_TIMES).apply();
        AlarmManager am = (AlarmManager) c.getSystemService(Context.ALARM_SERVICE);
        if (am != null) am.cancel(alarmIntent(c));
    }

    /** Ставит будильник на ближайший момент из списка, который ещё не наступил. */
    static void scheduleNext(Context c) {
        AlarmManager am = (AlarmManager) c.getSystemService(Context.ALARM_SERVICE);
        if (am == null) return;
        long next = nextTime(c, System.currentTimeMillis() + 30_000);
        PendingIntent pi = alarmIntent(c);
        if (next <= 0) { am.cancel(pi); return; }
        am.setAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, next, pi);
    }

    static long nextTime(Context c, long after) {
        long best = 0;
        try {
            JSONArray a = new JSONArray(prefs(c).getString(KEY_TIMES, "[]"));
            for (int i = 0; i < a.length(); i++) {
                long t = a.optLong(i, 0);
                if (t > after && (best == 0 || t < best)) best = t;
            }
        } catch (Exception ignored) { /* испорченный список — напоминаний нет */ }
        return best;
    }

    static void ensureChannel(Context c) {
        if (Build.VERSION.SDK_INT < 26) return;
        NotificationManager nm = c.getSystemService(NotificationManager.class);
        if (nm == null || nm.getNotificationChannel(CHANNEL) != null) return;
        NotificationChannel ch = new NotificationChannel(CHANNEL, c.getString(R.string.channel_name), NotificationManager.IMPORTANCE_DEFAULT);
        ch.setDescription(c.getString(R.string.channel_desc));
        nm.createNotificationChannel(ch);
    }

    static void show(Context c) {
        if (Build.VERSION.SDK_INT >= 33
            && c.checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) return;
        ensureChannel(c);
        Intent open = new Intent(c, MainActivity.class)
            .putExtra(EXTRA_FROM_NOTIF, true)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_SINGLE_TOP);
        PendingIntent tap = PendingIntent.getActivity(c, 0, open, PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);

        Notification.Builder b = Build.VERSION.SDK_INT >= 26 ? new Notification.Builder(c, CHANNEL) : new Notification.Builder(c);
        b.setSmallIcon(R.drawable.ic_notif)
         .setColor(c.getColor(R.color.gold))
         .setContentTitle(c.getString(R.string.notif_title))
         .setContentText(c.getString(R.string.notif_text))
         .setContentIntent(tap)
         .setAutoCancel(true);
        NotificationManager nm = (NotificationManager) c.getSystemService(Context.NOTIFICATION_SERVICE);
        if (nm != null) nm.notify(NOTIF_ID, b.build());
    }

    private static PendingIntent alarmIntent(Context c) {
        Intent i = new Intent(c, ReminderReceiver.class);
        return PendingIntent.getBroadcast(c, 0, i, PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
    }

    private static SharedPreferences prefs(Context c) {
        return c.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
    }
}
