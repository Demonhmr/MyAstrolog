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


def test_update_profile(db, profile):
    db.save_profile(profile)
    db.save_profile(replace(profile, cur_city="Казань"))
    assert db.get_profile(42).cur_city == "Казань"


def test_delete_user_removes_diary_and_grants_keeps_payments(db, profile):
    from core import webstore
    db.save_profile(profile)
    webstore.diary_put("t:42", "abcdef12", "2026-11-20", "запись")
    db.record_stars_payment(42, "one", 100, "XTR", "ch-x",
                            lambda c: webstore.add_grants(c, "t:42", [], "one", "tg:ch-x", False))
    webstore.grant_cycles("t:42", [], "one", "x", False)
    db.delete_user(42)
    assert webstore.diary_list("t:42") == [] and webstore.grants_of("t:42") == []
    assert len(db.payments_of(42)) == 1


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


def test_set_consent(db, profile):
    db.save_profile(replace(profile, consent_version="v1-2026-10-24", consent_at="2026-10-24T10:00:00"))
    db.set_consent(42, "bot-v2-2026-11-21", "2026-11-21T09:00:00")
    got = db.get_profile(42)
    assert got.consent_version == "bot-v2-2026-11-21"
    assert got.consent_at == "2026-11-21T09:00:00"
