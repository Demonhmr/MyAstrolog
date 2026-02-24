"""
calculator.py — v2
Scoring engine: elements / crosses by sign and house, dominants, synthetic sign/house.
"""


class AstroCalculator:
    WEIGHTS = {
        "Sun": 5, "Moon": 5, "Mercury": 3, "Venus": 3, "Mars": 3,
        "Jupiter": 2, "Saturn": 2, "Uranus": 1, "Neptune": 1, "Pluto": 1,
    }

    ZODIAC = {
        "Aries":       {"element": "Огонь",  "cross": "Кардинальный"},
        "Taurus":      {"element": "Земля",  "cross": "Фиксированный"},
        "Gemini":      {"element": "Воздух", "cross": "Мутабельный"},
        "Cancer":      {"element": "Вода",   "cross": "Кардинальный"},
        "Leo":         {"element": "Огонь",  "cross": "Фиксированный"},
        "Virgo":       {"element": "Земля",  "cross": "Мутабельный"},
        "Libra":       {"element": "Воздух", "cross": "Кардинальный"},
        "Scorpio":     {"element": "Вода",   "cross": "Фиксированный"},
        "Sagittarius": {"element": "Огонь",  "cross": "Мутабельный"},
        "Capricorn":   {"element": "Земля",  "cross": "Кардинальный"},
        "Aquarius":    {"element": "Воздух", "cross": "Фиксированный"},
        "Pisces":      {"element": "Вода",   "cross": "Мутабельный"},
    }

    # Houses: 1,5,9=Fire | 2,6,10=Earth | 3,7,11=Air | 4,8,12=Water
    # 1,4,7,10=Cardinal | 2,5,8,11=Fixed | 3,6,9,12=Mutable
    HOUSE_PROPS = {
        1:  {"element": "Огонь",  "cross": "Кардинальный"},
        2:  {"element": "Земля",  "cross": "Фиксированный"},
        3:  {"element": "Воздух", "cross": "Мутабельный"},
        4:  {"element": "Вода",   "cross": "Кардинальный"},
        5:  {"element": "Огонь",  "cross": "Фиксированный"},
        6:  {"element": "Земля",  "cross": "Мутабельный"},
        7:  {"element": "Воздух", "cross": "Кардинальный"},
        8:  {"element": "Вода",   "cross": "Фиксированный"},
        9:  {"element": "Огонь",  "cross": "Мутабельный"},
        10: {"element": "Земля",  "cross": "Кардинальный"},
        11: {"element": "Воздух", "cross": "Фиксированный"},
        12: {"element": "Вода",   "cross": "Мутабельный"},
    }

    def calculate_scores(self, planets):
        sign_scores  = {"elements": {}, "crosses": {}}
        house_scores = {"elements": {}, "crosses": {}}

        for p in planets:
            name = p["name"]
            weight = self.WEIGHTS.get(name, 0)
            if not weight:
                continue

            # By sign
            props = self.ZODIAC.get(p["sign"])
            if props:
                el = props["element"]
                cr = props["cross"]
                sign_scores["elements"][el] = sign_scores["elements"].get(el, 0) + weight
                sign_scores["crosses"][cr]  = sign_scores["crosses"].get(cr, 0)  + weight

            # By house
            props = self.HOUSE_PROPS.get(int(p["house"]))
            if props:
                el = props["element"]
                cr = props["cross"]
                house_scores["elements"][el] = house_scores["elements"].get(el, 0) + weight
                house_scores["crosses"][cr]  = house_scores["crosses"].get(cr, 0)  + weight

        return sign_scores, house_scores

    def get_dominants(self, scores):
        """Returns (dominant_element, dominant_cross) or (None, None) if no data."""
        if not scores["elements"] or not scores["crosses"]:
            return None, None
        el_dom = max(scores["elements"], key=scores["elements"].get)
        cr_dom = max(scores["crosses"],  key=scores["crosses"].get)
        return el_dom, cr_dom

    def get_synthetic_sign(self, element, cross):
        if not element or not cross:
            return None
        for sign, props in self.ZODIAC.items():
            if props["element"] == element and props["cross"] == cross:
                return sign
        return None

    def get_synthetic_house(self, element, cross):
        if not element or not cross:
            return None
        for house, props in self.HOUSE_PROPS.items():
            if props["element"] == element and props["cross"] == cross:
                return str(house)
        return None
