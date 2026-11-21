"""Дневник в боте: разбор «дата — запись»."""

from datetime import date

from bot.handlers.diary import parse_entry

TODAY = date(2026, 11, 21)


def test_parse_entry():
    assert parse_entry("Сдала проект", TODAY) == (TODAY, "Сдала проект")
    assert parse_entry("20.11 Сдала проект", TODAY) == (date(2026, 11, 20), "Сдала проект")
    assert parse_entry("20.11 — Сдала проект", TODAY) == (date(2026, 11, 20), "Сдала проект")
    assert parse_entry("1.3.2025: весна", TODAY) == (date(2025, 3, 1), "весна")
    # дата без года в будущем — значит прошлый год
    assert parse_entry("28.12 Ёлка", TODAY) == (date(2025, 12, 28), "Ёлка")
    assert parse_entry("31.02 нет такой даты", TODAY)[0] is None
    assert parse_entry("20.11", TODAY)[0] is None
    assert parse_entry("x" * 2001, TODAY)[0] is None
