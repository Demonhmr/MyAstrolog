"""
astrology.py — v3
Lunar Return calculation with pyswisseph (Swiss Ephemeris).
Geocentric calculations for planets, zero-crossing precision for return time.
"""

import swisseph as swe
import math
import logging
from datetime import datetime, timedelta
import pytz


class AstrologyEngine:
    def __init__(self):
        # Using built-in Moshier ephemeris, which is sufficiently accurate
        swe.set_ephe_path('')

    @staticmethod
    def _datetime_to_jd(dt_utc: datetime) -> float:
        """Converts UTC datetime to Julian Day."""
        h_frac = dt_utc.hour + dt_utc.minute / 60.0 + dt_utc.second / 3600.0
        return swe.julday(dt_utc.year, dt_utc.month, dt_utc.day, h_frac)

    @staticmethod
    def _jd_to_datetime(jd: float) -> datetime:
        """Converts Julian Day to UTC datetime safely using timedelta."""
        # swe.revjul returns (year, month, day, hour_float)
        y, m, d, h_frac = swe.revjul(jd)
        hour = int(h_frac)
        frac_min = (h_frac - hour) * 60
        minute = int(frac_min)
        second = round((frac_min - minute) * 60)

        # Use timedelta to safely handle any overflow (e.g. second=60, hour=24)
        try:
            dt = datetime(y, m, d, hour, minute, second)
        except ValueError:
            dt = datetime(y, m, d, hour, minute) + timedelta(seconds=second)
        return dt

    def get_lunar_return(self, name, year, month, day, hour, minute, lat, lon, utc_offset):
        """
        Calculates the Lunar Return exactly using zero-crossing on moon longitude.
        """
        # 1. Calculate Natal Moon Position
        natal_date = datetime(year, month, day, hour, minute)
        natal_utc = natal_date - timedelta(hours=utc_offset)
        
        jd_natal = self._datetime_to_jd(natal_utc)
        natal_moon, _ = swe.calc_ut(jd_natal, swe.MOON)
        natal_lon = natal_moon[0]

        # 2. Find return date — search ±14 days around today
        now_utc = datetime.utcnow()
        start_search_utc = now_utc - timedelta(days=14)
        
        start_jd = self._datetime_to_jd(start_search_utc)
        found_jd = self._find_next_return(start_jd, natal_lon)

        if not found_jd:
            logging.warning("Lunar return not found, using current UTC")
            found_jd = self._datetime_to_jd(now_utc)

        # 3. Find end date (next return)
        # Search starting from 25 days after the found date
        end_date_search_jd = found_jd + 25.0
        end_jd = self._find_next_return(end_date_search_jd, natal_lon)

        if not end_jd:
            end_jd = found_jd + 27.321  # Fallback synodic/sidereal length

        found_date_utc = self._jd_to_datetime(found_jd)
        end_date_utc = self._jd_to_datetime(end_jd)

        # We return a dict containing the properties necessary for further calculations
        chart_data = {
            "jd": found_jd,
            "lat": float(lat),
            "lon": float(lon),
        }

        return {
            "chart_data": chart_data,
            "start_date": found_date_utc,
            "end_date": end_date_utc
        }

    def _find_next_return(self, start_jd: float, natal_lon: float) -> float:
        """
        Finds the exact Julian Day when the Moon crosses the natal longitude.
        Uses 1-hour steps and linearly interpolates the exact zero-crossing.
        Handles both direct and retrograde Moon crossings.
        """
        # FIX #2: Early exit — already at the target longitude at start
        first_moon, _ = swe.calc_ut(start_jd, swe.MOON)
        first_diff = first_moon[0] - natal_lon
        if first_diff > 180: first_diff -= 360
        elif first_diff < -180: first_diff += 360
        if abs(first_diff) < 0.02:  # within ~1 arcminute
            return start_jd

        current_jd = start_jd
        prev_diff = first_diff

        # Search for 42 days (covers more than a full cycle)
        for _ in range(42 * 24):
            current_jd += 1.0 / 24.0
            curr_moon, _ = swe.calc_ut(current_jd, swe.MOON)
            curr_lon = curr_moon[0]

            # Signed difference: [-180, 180]
            diff = curr_lon - natal_lon
            if diff > 180:
                diff -= 360
            elif diff < -180:
                diff += 360

            # Direct crossing: negative → positive (Moon moves forward through target)
            if prev_diff < 0 and diff >= 0:
                total_change = diff - prev_diff
                fraction = abs(prev_diff) / total_change
                return current_jd - (1.0 / 24.0) + (fraction * (1.0 / 24.0))

            # FIX #6: Retrograde crossing: positive → negative
            if prev_diff > 0 and diff <= 0 and abs(prev_diff - diff) < 1.0:
                total_change = prev_diff - diff
                fraction = prev_diff / total_change
                return current_jd - (1.0 / 24.0) + (fraction * (1.0 / 24.0))

            prev_diff = diff

        return None

    def get_planets_data(self, chart_data):
        """
        Extracts geocentric planet positions using pyswisseph.
        Returns a list of dicts: name, sign, house, lon_deg, is_retro.
        """
        sign_names = [
            "Aries", "Taurus", "Gemini", "Cancer", "Leo", "Virgo",
            "Libra", "Scorpio", "Sagittarius", "Capricorn", "Aquarius", "Pisces",
        ]

        bodies = [
            ("Sun",     swe.SUN),
            ("Moon",    swe.MOON),
            ("Mercury", swe.MERCURY),
            ("Venus",   swe.VENUS),
            ("Mars",    swe.MARS),
            ("Jupiter", swe.JUPITER),
            ("Saturn",  swe.SATURN),
            ("Uranus",  swe.URANUS),
            ("Neptune", swe.NEPTUNE),
            ("Pluto",   swe.PLUTO),
        ]

        jd = chart_data["jd"]
        
        asc_sign = self._get_asc_sign(chart_data)
        asc_idx = sign_names.index(asc_sign)

        planets = []
        for name, body_id in bodies:
            res, _ = swe.calc_ut(jd, body_id)
            lon_deg = res[0]
            speed_lon = res[3]

            sign_idx = int(lon_deg / 30)
            sign = sign_names[sign_idx % 12]
            house_num = ((sign_idx - asc_idx) % 12) + 1

            is_retro = True if speed_lon < 0 else False

            planets.append({
                "name":     name,
                "sign":     sign,
                "house":    house_num,
                "lon_deg":  lon_deg,
                "is_retro": is_retro,
            })

        return planets

    def _get_asc_sign(self, chart_data):
        props = self.get_chart_points(chart_data)
        return props["ascendant"]

    def get_chart_points(self, chart_data):
        """Returns dict with ascendant and midheaven sign names and exact degrees."""
        sign_names = [
            "Aries", "Taurus", "Gemini", "Cancer", "Leo", "Virgo",
            "Libra", "Scorpio", "Sagittarius", "Capricorn", "Aquarius", "Pisces",
        ]

        jd = chart_data["jd"]
        lat = chart_data["lat"]
        lon = chart_data["lon"]

        # FIX #5: Use Placidus ('P') so cusps are meaningful if needed later,
        # ASC (ascmc[0]) and MC (ascmc[1]) are system-independent.
        # cusps is preserved but unused by Whole-Sign house numbering.
        cusps, ascmc = swe.houses(jd, lat, lon, b'P')

        asc_deg = ascmc[0]   # exact ecliptic longitude of Ascendant
        mc_deg  = ascmc[1]   # exact ecliptic longitude of Midheaven

        return {
            "ascendant":     sign_names[int(asc_deg / 30) % 12],
            "midheaven":     sign_names[int(mc_deg  / 30) % 12],
            # FIX #3: Expose exact degrees so chart_generator can draw them
            "ascendant_deg": asc_deg,
            "midheaven_deg": mc_deg,
        }
