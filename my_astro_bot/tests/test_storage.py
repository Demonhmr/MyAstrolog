"""Профили, напоминания, подписка и архив прогнозов в SQLite."""

from dataclasses import replace
from datetime import datetime, timedelta


def test_save_and_get_profile(db, profile):
    db.save_profile(profile)
    got = db.get_profile(42)
    assert got.name == "Аня"
    assert got.time_known is True
    assert got.reminders_on is True
    assert db.get_profile(999) is None


def test_update_keeps_premium(db, profile):
    db.save_profile(profile)
    until = datetime(2030, 1, 1)
    db.set_premium_until(42, until)
    db.save_profile(replace(profile, cur_city="Казань", premium_until=None))
    got = db.get_profile(42)
    assert got.cur_city == "Казань"
    assert got.premium_until == until.isoformat(timespec="seconds")
    assert got.is_premium(now=datetime(2029, 1, 1))
    assert not got.is_premium(now=datetime(2031, 1, 1))


def test_due_profiles(db, profile):
    db.save_profile(profile)
    db.save_profile(replace(profile, user_id=43, chat_id=43))
    now = datetime(2026, 10, 24, 12, 0)
    db.set_next_cycle(42, now - timedelta(hours=1))      # уже начался
    db.set_next_cycle(43, now + timedelta(days=3))       # ещё нет
    assert [p.user_id for p in db.due_profiles(now)] == [42]

    db.set_reminders(42, False)
    assert db.due_profiles(now) == []


def test_story_cache_and_delete(db, profile):
    db.save_profile(profile)
    start, end = datetime(2026, 10, 8, 9, 18), datetime(2026, 11, 4, 15, 21)
    assert db.get_story(42, start) is None
    db.save_story(42, start, end, "текст")
    assert db.get_story(42, start) == "текст"
    db.save_story(42, start, end, "новый текст")
    assert db.get_story(42, start) == "новый текст"

    db.delete_user(42)
    assert db.get_profile(42) is None
    assert db.get_story(42, start) is None
