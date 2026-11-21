"""Сервер приложения: вход по коду, профиль, платный доступ, оплата Robokassa, дневник."""

import hashlib
from datetime import datetime, timedelta
from unittest.mock import patch
from urllib.parse import unquote, urlencode

import pytest
from fastapi.testclient import TestClient

from api import app as api_mod
from core import mailer, webstore

MOSCOW = {"name": "Москва, Россия", "lat": 55.7558, "lon": 37.6173, "tz": "Europe/Moscow"}
KAZAN = {"name": "Казань, Россия", "lat": 55.7963, "lon": 49.1088, "tz": "Europe/Moscow"}
BIRTH = {"birth_date": "1990-01-15", "birth_time": "14:30", "birth_place": MOSCOW}
EMAIL = "anya@test.invalid"


@pytest.fixture
def client(monkeypatch):
    for rl in (api_mod._rl_forecast, api_mod._rl_cities, api_mod._rl_login, api_mod._rl_diary):
        rl.hits.clear()
    api_mod._chart_cache.clear()
    monkeypatch.setenv("TEST_LOGIN_CODE", "123456")
    return TestClient(api_mod.app)


def login(client, email=EMAIL, agree=True):
    assert client.post("/api/auth/code", json={"email": email}).status_code == 200
    r = client.post("/api/auth/login", json={"email": email, "code": "123456", "agree": agree})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


@pytest.fixture
def rk(monkeypatch):
    monkeypatch.setenv("RK_LOGIN", "zvezditsa")
    monkeypatch.setenv("RK_TEST_PASS1", "tp1")
    monkeypatch.setenv("RK_TEST_PASS2", "tp2")
    monkeypatch.setenv("RK_PASS1", "p1")
    monkeypatch.setenv("RK_PASS2", "p2")
    monkeypatch.setenv("RK_TEST", "1")


def result_form(inv, out, uid, pass2="tp2", test=True):
    sig = hashlib.sha256(f"{out}:{inv}:{pass2}:Shp_uid={uid}".encode()).hexdigest().upper()
    f = {"OutSum": out, "InvId": str(inv), "SignatureValue": sig, "Shp_uid": str(uid), "Fee": "5.85"}
    if test:
        f["IsTest"] = "1"
    return urlencode(f)


# ── Вход ─────────────────────────────────────────────────────────────────────

def test_login_flow(client):
    h = login(client)
    me = client.get("/api/config", headers=h).json()
    assert me["account"]["email"] == EMAIL and me["profile"] is None and me["locked"] is False
    assert len(me["plans"]) == 5 and me["plans"][0]["rub"] == 150
    client.post("/api/auth/logout", headers=h)
    assert client.get("/api/config", headers=h).status_code == 401


def test_new_account_needs_consent(client):
    client.post("/api/auth/code", json={"email": EMAIL})
    r = client.post("/api/auth/login", json={"email": EMAIL, "code": "123456", "agree": False})
    assert r.status_code == 422 and "согласие" in r.json()["error"]
    # код не потрачен — с согласием входит
    r = client.post("/api/auth/login", json={"email": EMAIL, "code": "123456", "agree": True})
    assert r.status_code == 200 and r.json()["new"] is True


def test_code_rules(client):
    assert client.post("/api/auth/code", json={"email": "не почта"}).status_code == 422
    assert client.post("/api/auth/code", json={"email": EMAIL}).status_code == 200
    assert client.post("/api/auth/code", json={"email": EMAIL}).status_code == 429   # раз в минуту
    for _ in range(4):
        r = client.post("/api/auth/login", json={"email": EMAIL, "code": "000000", "agree": True})
        assert r.status_code == 422 and "Неверный" in r.json()["error"]
    client.post("/api/auth/login", json={"email": EMAIL, "code": "000000", "agree": True})
    r = client.post("/api/auth/login", json={"email": EMAIL, "code": "123456", "agree": True})
    assert r.status_code == 429                                                     # 5 ошибок за 15 минут


