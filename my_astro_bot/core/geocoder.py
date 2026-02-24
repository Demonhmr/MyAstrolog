"""
geocoder.py — v2
City name → lat/lon/timezone via Nominatim (OSM) + TimezoneFinder (offline).
"""

from datetime import datetime
from geopy.geocoders import Nominatim
from timezonefinder import TimezoneFinder
import pytz

_VALID_PLACE_TYPES = {
    "city", "town", "village", "municipality", "hamlet", "suburb", "borough"
}


def geocode_city(city_name: str) -> dict:
    """
    Resolve city name to coordinates and timezone.

    Returns:
        dict with keys: lat, lon, timezone_name, utc_offset_hours, display_name
    Raises:
        ValueError if city not found or result is not a populated place.
    """
    geolocator = Nominatim(user_agent="my_astro_bot_v2")
    location = geolocator.geocode(
        city_name,
        addressdetails=True,
        language="ru",
        exactly_one=True,
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

    tf = TimezoneFinder()
    tz_name = tf.timezone_at(lat=lat, lng=lon) or "UTC"
    tz = pytz.timezone(tz_name)
    utc_offset = datetime.now(tz).utcoffset().total_seconds() / 3600

    return {
        "lat":              lat,
        "lon":              lon,
        "timezone_name":    tz_name,
        "utc_offset_hours": utc_offset,
        "display_name":     location.address,
    }
