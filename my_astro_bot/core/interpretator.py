"""
interpretator.py — v3
Generates forecast report, dynamics report, and LLM prompt from interpretations JSON.
All data paths are resolved relative to the package, not the working directory.
"""

import json
import re
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent  # my_astro_bot/
DATA_DIR = BASE_DIR / "data"

PLANET_RU = {
    "Sun": "Солнце", "Moon": "Луна", "Mercury": "Меркурий", "Venus": "Венера",
    "Mars": "Марс", "Jupiter": "Юпитер", "Saturn": "Сатурн",
    "Uranus": "Уран", "Neptune": "Нептун", "Pluto": "Плутон",
}

# Short house spheres for the dynamics report (ruler's house → life area)
HOUSE_SPHERES = {
    1: "личность и новые начинания", 2: "деньги и ресурсы",
    3: "общение, контакты и учёба", 4: "дом и семья",
    5: "творчество, дети и романтика", 6: "работа и здоровье",
    7: "партнёрство и отношения", 8: "кризисы, чужие ресурсы и трансформация",
    9: "путешествия, обучение и мировоззрение", 10: "карьера и статус",
    11: "друзья, планы и сообщества", 12: "уединение, подсознание и завершение дел",
}


class ReportInterpretator:
    def __init__(self, interpretations_path=None):
        path = Path(interpretations_path) if interpretations_path else (
            DATA_DIR / "interpretations" / "interpretations.json"
        )
        with open(path, "r", encoding="utf-8") as f:
            self.data = json.load(f)

    def _sanitize(self, text):
        """Remove Markdown formatting and clean up for Telegram HTML."""
        text = re.sub(r"\*\*(.*?)\*\*", r"\1", text)
        text = re.sub(r"^\s*\*\s*", "• ", text, flags=re.MULTILINE)
        text = re.sub(r"^#+\s*", "", text, flags=re.MULTILINE)
        text = re.sub(r"^---\s*$", "", text, flags=re.MULTILINE)
        # Escape & first, otherwise it would double-escape &lt;/&gt;
        text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    def _translate_sign(self, sign_en):
        translations = {
            "Aries": "Овен", "Taurus": "Телец", "Gemini": "Близнецы",
            "Cancer": "Рак", "Leo": "Лев", "Virgo": "Дева",
            "Libra": "Весы", "Scorpio": "Скорпион", "Sagittarius": "Стрелец",
            "Capricorn": "Козерог", "Aquarius": "Водолей", "Pisces": "Рыбы",
        }
        return translations.get(sign_en, sign_en)

    def generate_llm_prompt(self, sign_dom, house_dom, synth_sign, synth_house):
        """Generate a structured prompt for LLM forecast generation."""
        el_s, cr_s = sign_dom
        el_h, cr_h = house_dom

        el_s_text  = self.data["elements_sign"].get(el_s, "Описание отсутствует")
        cr_s_text  = self.data["crosses_sign"].get(cr_s, "Описание отсутствует")
        sign_text  = self.data["signs"].get(synth_sign, "Описание отсутствует")
        sign_ru    = self._translate_sign(synth_sign) if synth_sign else "Неопределён"

        el_h_text  = self.data["elements_house"].get(el_h, "Описание отсутствует")
        cr_h_text  = self.data["crosses_house"].get(cr_h, "Описание отсутствует")
        house_text = self.data["houses"].get(str(synth_house), "Описание отсутствует")

        try:
            with open(DATA_DIR / "prompts" / "forecast_prompt_template.txt", "r", encoding="utf-8") as f:
                template = f.read()
            with open(DATA_DIR / "prompts" / "forecast_examples.txt", "r", encoding="utf-8") as f:
                examples = f.read()
        except FileNotFoundError:
            return "Ошибка: Не найдены файлы шаблонов промта (data/prompts/...)"

        prompt = template.format(
            el_s_name=el_s,         el_s_text=self._sanitize(el_s_text),
            cr_s_name=cr_s,         cr_s_text=self._sanitize(cr_s_text),
            sign_name=sign_ru,      sign_text=self._sanitize(sign_text),
            el_h_name=el_h,         el_h_text=self._sanitize(el_h_text),
            cr_h_name=cr_h,         cr_h_text=self._sanitize(cr_h_text),
            house_name=f"{synth_house} Дом", house_text=self._sanitize(house_text),
            examples=examples,
        )
        return prompt

    def generate_report(self, sign_dom, house_dom, synth_sign, synth_house, dynamics):
        """Generate HTML forecast report for Telegram (≤4096 chars)."""
        synth_sign_ru = self._translate_sign(synth_sign) if synth_sign else "Неопределён"

        # FIX #4: JSON uses English keys ("Aries", not "Овен"), look up directly
        inner_text = self.data["signs"].get(synth_sign, "Описание отсутствует")
        outer_text = self.data["houses"].get(str(synth_house), "Описание отсутствует")

        inner_clean = self._sanitize(inner_text)
        outer_clean = self._sanitize(outer_text)

        def _truncate(s, n=800):
            return s[:n] + "..." if len(s) > n else s

        report = (
            f"🌙 <b>Астрологический прогноз на месяц (Лунар)</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n\n"
            f"🌀 <b>Общая энергия месяца</b>\n"
            f"Ведущее настроение: <b>{sign_dom[0]} + {sign_dom[1]}</b> ({synth_sign_ru})\n"
            f"Ведущая сфера: <b>{house_dom[0]} + {house_dom[1]}</b> (Дом {synth_house})\n\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🧱 <b>«Как я хочу» (Внутреннее состояние)</b>\n\n"
            f"{inner_clean}\n\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🏠 <b>«Как будет на самом деле» (Внешние обстоятельства)</b>\n\n"
            f"{outer_clean}\n"
        )

        if len(report) > 4000:
            report = (
                f"🌙 <b>Астрологический прогноз на месяц (Лунар)</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━\n\n"
                f"🌀 <b>Общая энергия месяца</b>\n"
                f"Настроение: <b>{sign_dom[0]} + {sign_dom[1]}</b> ({synth_sign_ru})\n"
                f"Сфера: <b>{house_dom[0]} + {house_dom[1]}</b> (Дом {synth_house})\n\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"🧱 <b>«Как я хочу»</b>\n\n"
                f"{_truncate(inner_clean)}\n\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"🏠 <b>«Как будет на самом деле»</b>\n\n"
                f"{_truncate(outer_clean)}\n"
            )
        return report

    def _ruler_line(self, ruler, house):
        """One line about a ruler planet: house + life sphere (methodology step 5.3)."""
        if not ruler or not house:
            return ""
        ruler_ru = PLANET_RU.get(ruler, ruler)
        sphere = HOUSE_SPHERES.get(int(house), "")
        sphere_part = f" — {sphere}" if sphere else ""
        return f"Управитель — <b>{ruler_ru}</b> в Доме <b>{house}</b>{sphere_part}.\n\n"

    def generate_dynamics_report(self, dynamics):
        """Generate separate HTML message with month dynamics."""
        start_en = dynamics.get("start_sign", "")
        end_en   = dynamics.get("end_sign", "")

        start_ru = self._translate_sign(start_en)
        end_ru   = self._translate_sign(end_en)

        start_text = self.data.get("sign_descriptions", {}).get(start_en, "")
        end_text   = self.data.get("sign_descriptions", {}).get(end_en, "")

        asc_ruler_line = self._ruler_line(dynamics.get("asc_ruler"), dynamics.get("asc_ruler_house"))
        mc_ruler_line  = self._ruler_line(dynamics.get("mc_ruler"),  dynamics.get("mc_ruler_house"))

        def _cap(s):
            s = self._sanitize(s) if s else "Описание отсутствует"
            return s[:1500] + "..." if len(s) > 1500 else s

        return (
            f"📅 <b>Динамика месяца</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n\n"
            f"🏁 <b>Начало месяца: Асцендент в {start_ru}</b>\n"
            f"{asc_ruler_line}"
            f"{_cap(start_text)}\n\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🎯 <b>Конец месяца: MC в {end_ru}</b>\n"
            f"{mc_ruler_line}"
            f"{_cap(end_text)}\n"
        )
