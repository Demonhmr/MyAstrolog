"""
report.py — прогноз в виде структуры (JSON) для веб-приложения и Android.

Тексты те же, что у бота (словарь в core/texts.py), но без разметки Telegram:
приложение верстает их само. Все строки — обычный текст, без HTML.
"""

import re
from typing import Optional

from core import texts
from core.forecast import Forecast


def _iso(dt) -> str:
    return dt.isoformat(timespec="seconds")


def _iso_utc(dt) -> str:
    """naive UTC → 2026-11-08T14:24:54Z"""
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _role(sign) -> Optional[dict]:
    if sign not in texts.ROLES:
        return None
    title, what = texts.ROLES[sign]
    return {
        "sign": sign, "sign_ru": texts.SIGN_RU[sign], "symbol": texts.SIGN_SYMBOL[sign],
        "title": title, "text": f"Тебе захочется {what}.",
    }


def _task(house) -> Optional[dict]:
    try:
        h = int(house)
        title, what = texts.HOUSE_TASKS[h]
    except (TypeError, ValueError, KeyError):
        return None
    return {"house": h, "title": title, "text": f"Больше всего внимания потребуют {what}."}


def _inner_outer(f: Forecast) -> dict:
    return {
        "inner": (
            f"Хочется {texts.WANT_ELEMENT.get(f.el_s, '…')}. "
            f"Твой стиль — {texts.WANT_CROSS.get(f.cr_s, '…')}."
        ),
        "outer": (
            f"{texts.LIFE_ELEMENT.get(f.el_h, '…').capitalize()}. "
            f"Темп — {texts.LIFE_CROSS.get(f.cr_h, '…')}."
        ),
    }


def story_sections(f: Forecast, interp_data: dict) -> list:
    """Текст «как хочешь / как будет» из справочника — та же логика, что render_story_fallback."""
    sign_text = interp_data.get("signs", {}).get(f.synth_sign, "")
    house_text = interp_data.get("houses", {}).get(str(f.synth_house), "")
    stem = texts.SIGN_RU.get(f.synth_sign, "")[:4]

    wants = []
    for keyword in ("Желания", "Мотивации", "Потребности"):
        wants = texts._section_items(sign_text, keyword, 5, skip=stem)
        if wants:
            break
    wants = wants or texts.FALLBACK_WANTS.get(f.synth_sign, [])
    life = texts._section_paragraph(house_text, "Жизнь заставляет")
    lessons = texts._section_items(house_text, "Чему учит", 3)
    tips = texts._section_items(house_text, "Рекомендации", 3)

    out = []
    if wants:
        out.append({"title": "Тебе захочется", "items": wants})
    if life:
        out.append({"title": "А жизнь тебе", "text": life})
    if lessons:
        out.append({"title": "Чему учат обстоятельства", "items": lessons})
    if tips:
        out.append({"title": "Что поможет", "items": tips})
    return out


def _dynamics(f: Forecast, interp_data: dict) -> dict:
    d = f.dynamics
    descr = interp_data.get("sign_descriptions", {})

    def part(sign, house):
        raw = re.sub(r"^\s*\*\*[^*]+\*\*\s*[-–—]\s*это\s+", "", descr.get(sign, ""))
        txt = texts._first_sentences(raw[:1].upper() + raw[1:], 380)
        sphere = None
        try:
            sphere = texts.HOUSE_TASKS[int(house)][0]
        except (TypeError, ValueError, KeyError):
            pass
        return {"sign": sign, "sign_ru": texts.SIGN_RU.get(sign), "text": txt, "sphere": sphere}

    return {
        "start": part(d["start_sign"], d.get("asc_ruler_house")),
        "end": part(d["end_sign"], d.get("mc_ruler_house")),
    }


def _expert(f: Forecast) -> dict:
    planets = []
    for p in f.planets:
        deg_in_sign = p["lon_deg"] % 30
        planets.append({
            "name": p["name"],
            "name_ru": texts.PLANET_RU.get(p["name"], p["name"]),
            "sign": p["sign"],
            "sign_ru": texts.SIGN_RU[p["sign"]],
            "deg": int(deg_in_sign),
            "min": int((deg_in_sign - int(deg_in_sign)) * 60),
            "retro": bool(p.get("is_retro")),
            "house": p["house"],
        })

    def scores(d):
        return [[k, v] for k, v in sorted(d.items(), key=lambda x: -x[1])]

    pts, dyn = f.points, f.dynamics
    return {
        "method": "Лунарный возврат, Swiss Ephemeris, дома от знака Асцендента",
        "cycle_start_utc": _iso_utc(f.cycle_start_utc),
        "planets": planets,
        "sign_scores": {"elements": scores(f.sign_scores["elements"]),
                        "crosses": scores(f.sign_scores["crosses"])},
        "house_scores": {"elements": scores(f.house_scores["elements"]),
                         "crosses": scores(f.house_scores["crosses"])},
        "synth_sign": {"sign_ru": texts.SIGN_RU.get(f.synth_sign), "element": f.el_s, "cross": f.cr_s},
        "synth_house": {"house": f.synth_house, "element": f.el_h, "cross": f.cr_h},
        "asc": {"sign_ru": texts.SIGN_RU[pts["ascendant"]], "deg": int(pts["ascendant_deg"] % 30),
                "ruler_ru": texts.PLANET_RU.get(dyn.get("asc_ruler")), "ruler_house": dyn.get("asc_ruler_house")},
        "mc": {"sign_ru": texts.SIGN_RU[pts["midheaven"]], "deg": int(pts["midheaven_deg"] % 30),
               "ruler_ru": texts.PLANET_RU.get(dyn.get("mc_ruler")), "ruler_house": dyn.get("mc_ruler_house")},
    }


def build_report(f: Forecast, interp_data: dict, story: Optional[dict] = None) -> dict:
    """
    story — {"source": "llm", "text": "..."} от нейросети; без него берётся справочник.
    """
    return {
        "cycle": {
            "start": _iso(f.start_local), "end": _iso(f.end_local),
            "start_utc": _iso_utc(f.cycle_start_utc), "end_utc": _iso_utc(f.cycle_end_utc),
            "start_text": texts.fmt_dt(f.start_local), "end_text": texts.fmt_dt(f.end_local),
            "tz": f.tz, "city": f.city,
        },
        "time_known": f.time_known,
        "role": _role(f.synth_sign),
        "task": _task(f.synth_house),
        "climate": _inner_outer(f),
        "story": story or {"source": "dictionary", "sections": story_sections(f, interp_data)},
        "dynamics": _dynamics(f, interp_data),
        "expert": _expert(f),
    }
