"""
api/app.py — сервер расчёта для веб-приложения и Android (zvezditsa.ru/api/).

Сервер ничего не хранит: данные рождения приходят в запросе, прогноз считается
и отдаётся, в журнал они не пишутся. Профиль живёт на устройстве пользователя.

  GET  /api/health
  GET  /api/cities?q=Казань      варианты города (Nominatim, с кэшем и паузой 1 с)
  POST /api/forecast             прогноз на личный месяц (JSON)
  POST /api/chart                картинка карты (PNG) для того же запроса

Запуск: uvicorn api.app:app --host 127.0.0.1 --port 8090 (из папки my_astro_bot).
Нейросеть пока не подключена: текст «как хочешь / как будет» — из справочника.
"""

import asyncio
import json
import logging
import os
import time
from collections import OrderedDict, defaultdict, deque
from datetime import date, datetime, timedelta
from typing import Optional

import pytz
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field, field_validator

from core import geocoder
from core.astrology import utcnow_naive
from core.chart_generator import generate_chart_png
from core.forecast import Forecast, build_forecast
from core.interpretator import DATA_DIR
from core.report import build_report
from core.storage import Profile
from core.texts import fmt_date

logger = logging.getLogger("zvezditsa.api")

API_VERSION = "1"
UNKNOWN_TIME = "12:00"

_interp_data = json.loads((DATA_DIR / "interpretations" / "interpretations.json").read_text("utf-8"))

app = FastAPI(title="Звездица API", version=API_VERSION, docs_url=None, redoc_url=None, openapi_url=None)


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


class ForecastIn(BaseModel):
    birth_date: date
    birth_time: Optional[str] = Field(default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    birth_place: Place
    current_place: Optional[Place] = None     # нет — там же, где родился
    at: Optional[datetime] = None             # момент внутри нужного месяца (UTC); нет — сейчас

    @field_validator("birth_date")
    @classmethod
    def _bd(cls, v):
        if not (date(1900, 1, 1) <= v <= date.today()):
            raise ValueError("дата рождения вне диапазона")
        return v


def _profile(body: ForecastIn) -> Profile:
    bt = body.birth_time or UNKNOWN_TIME
    hh, mm = map(int, bt.split(":"))
    b = body.birth_place
    c = body.current_place or b
    offset = geocoder.utc_offset_for(
        b.tz, datetime(body.birth_date.year, body.birth_date.month, body.birth_date.day, hh, mm)
    )
    return Profile(
        user_id=0, chat_id=0, name="",
        birth_date=body.birth_date.strftime("%d.%m.%Y"), birth_time=bt,
        time_known=body.birth_time is not None,
        birth_city=b.name, birth_lat=b.lat, birth_lon=b.lon, birth_utc_offset=offset, birth_tz=b.tz,
        cur_city=c.name[:80], cur_lat=c.lat, cur_lon=c.lon, cur_tz=c.tz,
    )


def _at(body: ForecastIn) -> Optional[datetime]:
    if body.at is None:
        return None
    at = body.at
    if at.tzinfo is not None:
        at = at.astimezone(pytz.utc).replace(tzinfo=None)
    now = utcnow_naive()
    # Разумные рамки: прошлый год … два года вперёд
    if not (now - timedelta(days=366) <= at <= now + timedelta(days=731)):
        raise HTTPException(422, "Дата вне доступного диапазона")
    return at


# ── Защита от перегрузки ──────────────────────────────────────────────────────

_heavy = asyncio.Semaphore(int(os.getenv("API_CONCURRENCY", "2")))


class RateLimit:
    """Скользящее окно на IP: не больше n запросов за period секунд."""

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


_rl_forecast = RateLimit(int(os.getenv("RL_FORECAST", "40")), 600)
_rl_cities = RateLimit(int(os.getenv("RL_CITIES", "30")), 60)


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


# ── Прогноз и карта ───────────────────────────────────────────────────────────

async def _forecast(request: Request, body: ForecastIn) -> Forecast:
    _rl_forecast.check(_ip(request))
    profile, at = _profile(body), _at(body)
    async with _heavy:
        try:
            return await asyncio.to_thread(build_forecast, profile, at)
        except Exception:
            # Без данных пользователя в журнале — только тип ошибки
            logger.exception("forecast failed")
            raise HTTPException(500, "Не удалось рассчитать прогноз")


@app.post("/api/forecast")
async def forecast(request: Request, body: ForecastIn):
    f = await _forecast(request, body)
    return build_report(f, _interp_data)


_chart_cache = LRU(200)


@app.post("/api/chart")
async def chart(request: Request, body: ForecastIn):
    f = await _forecast(request, body)
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
