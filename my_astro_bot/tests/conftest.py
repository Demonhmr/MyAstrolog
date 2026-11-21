"""Общие фикстуры: временная база и тестовый профиль."""

import pytest

from core import storage


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    """Каждый тест — со своей пустой базой; платный доступ и оплата выключены, пока тест не включит."""
    monkeypatch.setenv("DB_PATH", str(tmp_path / "auto.db"))
    for k in ("WEB_PAYWALL", "PAYWALL_TEST_EMAILS", "RK_LOGIN", "RK_PASS1", "RK_PASS2",
              "RK_TEST_PASS1", "RK_TEST_PASS2", "RK_TEST", "TEST_LOGIN_CODE", "PAYWALL_ENABLED"):
        monkeypatch.delenv(k, raising=False)


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
