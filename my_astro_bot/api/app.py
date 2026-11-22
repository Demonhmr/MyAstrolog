"""
api/app.py — сервер приложения Звездицы (zvezditsa.ru/api/) для сайта и Android.

Без входа сервер ничего не хранит: данные рождения приходят в запросе, прогноз
считается и отдаётся. Со входом (код на почту) на сервере живут данные рождения,
оплаченные личные месяцы и дневник — они одинаковы на всех устройствах.

  GET  /api/health
  GET  /api/cities?q=Казань           варианты города (Nominatim, кэш, 1 запрос/с)
  GET  /api/config                    тарифы, платный ли доступ, аккаунт и профиль
  POST /api/auth/code {email}         код на почту
  POST /api/auth/login {email, code, agree}
  POST /api/auth/logout
  DELETE /api/account                 удалить аккаунт и всё, что с ним связано
  PUT  /api/profile                   данные рождения (после оплаты — только «где сейчас»)
  POST /api/forecast                  прогноз на личный месяц (или «закрыт» с датами)
  POST /api/story                     живой текст нейросети к прогнозу (если story_pending)
  POST /api/chart                     картинка карты (PNG)
  POST /api/periods                   личные месяцы с доступом: прошлый, текущий, будущие
  POST /api/cycles {from, to}         границы личных месяцев за период (для дневника)
  GET/PUT/DELETE /api/diary[/{id}]    дневник; POST /api/diary/import — перенос с устройства
  POST /api/pay {plan}                счёт Robokassa → форма оплаты
  GET  /api/pay/{inv}                 оплачен ли счёт
  POST /api/robokassa/result          уведомление Robokassa (ResultURL)

Запросы с данными рождения без входа: поля birth_* в теле. Со входом — заголовок
Authorization: Bearer <токен>, данные берутся из профиля на сервере.

Платный доступ (WEB_PAYWALL): off — всё открыто; test — тарифы работают только для адресов
из PAYWALL_TEST_EMAILS и @test.invalid (проверка оплаты до запуска); on — для всех.
Запуск: uvicorn api.app:app --host 127.0.0.1 --port 8090 (из папки my_astro_bot).
"""

import asyncio
import json
import logging
import os
import re
import time
from collections import OrderedDict, defaultdict, deque
from datetime import date, datetime, timedelta
from typing import List, Optional
from urllib.parse import parse_qsl

import pytz
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, PlainTextResponse, Response
from pydantic import BaseModel, Field, field_validator

from core import geocoder, llm, mailer, periods, plans, robokassa, storage, webstore
from core.astrology import utcnow_naive
from core.chart_generator import generate_chart_png
from core.forecast import Forecast, build_forecast
from core.interpretator import DATA_DIR, ReportInterpretator
from core.report import build_report
from core.storage import Profile
from core.texts import fmt_date, fmt_dt

logger = logging.getLogger("zvezditsa.api")

API_VERSION = "2"
UNKNOWN_TIME = "12:00"
CONSENT_VERSION = "web-v2-2026-11-21"   # редакция согласия для аккаунта (landing/consent.html)

_interp_data = json.loads((DATA_DIR / "interpretations" / "interpretations.json").read_text("utf-8"))
_interp = ReportInterpretator()

app = FastAPI(title="Звездица API", version=API_VERSION, docs_url=None, redoc_url=None, openapi_url=None)


# ── База ─────────────────────────────────────────────────────────────────────

_db_inited = None


def _db():
    """База создаётся при первом обращении (и заново, если путь сменился — в тестах)."""
    global _db_inited
    path = str(storage.db_path())
    if _db_inited != path:
        storage.init_db()
        _db_inited = path


# ── Входные данные ────────────────────────────────────────────────────────────

