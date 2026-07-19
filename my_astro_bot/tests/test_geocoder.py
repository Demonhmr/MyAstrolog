"""Tests for geocode_city with mocked Nominatim (no network)."""

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from geopy.exc import GeocoderTimedOut

from core import geocoder


def _location(addresstype="city", cls="place", importance=0.7):
    return SimpleNamespace(
        latitude=55.7558,
        longitude=37.6173,
        address="Москва, Россия",
        raw={"addresstype": addresstype, "class": cls, "importance": importance},
    )


def test_geocode_valid_city():
    with patch.object(geocoder._geolocator, "geocode", return_value=_location()):
        result = geocoder.geocode_city("Москва", date_context=datetime(1990, 1, 15, 14, 30))
    assert result["lat"] == pytest.approx(55.7558)
    assert result["timezone_name"] == "Europe/Moscow"
    assert result["utc_offset_hours"] == 3.0  # Moscow, January 1990 = UTC+3
    assert "Москва" in result["display_name"]


def test_geocode_not_found():
    with patch.object(geocoder._geolocator, "geocode", return_value=None):
        with pytest.raises(ValueError, match="не найден"):
            geocoder.geocode_city("Асдфгх")


def test_geocode_not_a_city():
    river = _location(addresstype="river", cls="waterway", importance=0.2)
    with patch.object(geocoder._geolocator, "geocode", return_value=river):
        with pytest.raises(ValueError, match="населённый пункт"):
            geocoder.geocode_city("Волга")


def test_geocode_service_error_becomes_friendly_valueerror():
    with patch.object(geocoder._geolocator, "geocode", side_effect=GeocoderTimedOut()):
        with pytest.raises(ValueError, match="временно недоступен"):
            geocoder.geocode_city("Москва")


def test_ambiguous_time_does_not_crash():
    """Birth during autumn DST rollback must not raise (was a NameError crash)."""
    with patch.object(geocoder._geolocator, "geocode", return_value=_location()):
        # 1990-09-30 02:30 Moscow: clocks went back — ambiguous local time
        result = geocoder.geocode_city("Москва", date_context=datetime(1990, 9, 30, 2, 30))
    assert isinstance(result["utc_offset_hours"], float)
