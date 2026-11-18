package ru.zvezditsa.app;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;

/** Будильник сработал: показать «Начался твой новый личный месяц» и поставить следующий. */
public class ReminderReceiver extends BroadcastReceiver {
    @Override
    public void onReceive(Context c, Intent intent) {
        Reminders.show(c);
        Reminders.scheduleNext(c);
    }
}
