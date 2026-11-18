"""
geocoder.py — v3
City name → lat/lon/timezone via Nominatim (OSM) + TimezoneFinder (offline).

geocode_city is synchronous (network call) — call it via run_in_executor
from async handlers so it doesn't block the event loop.
"""

import logging
from datetime import datetime

from geopy.geocoders import Nominatim
from geopy.exc import GeopyError
from timezonefinder import TimezoneFinder
import pytz

logger = logging.getLogger(__name__)

_VALID_PLACE_TYPES = {
    "city", "town", "village", "municipality", "hamlet", "suburb", "borough"
}

# Module-level singletons: TimezoneFinder loads its offline polygon DB on init
# (slow, memory-heavy) and Nominatim needs a stable user_agent — never
# re-create these per request.
_geolocator = Nominatim(user_agent="my_astro_bot_v2", timeout=5)
_tf = TimezoneFinder()


def geocode_city(city_name: str, date_context: datetime = None) -> dict:
    """
    Resolve city name to coordinates and timezone.
    Calculates UTC offset for the date_context moment if provided.

    Raises ValueError with a user-friendly message on any failure.

    Returns:
        dict with keys: lat, lon, timezone_name, utc_offset_hours, display_name
    """
    try:
        location = _geolocator.geocode(
            city_name,
            addressdetails=True,
            language="ru",
            exactly_one=True,
        )
    except GeopyError as e:
        logger.warning(f"Geocoding service error for {city_name!r}: {e}")
        raise ValueError(
            "Сервис геокодинга временно недоступен. "
            "Подожди минуту и отправь название города ещё раз."
        )

    if not location:
        raise ValueError(
            f"Город «{city_name}» не найден. "
            "Попробуй ввести название на русском или английском (например, Москва, London)."
        )

    if not _is_place(location.raw):
        raise ValueError(
            f"«{city_name}» не распознан как населённый пункт. "
            "Пожалуйста, введи название города (например, Москва, Санкт-Петербург, London)."
        )

    lat = location.latitude
    lon = location.longitude

    tz_name = _tf.timezone_at(lat=lat, lng=lon) or "UTC"
    utc_offset = utc_offset_for(tz_name, date_context)

    return {
        "lat":              lat,
        "lon":              lon,
        "timezone_name":    tz_name,
        "utc_offset_hours": utc_offset,
        "display_name":     location.address,
    }


def _is_place(raw: dict) -> bool:
    """Населённый пункт, а не река, улица или магазин."""
    return (
        raw.get("addresstype", "") in _VALID_PLACE_TYPES
        or raw.get("class", "") == "place"
        or float(raw.get("importance", 0)) >= 0.4
    )


def utc_offset_for(tz_name: str, ref_dt: datetime = None) -> float:
    """
    Смещение от UTC (часы) в поясе tz_name в момент ref_dt (местное время).
    Учитывает исторические переходы; без ref_dt — текущее смещение.
    """
    tz = pytz.timezone(tz_name)
    ref_dt = ref_dt or datetime.now()
    try:
        if ref_dt.tzinfo is None:
            # We assume the user entered LOCAL time for the given city
            # localize handles historical DST/offset shifts
            try:
                localized_dt = tz.localize(ref_dt, is_dst=None)
            except pytz.exceptions.AmbiguousTimeError:
                # Clock was turned back: two valid offsets exist. Choose DST=True (summer) as safer.
                logger.warning(
                    f"AmbiguousTimeError for {ref_dt} in {tz_name} "
                    f"(clock change overlap). Using DST=True (summer offset)."
                )
                localized_dt = tz.localize(ref_dt, is_dst=True)
            except pytz.exceptions.NonExistentTimeError:
                # Clock was turned forward: this local time never existed. Use DST=True.
                logger.warning(
                    f"NonExistentTimeError for {ref_dt} in {tz_name} "
                    f"(spring-forward gap). Using DST=True."
                )
                localized_dt = tz.localize(ref_dt, is_dst=True)
            return localized_dt.utcoffset().total_seconds() / 3600
        return ref_dt.astimezone(tz).utcoffset().total_seconds() / 3600
    except Exception as e:
        # Fallback to current offset if localization fails for any other reason
        logger.warning(f"UTC offset localization failed for {ref_dt} in {tz_name}: {e}. Using current offset.")
        return datetime.now(tz).utcoffset().total_seconds() / 3600


_REGION_TYPES = {"country", "state", "region", "province", "county", "district", "state_district"}


def _short_name(raw: dict) -> str:
    """«Великий Новгород, Новгородская область, Россия» вместо полного адреса."""
    addr = raw.get("address") or {}
    parts = [
        raw.get("name") or addr.get("city") or addr.get("town") or addr.get("village"),
        addr.get("state") or addr.get("region"),
        addr.get("country"),
    ]
    out = []
    for p in parts:
        if p and p not in out:
            out.append(p)
    return ", ".join(out)


def search_cities(query: str, limit: int = 5) -> list:
    """
    Несколько вариантов города для выбора в приложении.
    Возвращает [{name, lat, lon, tz}]; пустой список — ничего не нашлось.
    ValueError — сервис недоступен.
    """
    try:
        found = _geolocator.geocode(
            query, addressdetails=True, language="ru", exactly_one=False, limit=limit * 2,
        ) or []
    except GeopyError as e:
        logger.warning(f"Geocoding service error: {e}")
        raise ValueError("Сервис поиска городов временно недоступен. Попробуй через минуту.")

    out, seen = [], set()
    for loc in found:
        raw = loc.raw
        if raw.get("addresstype") in _REGION_TYPES or not _is_place(raw):
            continue
        name = _short_name(raw) or loc.address
        key = (round(loc.latitude, 1), round(loc.longitude, 1))
        if key in seen or name in seen:
            continue
        seen.update((key, name))
        out.append({
            "name": name,
            "lat": round(loc.latitude, 5),
            "lon": round(loc.longitude, 5),
            "tz": _tf.timezone_at(lat=loc.latitude, lng=loc.longitude) or "UTC",
        })
        if len(out) >= limit:
            break
    return out
