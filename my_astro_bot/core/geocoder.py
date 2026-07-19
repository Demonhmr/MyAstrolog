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

    raw = location.raw
    importance   = float(raw.get("importance", 0))
    address_type = raw.get("addresstype", "")
    osm_class    = raw.get("class", "")

    is_valid = (
        address_type in _VALID_PLACE_TYPES
        or osm_class == "place"
        or importance >= 0.4
    )
    if not is_valid:
        raise ValueError(
            f"«{city_name}» не распознан как населённый пункт. "
            "Пожалуйста, введи название города (например, Москва, Санкт-Петербург, London)."
        )

    lat = location.latitude
    lon = location.longitude

    tz_name = _tf.timezone_at(lat=lat, lng=lon) or "UTC"
    tz = pytz.timezone(tz_name)

    # Use provided date_context to calculate historical/correct offset
    ref_dt = date_context or datetime.now()
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
            utc_offset = localized_dt.utcoffset().total_seconds() / 3600
        else:
            utc_offset = ref_dt.astimezone(tz).utcoffset().total_seconds() / 3600
    except Exception as e:
        # Fallback to current offset if localization fails for any other reason
        logger.warning(f"UTC offset localization failed for {ref_dt} in {tz_name}: {e}. Using current offset.")
        utc_offset = datetime.now(tz).utcoffset().total_seconds() / 3600

    return {
        "lat":              lat,
        "lon":              lon,
        "timezone_name":    tz_name,
        "utc_offset_hours": utc_offset,
        "display_name":     location.address,
    }
