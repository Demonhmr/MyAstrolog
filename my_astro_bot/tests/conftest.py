"""Общие фикстуры: временная база и тестовый профиль."""

import pytest

from core import storage


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "test.db"))
    storage.init_db()
    return storage


@pytest.fixture
def profile():
    return storage.Profile(
        user_id=42, chat_id=42, name="Аня",
        birth_date="15.01.1990", birth_time="14:30", time_known=True,
        birth_city="Москва", birth_lat=55.7558, birth_lon=37.6173,
        birth_utc_offset=3.0, birth_tz="Europe/Moscow",
        cur_city="Москва", cur_lat=55.7558, cur_lon=37.6173, cur_tz="Europe/Moscow",
    )
