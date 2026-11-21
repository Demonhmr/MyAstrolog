"""
robokassa.py — счета и уведомления об оплате Robokassa (как у Волпеня, см. ~/projects/MK/server/sql/005).

Счёт: форма POST на https://auth.robokassa.ru/Merchant/Index.aspx с полями
  MerchantLogin, OutSum, InvId, Description, SignatureValue, Shp_uid, Receipt, Culture, Encoding, [IsTest], [Email]
  подпись = hash(MerchantLogin:OutSum:InvId:Receipt:Пароль#1:Shp_uid=…)
Receipt — номенклатура для чека самозанятого («Мой налог»): JSON одной позицией, URL-кодированный один раз;
в форме браузер кодирует его ещё раз — так и требует Robokassa.

Уведомление (ResultURL, POST): OutSum, InvId, SignatureValue, Shp_uid, [IsTest], [Fee]
  подпись = hash(OutSum:InvId:Пароль#2:Shp_uid=…), ответ «OK<InvId>».

Настройки (.env): RK_LOGIN, RK_PASS1, RK_PASS2 (боевые), RK_TEST_PASS1, RK_TEST_PASS2 (тестовые),
RK_TEST=1 — счета в тестовом режиме, RK_HASH=sha256 (как в технических настройках магазина).
"""

import hashlib
import hmac
import os
from typing import Optional
from urllib.parse import quote

URL = "https://auth.robokassa.ru/Merchant/Index.aspx"


def _env(k: str) -> str:
    return (os.getenv(k) or "").strip()


def test_mode() -> bool:
    return _env("RK_TEST") != "0"


def _pass(n: int, test: bool) -> str:
    return _env(f"RK_TEST_PASS{n}" if test else f"RK_PASS{n}")


def ready() -> bool:
    """Можно ли выставлять счета: логин и пароли текущего режима заданы."""
    return bool(_env("RK_LOGIN") and _pass(1, test_mode()) and _pass(2, test_mode()))


def _hash(s: str) -> str:
    algo = _env("RK_HASH") or "sha256"
    return hashlib.new(algo, s.encode("utf-8")).hexdigest()


def rub(kop: int) -> str:
    """15000 → '150.00' (формат OutSum)."""
    return f"{kop // 100}.{kop % 100:02d}"


def receipt(name: str, kop: int) -> str:
    # имя без кавычек и обратных слэшей — JSON собирается строкой, как в Волпене
    name = name.replace('"', "").replace("\\", "")[:128]
    raw = ('{"items":[{"name":"' + name + '","quantity":1,"sum":' + rub(kop) +
           ',"payment_method":"full_payment","payment_object":"service","tax":"none"}]}')
    return quote(raw, safe="")


def invoice(inv_id: int, kop: int, account_id: int, description: str, receipt_name: str,
            email: Optional[str], test: bool) -> dict:
    login = _env("RK_LOGIN")
    out = rub(kop)
    rec = receipt(receipt_name, kop)
    sig = _hash(f"{login}:{out}:{inv_id}:{rec}:{_pass(1, test)}:Shp_uid={account_id}")
    fields = {
        "MerchantLogin": login, "OutSum": out, "InvId": str(inv_id),
        "Description": description[:100], "SignatureValue": sig, "Shp_uid": str(account_id),
        "Receipt": rec, "Culture": "ru", "Encoding": "utf-8",
    }
    if email:
        fields["Email"] = email      # подставится в форму оплаты: туда придёт чек
    if test:
        fields["IsTest"] = "1"
    return {"action": URL, "fields": fields}


def check_result(form: dict, order: dict) -> Optional[str]:
    """None — уведомление верное, иначе причина отказа."""
    out, inv, sig, uid = form.get("OutSum"), form.get("InvId"), form.get("SignatureValue"), form.get("Shp_uid")
    if not (out and inv and sig and uid):
        return "bad_request"
    if order.get("account_id") is not None and str(order["account_id"]) != uid:
        return "bad_uid"
    n_test = form.get("IsTest") == "1"
    if n_test and not order["is_test"]:
        # IsTest не входит в подпись: боевой счёт нельзя «оплатить» в тестовом режиме
        return "test_for_real"
    p2 = _pass(2, bool(order["is_test"]))
    if not p2:
        return "no_secret"
    if not hmac.compare_digest(sig.lower(), _hash(f"{out}:{inv}:{p2}:Shp_uid={uid}").lower()):
        return "bad_sign"
    try:
        if round(float(out) * 100) != order["amount_kop"]:
            return "bad_sum"
    except ValueError:
        return "bad_request"
    return None


def fee_kop(form: dict) -> Optional[int]:
    try:
        return round(float(form["Fee"]) * 100)
    except (KeyError, ValueError, TypeError):
        return None