def test_real_mail_is_sent(client, monkeypatch):
    sent = {}
    monkeypatch.setattr(mailer, "send_login_code", lambda e, c: sent.update(email=e, code=c) or True)
    assert client.post("/api/auth/code", json={"email": " Anya@Example.RU "}).status_code == 200
    assert sent["email"] == "anya@example.ru" and len(sent["code"]) == 6
    r = client.post("/api/auth/login", json={"email": "anya@example.ru", "code": sent["code"], "agree": True})
    assert r.status_code == 200
    # код одноразовый
    r = client.post("/api/auth/login", json={"email": "anya@example.ru", "code": sent["code"], "agree": True})
    assert r.status_code == 422


def test_mail_failure(client, monkeypatch):
    monkeypatch.setattr(mailer, "send_login_code", lambda e, c: False)
    r = client.post("/api/auth/code", json={"email": "anya@example.ru"})
    assert r.status_code == 502
    monkeypatch.setattr(mailer, "send_login_code", lambda e, c: True)
    assert client.post("/api/auth/code", json={"email": "anya@example.ru"}).status_code == 200  # без паузы в минуту


# ── Профиль и прогноз со входом ──────────────────────────────────────────────

def test_profile_and_forecast_from_server(client):
    h = login(client)
    assert client.post("/api/forecast", json={}, headers=h).status_code == 409   # профиля ещё нет
    assert client.put("/api/profile", json=BIRTH, headers=h).status_code == 200
    d = client.post("/api/forecast", json={}, headers=h).json()
    assert d["access"] == {"status": "open", "index": 0} and d["role"]
    guest = client.post("/api/forecast", json=BIRTH).json()
    assert guest["cycle"]["start_utc"] == d["cycle"]["start_utc"]


# ── Платный доступ ───────────────────────────────────────────────────────────

def test_guest_paywall_on(client, monkeypatch):
    monkeypatch.setenv("WEB_PAYWALL", "on")
    cur = client.post("/api/forecast", json=BIRTH).json()
    assert cur["locked"] is True and cur["access"] == {"status": "locked", "index": 0}
    assert "role" not in cur and cur["cycle"]["start_text"]
    # за час до начала текущего — прошлый месяц
    at = (datetime.fromisoformat(cur["cycle"]["start_utc"].replace("Z", "+00:00")) - timedelta(hours=1)).isoformat()
    prev = client.post("/api/forecast", json={**BIRTH, "at": at}).json()
    assert prev["access"]["status"] == "free" and prev["role"]
    assert client.post("/api/chart", json=BIRTH).status_code == 402
    assert client.post("/api/chart", json={**BIRTH, "at": at}).status_code == 200
    p = client.post("/api/periods", json=BIRTH).json()
    assert p["paywall"] is True
    assert [i["status"] for i in p["items"][:3]] == ["free", "locked", "locked"]
    assert len(p["items"]) == 14


def test_paywall_test_mode_only_for_testers(client, monkeypatch):
    monkeypatch.setenv("WEB_PAYWALL", "test")
    assert client.post("/api/forecast", json=BIRTH).json().get("locked") is None   # гость — как раньше
    h = login(client)                                                               # @test.invalid — тестер
    client.put("/api/profile", json=BIRTH, headers=h)
    assert client.post("/api/forecast", json={}, headers=h).json()["locked"] is True


def test_pay_not_ready_without_shop(client, monkeypatch):
    monkeypatch.setenv("WEB_PAYWALL", "on")
    h = login(client)
    client.put("/api/profile", json=BIRTH, headers=h)
    r = client.post("/api/pay", json={"plan": "one"}, headers=h)
    assert r.status_code == 503 and "скоро" in r.json()["error"]