class Place(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    tz: str

    @field_validator("tz")
    @classmethod
    def _tz(cls, v):
        if v not in pytz.all_timezones_set:
            raise ValueError("неизвестный часовой пояс")
        return v


class Birth(BaseModel):
    birth_date: date
    birth_time: Optional[str] = Field(default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    birth_place: Place
    current_place: Optional[Place] = None     # нет — там же, где родился

    @field_validator("birth_date")
    @classmethod
    def _bd(cls, v):
        if not (date(1900, 1, 1) <= v <= date.today()):
            raise ValueError("дата рождения вне диапазона")
        return v


class ForecastIn(BaseModel):
    # без входа — данные рождения обязательны; со входом берутся из профиля
    birth_date: Optional[date] = None
    birth_time: Optional[str] = Field(default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    birth_place: Optional[Place] = None
    current_place: Optional[Place] = None
    at: Optional[datetime] = None             # момент внутри нужного месяца (UTC); нет — сейчас

    @field_validator("birth_date")
    @classmethod
    def _bd(cls, v):
        if v is not None and not (date(1900, 1, 1) <= v <= date.today()):
            raise ValueError("дата рождения вне диапазона")
        return v


def _birth_dict(b) -> dict:
    return {
        "birth_date": b.birth_date.isoformat(), "birth_time": b.birth_time,
        "birth_place": b.birth_place.model_dump(),
        "current_place": b.current_place.model_dump() if b.current_place else None,
    }


def _profile(d: dict) -> Profile:
    """Словарь профиля (как в приложении) → Profile ядра расчёта."""
    bt = d.get("birth_time") or UNKNOWN_TIME
    hh, mm = map(int, bt.split(":"))
    y, mo, dd = map(int, d["birth_date"].split("-"))
    b = d["birth_place"]
    c = d.get("current_place") or b
    offset = geocoder.utc_offset_for(b["tz"], datetime(y, mo, dd, hh, mm))
    return Profile(
        user_id=0, chat_id=0, name="",
        birth_date=f"{dd:02d}.{mo:02d}.{y:04d}", birth_time=bt,
        time_known=d.get("birth_time") is not None,
        birth_city=b["name"], birth_lat=b["lat"], birth_lon=b["lon"], birth_utc_offset=offset, birth_tz=b["tz"],
        cur_city=c["name"][:80], cur_lat=c["lat"], cur_lon=c["lon"], cur_tz=c["tz"],
    )


def _place_key(d: dict) -> str:
    c = d.get("current_place") or d["birth_place"]
    return f'{c["name"]}|{round(c["lat"], 3)}|{round(c["lon"], 3)}|{c["tz"]}'


def _at(at: Optional[datetime]) -> Optional[datetime]:
    if at is None:
        return None
    if at.tzinfo is not None:
        at = at.astimezone(pytz.utc).replace(tzinfo=None)
    now = utcnow_naive()
    # Разумные рамки: прошлый год … оплаченное наперёд (до ~3 лет)
    if not (now - timedelta(days=366) <= at <= now + timedelta(days=1100)):
        raise HTTPException(422, "Дата вне доступного диапазона")
    return at


# ── Защита от перегрузки ──────────────────────────────────────────────────────

_heavy = asyncio.Semaphore(int(os.getenv("API_CONCURRENCY", "2")))


class RateLimit:
    """Скользящее окно на ключ (IP): не больше n запросов за period секунд."""

    def __init__(self, n: int, period: float):
        self.n, self.period = n, period
        self.hits = defaultdict(deque)

    def check(self, ip: str):
        now = time.monotonic()
        q = self.hits[ip]
        while q and now - q[0] > self.period:
            q.popleft()
        if len(q) >= self.n:
            raise HTTPException(429, "Слишком много запросов. Подожди минуту.")
        q.append(now)
        if len(self.hits) > 10000:  # чистка старых адресов
            for k in [k for k, v in self.hits.items() if not v or now - v[-1] > self.period]:
                del self.hits[k]


# Мобильные операторы сажают многих абонентов на один IP — лимит с запасом; процессор бережёт _heavy
_rl_forecast = RateLimit(int(os.getenv("RL_FORECAST", "120")), 600)
_rl_cities = RateLimit(int(os.getenv("RL_CITIES", "30")), 60)
_rl_login = RateLimit(int(os.getenv("RL_LOGIN", "30")), 600)
_rl_diary = RateLimit(int(os.getenv("RL_DIARY", "240")), 600)


def _ip(request: Request) -> str:
    # nginx на этом же сервере кладёт адрес клиента в X-Real-IP
    return request.headers.get("x-real-ip") or (request.client.host if request.client else "?")


class LRU(OrderedDict):
    def __init__(self, size: int):
        super().__init__()
        self.size = size

    def get(self, k):
        if k in self:
            self.move_to_end(k)
            return self[k]
        return None

    def put(self, k, v):
        self[k] = v
        self.move_to_end(k)
        while len(self) > self.size:
            self.popitem(last=False)


# ── Аккаунт и платный доступ ─────────────────────────────────────────────────

def _token(request: Request) -> Optional[str]:
    h = request.headers.get("authorization") or ""
    return h[7:].strip() if h.lower().startswith("bearer ") else None


def _account(request: Request, required: bool = False) -> Optional[dict]:
    tok = _token(request)
    if not tok:
        if required:
            raise HTTPException(401, "Войди по почте, чтобы продолжить")
        return None
    _db()
    acc_id = webstore.session_account(tok)
    acc = webstore.get_account(acc_id) if acc_id else None
    if not acc:
        # токен устарел — приложение выйдет из аккаунта и покажет вход
        raise HTTPException(401, "Вход устарел. Войди по почте ещё раз.")
    return acc


def _paywall_mode() -> str:
    m = (os.getenv("WEB_PAYWALL") or "off").strip().lower()
    return m if m in ("off", "test", "on") else "off"


def _paywall_for(acc: Optional[dict]) -> bool:
    mode = _paywall_mode()
    if mode == "on":
        return True
    if mode == "test" and acc:
        testers = {e.strip().lower() for e in (os.getenv("PAYWALL_TEST_EMAILS") or "").split(",") if e.strip()}
        return acc["email"] in testers or acc["email"].endswith("@test.invalid")
    return False


def _who(request: Request, body: Optional[ForecastIn]):
    """→ (аккаунт или None, словарь профиля). Со входом профиль — с сервера."""
    acc = _account(request)
    if acc:
        prof = webstore.get_web_profile(acc["id"])
        if not prof:
            raise HTTPException(409, "Сначала заполни данные рождения")
        return acc, prof
    if body is None or body.birth_date is None or body.birth_place is None:
        raise HTTPException(422, "Проверь данные")
    return None, _birth_dict(body)


def _cycle_json(c: periods.Cycle, tz: str) -> dict:
    zone = pytz.timezone(tz)
    s = pytz.utc.localize(c.start).astimezone(zone)
    e = pytz.utc.localize(c.end).astimezone(zone)
    return {
        "index": c.index,
        "start": s.isoformat(timespec="seconds"), "end": e.isoformat(timespec="seconds"),
        "start_utc": c.start.strftime("%Y-%m-%dT%H:%M:%SZ"), "end_utc": c.end.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "start_text": fmt_dt(s), "end_text": fmt_dt(e),
        "start_date": fmt_date(s) + (f" {s.year}" if s.year != utcnow_naive().year else ""),
        "end_date": fmt_date(e) + (f" {e.year}" if e.year != utcnow_naive().year else ""),
    }


def _calendar(prof: dict, now: datetime) -> periods.CycleCalendar:
    return periods.CycleCalendar(_profile(prof), now)


def _access(acc: Optional[dict], prof: dict, at: Optional[datetime]):
    """→ (месяц, статус, календарь) для момента at."""
    now = utcnow_naive()
    cal = _calendar(prof, now)
    idx = cal.index_of(at) if at else 0
    if idx > periods.MAX_AHEAD:
        raise HTTPException(422, "Дата вне доступного диапазона")
    cyc = cal.cycle(idx)
    grants = webstore.grants_of(webstore.web_owner(acc["id"])) if acc else []
    return cyc, periods.status(cyc, grants, now, _paywall_for(acc)), cal


# ── Поиск городов ─────────────────────────────────────────────────────────────

_city_cache = LRU(3000)
_nominatim_lock = asyncio.Lock()
_nominatim_last = 0.0


@app.get("/api/cities")
async def cities(request: Request, q: str = Query(min_length=2, max_length=100)):
    key = " ".join(q.lower().split())
    cached = _city_cache.get(key)
    if cached is not None:
        return {"cities": cached}
    _rl_cities.check(_ip(request))

    global _nominatim_last
    async with _nominatim_lock:  # правила Nominatim: не чаще 1 запроса в секунду
        wait = 1.0 - (time.monotonic() - _nominatim_last)
        if wait > 0:
            await asyncio.sleep(wait)
        try:
            found = await asyncio.to_thread(geocoder.search_cities, q.strip())
        except ValueError as e:
            raise HTTPException(503, str(e))
        finally:
            _nominatim_last = time.monotonic()
    _city_cache.put(key, found)
    return {"cities": found}


# ── Настройки для приложения ─────────────────────────────────────────────────

def _me(acc: Optional[dict]) -> dict:
    out = {
        "paywall": _paywall_for(acc),
        "pay_ready": robokassa.ready(),
        "plans": [plans.as_json(p) for p in plans.plans().values()],
        "consent_version": CONSENT_VERSION,
        "account": None, "profile": None, "locked": False,
    }
    if acc:
        out["account"] = {"email": acc["email"], "consent_ok": acc["consent_version"] == CONSENT_VERSION}
        out["profile"] = webstore.get_web_profile(acc["id"])
        out["locked"] = webstore.has_grants(webstore.web_owner(acc["id"]))
    return out


@app.get("/api/config")
async def config(request: Request):
    _db()
    return _me(_account(request))


# ── Вход по коду из письма ───────────────────────────────────────────────────

EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]+\.[^@\s]{2,}$")


def _email(v: str) -> str:
    e = (v or "").strip().lower()
    if len(e) > 254 or not EMAIL_RE.match(e):
        raise HTTPException(422, "Проверь адрес почты")
    return e


class CodeIn(BaseModel):
    email: str = Field(max_length=254)


class LoginIn(BaseModel):
    email: str = Field(max_length=254)
    code: str = Field(max_length=12)
    agree: bool = False


def _test_code(email: str) -> Optional[str]:
    """Адреса @test.invalid писем не получают: их код — TEST_LOGIN_CODE (для автотестов), если он задан."""
    code = os.getenv("TEST_LOGIN_CODE")
    return code if code and email.endswith("@test.invalid") else None


@app.post("/api/auth/code")
async def auth_code(request: Request, body: CodeIn):
    _db()
    email, ip = _email(body.email), _ip(request)
    n = webstore.code_counts(email, ip)
    if n["last"] and utcnow_naive() - n["last"] < timedelta(seconds=60):
        raise HTTPException(429, "Код уже отправлен. Новый можно запросить через минуту.")
    if n["email_hour"] >= 5 or n["ip_hour"] >= 20:
        raise HTTPException(429, "Слишком много кодов за час. Попробуй позже.")
    test = _test_code(email)
    if test is None and email.endswith("@test.invalid"):
        raise HTTPException(422, "Проверь адрес почты")
    code = webstore.new_code(email, ip, test)
    if test is None:
        sent = await asyncio.to_thread(mailer.send_login_code, email, code)
        if not sent:
            webstore.drop_code(email)
            raise HTTPException(502, "Не получилось отправить письмо. Попробуй ещё раз чуть позже.")
    return {"sent": True, "ttl_min": int(webstore.CODE_TTL.total_seconds() // 60)}


@app.post("/api/auth/login")
async def auth_login(request: Request, body: LoginIn):
    _db()
    _rl_login.check(_ip(request))
    email = _email(body.email)
    code = re.sub(r"\D", "", body.code)
    if webstore.recent_fails(email) >= 5:
        raise HTTPException(429, "Слишком много неверных кодов. Подожди 15 минут и запроси новый.")
    acc = webstore.get_account_by_email(email)
    if not acc and not body.agree:
        # новый аккаунт — только с согласием (код не тратим)
        raise HTTPException(422, "Нужно согласие на обработку данных")
    res = webstore.check_code(email, code)
    if res == "expired":
        raise HTTPException(422, "Код устарел. Запроси новый.")
    if res == "bad":
        raise HTTPException(422, "Неверный код. Проверь письмо.")
    new = acc is None
    if new:
        acc_id = webstore.create_account(email, CONSENT_VERSION)
    else:
        acc_id = acc["id"]
        if body.agree and acc["consent_version"] != CONSENT_VERSION:
            webstore.set_consent(acc_id, CONSENT_VERSION)
    token = webstore.new_session(acc_id)
    return {"token": token, "new": new, **_me(webstore.get_account(acc_id))}


@app.post("/api/auth/logout")
async def auth_logout(request: Request):
    tok = _token(request)
    if tok:
        _db()
        webstore.end_session(tok)
    return {"ok": True}


class ConsentIn(BaseModel):
    agree: bool


@app.post("/api/account/consent")
async def account_consent(request: Request, body: ConsentIn):
    acc = _account(request, required=True)
    if not body.agree:
        raise HTTPException(422, "Нужно согласие на обработку данных")
    webstore.set_consent(acc["id"], CONSENT_VERSION)
    return _me(webstore.get_account(acc["id"]))


@app.delete("/api/account")
async def account_delete(request: Request):
    acc = _account(request, required=True)
    webstore.erase_account(acc["id"])
    logger.info("account erased: %s", acc["id"])
    return {"ok": True}


# ── Профиль ──────────────────────────────────────────────────────────────────

@app.put("/api/profile")
async def profile_put(request: Request, body: Birth):
    acc = _account(request, required=True)
    new = _birth_dict(body)
    old = webstore.get_web_profile(acc["id"])
    if old and webstore.has_grants(webstore.web_owner(acc["id"])):
        same = (old["birth_date"] == new["birth_date"] and old["birth_time"] == new["birth_time"]
                and old["birth_place"] == new["birth_place"])
        if not same:
            # оплаченные месяцы привязаны к человеку: дату, время и место рождения меняет поддержка
            raise HTTPException(409, "После оплаты дату, время и город рождения меняет поддержка. "
                                     "Город, где ты сейчас, можно менять.")
    webstore.save_web_profile(acc["id"], new)
    return _me(acc)


# ── Прогноз и карта ───────────────────────────────────────────────────────────

async def _forecast(prof: dict, at: Optional[datetime]) -> Forecast:
    async with _heavy:
        try:
            return await asyncio.to_thread(build_forecast, _profile(prof), at)
        except Exception:
            # Без данных пользователя в журнале — только тип ошибки
            logger.exception("forecast failed")
            raise HTTPException(500, "Не удалось рассчитать прогноз")


async def _gate(request: Request, body: ForecastIn):
    _rl_forecast.check(_ip(request))
    _db()
    acc, prof = _who(request, body)
    at = _at(body.at)
    cyc, st, cal = await asyncio.to_thread(_access, acc, prof, at)
    return acc, prof, cyc, st


@app.post("/api/forecast")
async def forecast(request: Request, body: ForecastIn):
    acc, prof, cyc, st = await _gate(request, body)
    access = {"status": st, "index": cyc.index}
    if st not in periods.ACCESSIBLE:
        tz = (prof.get("current_place") or prof["birth_place"])["tz"]
        return {"locked": True, "access": access, "cycle": {**_cycle_json(cyc, tz), "tz": tz,
                "city": (prof.get("current_place") or prof["birth_place"])["name"]},
                "time_known": prof.get("birth_time") is not None}
    owner = webstore.web_owner(acc["id"]) if acc else None
    key = _place_key(prof)
    if owner and st == periods.PAID:
        snap = webstore.cached_report(owner, cyc.start, key)
        if snap:
            return {**_with_story(snap), "access": access}
    f = await _forecast(prof, _mid(cyc))
    rep = build_report(f, _interp_data)
    rep["story_key"] = _story_key(f)
    if owner and st == periods.PAID:
        webstore.save_report(owner, cyc.start, key, rep)
    return {**_with_story(rep), "access": access}


# ── Живой текст нейросети ─────────────────────────────────────────────────────
# Промпт зависит только от сочетания стихий, крестов, знака и дома (без ПД),
# поэтому текст пишется один раз на сочетание и хранится общим (webstore.llm_stories).
# /api/forecast отдаёт готовый текст или справочник с story_pending — тогда
# приложение просит /api/story и подменяет текст, не задерживая показ прогноза.

_story_jobs: dict = {}          # key → asyncio.Task: одно сочетание пишется один раз


def _mid(cyc) -> datetime:
    # момент внутри месяца: середина — не зависит от секундных расхождений границ
    return cyc.start + (cyc.end - cyc.start) / 2


def _story_key(f: Forecast) -> str:
    return llm.story_key(f.el_s, f.cr_s, f.el_h, f.cr_h, f.synth_sign, f.synth_house)


def _llm_daily_limit() -> int:
    try:
        return int(os.getenv("LLM_WEB_DAILY", "300"))
    except ValueError:
        return 300


def _with_story(rep: dict) -> dict:
    key = rep.get("story_key")
    if not key or rep["story"].get("source") == "llm":
        return rep
    text = webstore.llm_story(key)
    if text:
        return {**rep, "story": {"source": "llm", "text": text}}
    if llm.is_configured() and _llm_daily_limit() > 0:
        return {**rep, "story_pending": True}
    return rep


async def _write_story(key: str, f: Forecast) -> Optional[str]:
    text = await asyncio.to_thread(webstore.llm_story, key)
    if text:
        return text
    since = utcnow_naive() - timedelta(days=1)
    if await asyncio.to_thread(webstore.llm_stories_since, since) >= _llm_daily_limit():
        logger.warning("LLM daily limit reached")
        return None
    prompt = _interp.generate_llm_prompt((f.el_s, f.cr_s), (f.el_h, f.cr_h), f.synth_sign, f.synth_house)
    text = await llm.write_story(prompt)
    if text:
        await asyncio.to_thread(webstore.save_llm_story, key, llm.model(), text)
    return text


@app.post("/api/story")
async def story(request: Request, body: ForecastIn):
    acc, prof, cyc, st = await _gate(request, body)
    if st not in periods.ACCESSIBLE:
        raise HTTPException(402, "Этот личный месяц закрыт")
    if not llm.is_configured():
        return {"story": None}
    f = await _forecast(prof, _mid(cyc))
    key = _story_key(f)
    job = _story_jobs.get(key)
    if job is None:
        job = asyncio.ensure_future(_write_story(key, f))
        _story_jobs[key] = job
        job.add_done_callback(lambda _j, k=key: _story_jobs.pop(k, None))
    try:
        # shield: обрыв связи у одного клиента не отменяет текст для остальных
        text = await asyncio.shield(job)
    except Exception:
        logger.exception("story failed")
        text = None
    return {"story": {"source": "llm", "text": text} if text else None}


_chart_cache = LRU(200)


@app.post("/api/chart")
async def chart(request: Request, body: ForecastIn):
    acc, prof, cyc, st = await _gate(request, body)
    if st not in periods.ACCESSIBLE:
        raise HTTPException(402, "Этот личный месяц закрыт")
    f = await _forecast(prof, cyc.start + (cyc.end - cyc.start) / 2)
    key = (f.cycle_start_utc.isoformat(), round(f.points["ascendant_deg"], 2), f.city)
    png = _chart_cache.get(key)
    if png is None:
        async with _heavy:
            png = await asyncio.to_thread(
                generate_chart_png,
                planets=f.planets, chart_points=f.points,
                name="Личный месяц",
                birth_date=fmt_date(f.start_local), birth_time=f.start_local.strftime("%H:%M"),
                city=f.city.split(",")[0][:40],
                chart_title="Карта неба на начало личного месяца",
                footer="★ Звездица",
            )
        _chart_cache.put(key, png)
    return Response(png, media_type="image/png", headers={"Cache-Control": "private, max-age=86400"})


# ── Личные месяцы ─────────────────────────────────────────────────────────────

def _periods(acc: Optional[dict], prof: dict) -> dict:
    now = utcnow_naive()
    cal = _calendar(prof, now)
    grants = webstore.grants_of(webstore.web_owner(acc["id"])) if acc else []
    paywall = _paywall_for(acc)
    last = max(12, periods.last_granted_index(cal, grants)) if paywall else 3
    tz = (prof.get("current_place") or prof["birth_place"])["tz"]
    items = []
    for c in cal.cycles(-1, last):
        items.append({**_cycle_json(c, tz), "status": periods.status(c, grants, now, paywall)})
    return {"paywall": paywall, "items": items}


@app.post("/api/periods")
async def periods_list(request: Request, body: ForecastIn):
    _rl_forecast.check(_ip(request))
    _db()
    acc, prof = _who(request, body)
    return await asyncio.to_thread(_periods, acc, prof)


class CyclesIn(ForecastIn):
    date_from: date = Field(alias="from")
    date_to: date = Field(alias="to")


@app.post("/api/cycles")
async def cycles_between(request: Request, body: CyclesIn):
    """Границы личных месяцев, пересекающих [from, to] (для дневника). Не больше ~3 лет."""
    _rl_forecast.check(_ip(request))
    _db()
    acc, prof = _who(request, body)
    if body.date_to < body.date_from or (body.date_to - body.date_from).days > 1100:
        raise HTTPException(422, "Слишком большой период")

    def run():
        cal = _calendar(prof, utcnow_naive())
        a = cal.index_of(datetime.combine(body.date_from, datetime.min.time()) - timedelta(days=1))
        b = cal.index_of(datetime.combine(body.date_to, datetime.min.time()) + timedelta(days=2))
        tz = (prof.get("current_place") or prof["birth_place"])["tz"]
        return {"items": [_cycle_json(c, tz) for c in cal.cycles(a, b)]}

    return await asyncio.to_thread(run)


# ── Дневник ──────────────────────────────────────────────────────────────────

ID_RE = re.compile(r"^[A-Za-z0-9_-]{6,40}$")


class DiaryIn(BaseModel):
    day: date
    text: str = Field(min_length=1, max_length=webstore.DIARY_MAX_TEXT)


class DiaryItem(DiaryIn):
    id: str
    created_at: Optional[datetime] = None


class DiaryImport(BaseModel):
    entries: List[DiaryItem] = Field(max_length=1000)


def _check_entry(entry_id: str, day: date, text: str):
    if not ID_RE.match(entry_id):
        raise HTTPException(422, "Проверь данные")
    if not (date(1900, 1, 1) <= day <= date.today() + timedelta(days=800)):
        raise HTTPException(422, "Проверь дату записи")
    if not text.strip():
        raise HTTPException(422, "Запись пустая")


def _diary_owner(request: Request) -> str:
    _rl_diary.check(_ip(request))
    return webstore.web_owner(_account(request, required=True)["id"])


@app.get("/api/diary")
async def diary_get(request: Request):
    return {"entries": webstore.diary_list(_diary_owner(request))}


@app.put("/api/diary/{entry_id}")
async def diary_put(request: Request, entry_id: str, body: DiaryIn):
    owner = _diary_owner(request)
    _check_entry(entry_id, body.day, body.text)
    if not webstore.diary_exists(owner, entry_id) and webstore.diary_count(owner) >= webstore.DIARY_MAX_ENTRIES:
        raise HTTPException(409, "В дневнике слишком много записей")
    return webstore.diary_put(owner, entry_id, body.day.isoformat(), body.text.strip())


@app.delete("/api/diary/{entry_id}")
async def diary_del(request: Request, entry_id: str):
    owner = _diary_owner(request)
    if not ID_RE.match(entry_id):
        raise HTTPException(422, "Проверь данные")
    return {"deleted": webstore.diary_delete(owner, entry_id)}


@app.post("/api/diary/import")
async def diary_import(request: Request, body: DiaryImport):
    """Записи с устройства → в аккаунт (после входа). Уже перенесённые — не дублируются."""
    owner = _diary_owner(request)
    for e in body.entries:
        _check_entry(e.id, e.day, e.text)
    room = webstore.DIARY_MAX_ENTRIES - webstore.diary_count(owner)
    for e in body.entries:
        if webstore.diary_exists(owner, e.id):
            continue
        if room <= 0:
            break
        created = e.created_at.astimezone(pytz.utc).replace(tzinfo=None) if e.created_at and e.created_at.tzinfo \
            else e.created_at
        webstore.diary_put(owner, e.id, e.day.isoformat(), e.text.strip(),
                           created.isoformat(timespec="seconds") if created else None)
        room -= 1
    return {"entries": webstore.diary_list(owner)}


# ── Оплата ───────────────────────────────────────────────────────────────────

class PayIn(BaseModel):
    plan: str = Field(max_length=16)


@app.post("/api/pay")
async def pay(request: Request, body: PayIn):
    acc = _account(request, required=True)
    plan = plans.get(body.plan)
    if not plan:
        raise HTTPException(422, "Такого тарифа нет")
    if not _paywall_for(acc):
        raise HTTPException(409, "Сейчас все прогнозы открыты бесплатно")
    if not robokassa.ready():
        raise HTTPException(503, "Оплата скоро заработает. Попробуй позже.")
    if not webstore.get_web_profile(acc["id"]):
        raise HTTPException(409, "Сначала заполни данные рождения")
    test = robokassa.test_mode()
    kop = plan.rub * 100
    inv = webstore.create_order(acc["id"], plan.code, kop, test)
    form = robokassa.invoice(inv, kop, acc["id"], f"Звездица: {plan.title}", plan.receipt, acc["email"], test)
    return {"inv": inv, "test": test, **form}


@app.get("/api/pay/{inv}")
async def pay_status(request: Request, inv: int):
    acc = _account(request, required=True)
    o = webstore.get_order(inv)
    if not o or o["account_id"] != acc["id"]:
        raise HTTPException(404, "Счёт не найден")
    return {"inv": inv, "status": o["status"], "plan": o["plan"], "granted": o["granted"]}


def _grant_for_order(conn, order: dict):
    """Выдача месяцев по оплаченному счёту (внутри транзакции pay_order)."""
    plan = plans.get(order["plan"])
    if order["account_id"] is None:
        return 0, "account_erased"
    prof = webstore.get_web_profile(order["account_id"])
    if not plan or not prof:
        return 0, "no_profile" if plan else "unknown_plan"
    owner = webstore.web_owner(order["account_id"])
    rows = conn.execute("SELECT cycle_start, preview FROM grants WHERE owner = ?", (owner,)).fetchall()
    grants = [periods.Grant(datetime.fromisoformat(r["cycle_start"]), bool(r["preview"])) for r in rows]
    cal = _calendar(prof, utcnow_naive())
    cycles = periods.cycles_to_grant(cal, grants, plan.months)
    n = webstore.add_grants(conn, owner, cycles, plan.code, f"rk:{order['id']}", plan.preview)
    return n, None


@app.post("/api/robokassa/result")
async def robokassa_result(request: Request):
    _db()
    raw = (await request.body()).decode("utf-8", "replace")
    form = dict(parse_qsl(raw, keep_blank_values=True))
    if not form and request.query_params:   # на случай метода GET в настройках магазина
        form = dict(request.query_params)
    try:
        inv = int(form.get("InvId", ""))
    except ValueError:
        return PlainTextResponse("bad request", status_code=400)
    order = webstore.get_order(inv)
    reason = robokassa.check_result(form, order) if order else "unknown_inv"
    if reason:
        logger.warning("robokassa result rejected: inv=%s reason=%s", inv, reason)
        return PlainTextResponse(reason, status_code=400)
    o = await asyncio.to_thread(webstore.pay_order, inv, robokassa.fee_kop(form), _grant_for_order)
    logger.info("robokassa paid: inv=%s plan=%s first=%s", inv, o["plan"], o["first"])
    return PlainTextResponse(f"OK{inv}")


@app.get("/api/health")
async def health():
    return {"ok": True, "version": API_VERSION}


@app.exception_handler(HTTPException)
async def _http_error(request: Request, exc: HTTPException):
    return JSONResponse({"error": exc.detail}, status_code=exc.status_code)


@app.exception_handler(RequestValidationError)
async def _bad_input(request: Request, exc: RequestValidationError):
    fields = sorted({".".join(str(x) for x in e.get("loc", [])[1:]) for e in exc.errors()})
    return JSONResponse({"error": "Проверь данные", "fields": fields}, status_code=422)
