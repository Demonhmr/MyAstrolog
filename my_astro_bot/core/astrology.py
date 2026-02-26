"""
astrology.py — v2
Lunar Return calculation with fixed ±14-day search window, retrograde detection.
"""

import ephem
import math
import logging
from datetime import datetime, timedelta
import pytz


class AstrologyEngine:
    def __init__(self):
        pass

    def get_lunar_return(self, name, year, month, day, hour, minute, lat, lon, utc_offset):
        """
        Calculates the Lunar Return chart observer and cycle dates.
        """
        # 1. Calculate Natal Moon Position
        natal_date = datetime(year, month, day, hour, minute)
        natal_utc = natal_date - timedelta(hours=utc_offset)

        observer = ephem.Observer()
        observer.lat = str(lat)
        observer.lon = str(lon)
        observer.date = natal_utc

        moon = ephem.Moon(observer)
        natal_ecl = ephem.Ecliptic(moon)
        natal_lon_rad = natal_ecl.lon

        # 2. Find return date — search ±14 days around today
        now_utc = datetime.utcnow()
        start_search = now_utc - timedelta(days=14)

        found_date_utc = self._find_next_return(observer, moon, natal_lon_rad, start_search)

        if not found_date_utc:
            logging.warning("Lunar return not found, using current UTC")
            found_date_utc = now_utc

        # 3. Find end date (next return)
        # Search starting from 25 days after the found date
        end_date_search = found_date_utc + timedelta(days=25)
        end_date_utc = self._find_next_return(observer, moon, natal_lon_rad, end_date_search)

        if not end_date_utc:
            end_date_utc = found_date_utc + timedelta(days=27, hours=8) # Fallback

        observer.date = found_date_utc
        return {
            "observer": observer,
            "start_date": found_date_utc,
            "end_date": end_date_utc
        }

    def _find_next_return(self, observer, moon, natal_lon_rad, start_from_utc):
        current_date_utc = start_from_utc
        # Search for 42 days (covers more than a full cycle)
        for _ in range(42 * 24):
            observer.date = current_date_utc
            moon.compute(observer)
            curr_ecl = ephem.Ecliptic(moon)

            diff = abs(curr_ecl.lon - natal_lon_rad)
            if diff > math.pi:
                diff = 2 * math.pi - diff

            if diff < 0.01:  # ~0.57°
                return current_date_utc

            current_date_utc += timedelta(hours=1)
        return None

    def get_planets_data(self, observer):
        """
        Extracts planet positions from an Ephem observer context.
        Returns a list of dicts: name, sign, house, lon_deg, is_retro.
        """
        sign_names = [
            "Aries", "Taurus", "Gemini", "Cancer", "Leo", "Virgo",
            "Libra", "Scorpio", "Sagittarius", "Capricorn", "Aquarius", "Pisces",
        ]

        bodies = [
            ("Sun",     ephem.Sun(observer)),
            ("Moon",    ephem.Moon(observer)),
            ("Mercury", ephem.Mercury(observer)),
            ("Venus",   ephem.Venus(observer)),
            ("Mars",    ephem.Mars(observer)),
            ("Jupiter", ephem.Jupiter(observer)),
            ("Saturn",  ephem.Saturn(observer)),
            ("Uranus",  ephem.Uranus(observer)),
            ("Neptune", ephem.Neptune(observer)),
            ("Pluto",   ephem.Pluto(observer)),
        ]

        # Pre-compute observer for retrograde check (+1 day)
        observer_next = ephem.Observer()
        observer_next.lat = observer.lat
        observer_next.lon = observer.lon
        observer_next.date = ephem.Date(observer.date + 1)

        asc_sign = self._get_asc_sign(observer)
        asc_idx = sign_names.index(asc_sign)

        planets = []
        for name, body in bodies:
            body.compute(observer)
            ecl = ephem.Ecliptic(body)
            lon_deg = math.degrees(ecl.lon)

            sign_idx = int(lon_deg / 30)
            sign = sign_names[sign_idx % 12]
            house_num = ((sign_idx - asc_idx) % 12) + 1

            # Retrograde: position decreasing over next 24h
            body_class = type(body)
            body_next = body_class(observer_next)
            body_next.compute(observer_next)
            ecl_next = ephem.Ecliptic(body_next)
            lon_next = math.degrees(ecl_next.lon)
            delta = lon_next - lon_deg
            if delta > 180:
                delta -= 360
            if delta < -180:
                delta += 360
            is_retro = delta < 0

            planets.append({
                "name":     name,
                "sign":     sign,
                "house":    house_num,
                "lon_deg":  lon_deg,
                "is_retro": is_retro,
            })

        return planets

    def _get_asc_sign(self, observer):
        props = self.get_chart_points(observer)
        return props["ascendant"]

    def get_chart_points(self, observer):
        """Returns dict with ascendant and midheaven sign names."""
        lst = observer.sidereal_time()
        lat = observer.lat
        eps = math.radians(23.44)   # obliquity of ecliptic

        ramc = lst
        denom = -math.sin(ramc) * math.cos(eps) + (-math.tan(lat) * math.sin(eps))
        numer = math.cos(ramc)

        asc_rad = math.atan2(numer, denom)
        asc_deg = math.degrees(asc_rad)
        if asc_deg < 0:
            asc_deg += 360

        mc_rad = math.atan2(math.sin(ramc), math.cos(ramc) * math.cos(eps))
        mc_deg = math.degrees(mc_rad)
        if mc_deg < 0:
            mc_deg += 360

        sign_names = [
            "Aries", "Taurus", "Gemini", "Cancer", "Leo", "Virgo",
            "Libra", "Scorpio", "Sagittarius", "Capricorn", "Aquarius", "Pisces",
        ]
        return {
            "ascendant": sign_names[int(asc_deg / 30) % 12],
            "midheaven": sign_names[int(mc_deg / 30) % 12],
        }