def test_full_payment_flow(client, monkeypatch, rk):
    monkeypatch.setenv("WEB_PAYWALL", "on")
    h = login(client)
    client.put("/api/profile", json=BIRTH, headers=h)
    acc = webstore.get_account_by_email(EMAIL)

    r = client.post("/api/pay", json={"plan": "p3"}, headers=h).json()
    f = r["fields"]
    assert r["action"].startswith("https://auth.robokassa.ru/") and r["test"] is True
    assert f["OutSum"] == "390.00" and f["IsTest"] == "1" and f["Shp_uid"] == str(acc["id"])
    assert int(f["InvId"]) >= webstore.FIRST_INV_ID
    rec = unquote(f["Receipt"])
    assert '"sum":390.00' in rec and '"tax":"none"' in rec and "3 личных месяца" in rec
    expect = hashlib.sha256(f"zvezditsa:390.00:{f['InvId']}:{f['Receipt']}:tp1:Shp_uid={acc['id']}".encode()).hexdigest()
    assert f["SignatureValue"] == expect
    inv = int(f["InvId"])
    assert client.get(f"/api/pay/{inv}", headers=h).json()["status"] == "new"

    ct = {"Content-Type": "application/x-www-form-urlencoded"}
    # подделки отвергаются
    assert client.post("/api/robokassa/result", content=result_form(inv, "390.00", acc["id"], "wrong"), headers=ct).status_code == 400
    assert client.post("/api/robokassa/result", content=result_form(inv, "1.00", acc["id"]), headers=ct).status_code == 400
    assert client.post("/api/robokassa/result", content=result_form(inv, "390.00", acc["id"] + 1), headers=ct).status_code == 400
    # настоящее уведомление — дважды, месяцы выдаются один раз
    for _ in range(2):
        r = client.post("/api/robokassa/result", content=result_form(inv, "390.00", acc["id"]), headers=ct)
        assert r.status_code == 200 and r.text == f"OK{inv}"
    st = client.get(f"/api/pay/{inv}", headers=h).json()
    assert st == {"inv": inv, "status": "paid", "plan": "p3", "granted": 3}
    o = webstore.get_order(inv)
    assert o["result_count"] == 2 and o["fee_kop"] == 585

    p = client.post("/api/periods", json={}, headers=h).json()["items"]
    assert [i["status"] for i in p[:5]] == ["free", "paid", "paid_later", "paid_later", "locked"]
    cur = client.post("/api/forecast", json={}, headers=h).json()
    assert cur["access"]["status"] == "paid" and cur["role"]
    nxt_at = p[2]["start_utc"].replace("Z", "+00:00")
    assert client.post("/api/forecast", json={"at": nxt_at}, headers=h).json()["locked"] is True

    # после оплаты дату рождения сменить нельзя, город «где сейчас» — можно
    assert client.put("/api/profile", json={**BIRTH, "birth_time": "15:00"}, headers=h).status_code == 409
    assert client.put("/api/profile", json={**BIRTH, "current_place": KAZAN}, headers=h).status_code == 200
    assert client.post("/api/forecast", json={}, headers=h).json()["cycle"]["city"].startswith("Казань")

    # «наперёд»: следующие 13 после уже оплаченных, открыты сразу
    r = client.post("/api/pay", json={"plan": "plus"}, headers=h).json()
    inv2 = int(r["fields"]["InvId"])
    client.post("/api/robokassa/result", content=result_form(inv2, "1590.00", acc["id"]), headers=ct)
    p = client.post("/api/periods", json={}, headers=h).json()["items"]
    assert [i["status"] for i in p[1:5]] == ["paid", "paid_later", "paid_later", "paid"]
    assert sum(1 for i in p if i["status"] == "paid") == 14 and len(p) == 17   # от прошлого (−1) до последнего оплаченного (15)
    far = p[-1]["start_utc"].replace("Z", "+00:00")
    assert client.post("/api/forecast", json={"at": far}, headers=h).json()["access"]["status"] == "paid"


def test_test_notification_for_real_invoice(client, monkeypatch, rk):
    monkeypatch.setenv("WEB_PAYWALL", "on")
    monkeypatch.setenv("RK_TEST", "0")
    h = login(client)
    client.put("/api/profile", json=BIRTH, headers=h)
    acc = webstore.get_account_by_email(EMAIL)
    f = client.post("/api/pay", json={"plan": "one"}, headers=h).json()["fields"]
    assert "IsTest" not in f
    inv = int(f["InvId"])
    ct = {"Content-Type": "application/x-www-form-urlencoded"}
    r = client.post("/api/robokassa/result", content=result_form(inv, "150.00", acc["id"], "p2", test=True), headers=ct)
    assert r.status_code == 400 and r.text == "test_for_real"
    r = client.post("/api/robokassa/result", content=result_form(inv, "150.00", acc["id"], "p2", test=False), headers=ct)
    assert r.text == f"OK{inv}"


def test_erase_account_keeps_orders(client, monkeypatch, rk):
    monkeypatch.setenv("WEB_PAYWALL", "on")
    h = login(client)
    client.put("/api/profile", json=BIRTH, headers=h)
    inv = int(client.post("/api/pay", json={"plan": "one"}, headers=h).json()["fields"]["InvId"])
    client.put("/api/diary/abcdef12", json={"day": "2026-11-20", "text": "Тест"}, headers=h)
    assert client.delete("/api/account", headers=h).status_code == 200
    assert webstore.get_account_by_email(EMAIL) is None
    assert webstore.get_order(inv)["account_id"] is None
    assert webstore.diary_list("w:1") == []


# ── Дневник ──────────────────────────────────────────────────────────────────

def test_diary(client):
    assert client.get("/api/diary").status_code == 401
    h = login(client)
    r = client.put("/api/diary/entry-0001", json={"day": "2026-11-20", "text": "  Сдала проект  "}, headers=h)
    assert r.status_code == 200 and r.json()["text"] == "Сдала проект"
    client.put("/api/diary/entry-0002", json={"day": "2026-11-21", "text": "Поссорилась"}, headers=h)
    client.put("/api/diary/entry-0001", json={"day": "2026-11-19", "text": "Сдала проект!"}, headers=h)
    e = client.get("/api/diary", headers=h).json()["entries"]
    assert [(x["id"], x["day"]) for x in e] == [("entry-0002", "2026-11-21"), ("entry-0001", "2026-11-19")]
    assert client.put("/api/diary/bad id", json={"day": "2026-11-20", "text": "x"}, headers=h).status_code in (404, 422)
    assert client.put("/api/diary/entry-0003", json={"day": "2026-11-20", "text": "x" * 2001}, headers=h).status_code == 422
    assert client.put("/api/diary/entry-0003", json={"day": "2026-11-20", "text": "   "}, headers=h).status_code == 422
    assert client.delete("/api/diary/entry-0002", headers=h).json() == {"deleted": True}
    # перенос с устройства: без дублей
    imp = {"entries": [{"id": "entry-0001", "day": "2026-11-19", "text": "дубль"},
                       {"id": "local-0001", "day": "2026-10-01", "text": "Старая запись",
                        "created_at": "2026-10-01T10:00:00Z"}]}
    e = client.post("/api/diary/import", json=imp, headers=h).json()["entries"]
    assert [x["text"] for x in e] == ["Сдала проект!", "Старая запись"]
    # чужой аккаунт записей не видит
    h2 = login(client, "boris@test.invalid")
    assert client.get("/api/diary", headers=h2).json()["entries"] == []


def test_cycles_for_diary(client):
    r = client.post("/api/cycles", json={**BIRTH, "from": "2026-01-01", "to": "2026-12-31"})
    items = r.json()["items"]
    assert 13 <= len(items) <= 16
    assert items[0]["start_utc"] < "2026-01-01" and items[-1]["end_utc"] > "2026-12-31"
    assert client.post("/api/cycles", json={**BIRTH, "from": "2020-01-01", "to": "2026-12-31"}).status_code == 422
