"""
texts.py — тексты Звездицы для людей (Telegram HTML).

Термины методики переведены на понятный язык по утверждённому словарю:
  лунарный возврат → личный месяц, синтетический знак → роль месяца,
  синтетический дом → главная задача, знаки → «как ты хочешь»,
  дома → «как будет на самом деле», Asc → начало месяца, MC → финал.
Технические данные остаются в разделе «Подробно для знатоков».
"""

import html
import re

from core.forecast import Forecast

MONTHS_GEN = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля",
              "августа", "сентября", "октября", "ноября", "декабря"]

SIGN_RU = {
    "Aries": "Овен", "Taurus": "Телец", "Gemini": "Близнецы", "Cancer": "Рак",
    "Leo": "Лев", "Virgo": "Дева", "Libra": "Весы", "Scorpio": "Скорпион",
    "Sagittarius": "Стрелец", "Capricorn": "Козерог", "Aquarius": "Водолей",
    "Pisces": "Рыбы",
}
SIGN_SYMBOL = {
    "Aries": "♈", "Taurus": "♉", "Gemini": "♊", "Cancer": "♋", "Leo": "♌",
    "Virgo": "♍", "Libra": "♎", "Scorpio": "♏", "Sagittarius": "♐",
    "Capricorn": "♑", "Aquarius": "♒", "Pisces": "♓",
}
PLANET_RU = {
    "Sun": "Солнце", "Moon": "Луна", "Mercury": "Меркурий", "Venus": "Венера",
    "Mars": "Марс", "Jupiter": "Юпитер", "Saturn": "Сатурн",
    "Uranus": "Уран", "Neptune": "Нептун", "Pluto": "Плутон",
}

# Роль месяца (по знаку, который собирает доминирующие стихию и крест)
ROLES = {
    "Aries":       ("Первопроходец", "начинать первым и не ждать идеальных условий"),
    "Taurus":      ("Хранитель", "беречь и приумножать то, что уже есть"),
    "Gemini":      ("Связной", "узнавать, договариваться и держать много нитей сразу"),
    "Cancer":      ("Опекун", "заботиться о своих и создавать ощущение дома"),
    "Leo":         ("Главный герой", "проявлять себя, творить и вести за собой"),
    "Virgo":       ("Мастер", "наводить порядок, улучшать детали и быть полезным"),
    "Libra":       ("Дипломат", "искать баланс, договариваться и выбирать союзников"),
    "Scorpio":     ("Исследователь глубин", "докапываться до сути и проходить через перемены"),
    "Sagittarius": ("Путешественник", "расширять горизонты, учиться и искать смысл"),
    "Capricorn":   ("Стратег", "ставить цели и доводить дело до результата"),
    "Aquarius":    ("Новатор", "менять правила, искать своих людей и свободу"),
    "Pisces":      ("Мечтатель", "доверять интуиции, отпускать и сочувствовать"),
}

# Главная задача месяца (по дому) и сферы жизни для управителей
HOUSE_TASKS = {
    1:  ("Ты и твой образ", "заявить о себе и начать что-то новое для себя"),
    2:  ("Деньги и ресурсы", "разобраться с доходами, тратами и тем, что ты ценишь"),
    3:  ("Общение и учёба", "переговоры, переписки, короткие поездки, новые знания"),
    4:  ("Дом и семья", "родные, жильё и твоя внутренняя опора"),
    5:  ("Творчество и любовь", "удовольствие, романтика, дети и самовыражение"),
    6:  ("Работа и здоровье", "режим, рабочие задачи и забота о теле"),
    7:  ("Партнёрство", "отношения, договоры и сотрудничество"),
    8:  ("Перемены и общие ресурсы", "кризисы, кредиты, чужие деньги и глубокие изменения"),
    9:  ("Горизонты", "путешествия, обучение и поиск смысла"),
    10: ("Карьера и статус", "цели, репутация и достижения"),
    11: ("Друзья и планы", "команды, сообщества и мечты о будущем"),
    12: ("Отдых и завершение", "уединение, восстановление и закрытие старых дел"),
}

# «Как ты хочешь»: стихия и крест по знакам
WANT_ELEMENT = {
    "Огонь": "действовать сразу и быть заметным",
    "Земля": "делать основательно и видеть практический результат",
    "Воздух": "всё обдумать, обсудить и узнать",
    "Вода": "прислушиваться к чувствам и быть рядом со своими",
}
WANT_CROSS = {
    "Кардинальный": "запускать новое",
    "Фиксированный": "держать курс и не распыляться",
    "Мутабельный": "гибко переключаться между делами",
}
# «Как будет на самом деле»: стихия и крест по домам
LIFE_ELEMENT = {
    "Огонь": "быстрые события, где нужен напор и смелость",
    "Земля": "практические задачи: деньги, работа, быт",
    "Воздух": "разговоры, новости и много людей вокруг",
    "Вода": "эмоции, близкие люди и то, что трогает за живое",
}
LIFE_CROSS = {
    "Кардинальный": "резкие старты и повороты",
    "Фиксированный": "долгие процессы, которые надо выдержать",
    "Мутабельный": "частые перемены и много задач параллельно",
}

# В справочнике у Рыб нет разделов «Желания/Мотивации/Потребности»
FALLBACK_WANTS = {
    "Pisces": [
        "больше тишины и времени для себя",
        "доверять интуиции, а не планам",
        "помогать и сочувствовать",
        "мечтать, творить, слушать музыку",
        "выйти из гонки и жёстких правил",
    ],
}

LINE = "━━━━━━━━━━━━━━━━━━━━"


def esc(s) -> str:
    return html.escape(str(s), quote=False)


def fmt_date(dt) -> str:
    return f"{dt.day} {MONTHS_GEN[dt.month - 1]}"


def fmt_dt(dt) -> str:
    return f"{fmt_date(dt)}, {dt.strftime('%H:%M')}"


def _first_sentences(text: str, limit: int = 420) -> str:
    """Чистит markdown из справочника и берёт первые предложения до limit символов."""
    t = re.sub(r"\*\*(.*?)\*\*", r"\1", text or "")
    t = re.sub(r"\s+", " ", t).strip()
    if len(t) <= limit:
        return t
    cut = t[:limit]
    end = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "))
    return (cut[: end + 1] if end > 80 else cut.rstrip() + "…")


def role_line(sign) -> str:
    if not sign or sign not in ROLES:
        return "Роль месяца: не удалось определить."
    title, what = ROLES[sign]
    return f"🎭 <b>Роль месяца: {title}</b> ({SIGN_RU[sign]} {SIGN_SYMBOL[sign]})\nТебе захочется {what}."


def task_line(house) -> str:
    try:
        h = int(house)
    except (TypeError, ValueError):
        return "Главная задача: не удалось определить."
    title, what = HOUSE_TASKS[h]
    return f"🎯 <b>Главная задача: {title}</b>\nБольше всего внимания потребуют {what}."


def time_warning(f: Forecast) -> str:
    if f.time_known:
        return ""
    return (
        "\n\n⚠️ <i>Время рождения неизвестно, поэтому прогноз приблизительный: "
        "начало месяца может сдвинуться на несколько часов, а «как начнётся месяц» — "
        "измениться. Узнаешь время — обнови данные: /profile</i>"
    )


def render_summary(f: Forecast, *, new_cycle: bool = False) -> str:
    """Первое сообщение: даты личного месяца, роль и главная задача."""
    head = "🌙 <b>Начался твой новый личный месяц!</b>" if new_cycle else "🌙 <b>Твой личный месяц</b>"
    return (
        f"{head}\n"
        f"{LINE}\n"
        f"📅 <b>{fmt_dt(f.start_local)} — {fmt_dt(f.end_local)}</b>\n"
        f"<i>по времени: {esc(f.city)}</i>\n\n"
        f"{role_line(f.synth_sign)}\n\n"
        f"{task_line(f.synth_house)}"
        f"{time_warning(f)}"
    )


def chart_caption(f: Forecast) -> str:
    return (
        f"✨ <b>Карта неба на начало твоего месяца</b>\n"
        f"{fmt_dt(f.start_local)} · {esc(f.city)}"
    )


def render_story_header(f: Forecast) -> str:
    return (
        f"💫 <b>Как ты хочешь и как будет на самом деле</b>\n"
        f"{LINE}\n"
        f"<b>Внутри:</b> хочется {WANT_ELEMENT.get(f.el_s, '…')}. "
        f"Твой стиль — {WANT_CROSS.get(f.cr_s, '…')}.\n"
        f"<b>Снаружи:</b> {LIFE_ELEMENT.get(f.el_h, '…')}. "
        f"Темп — {LIFE_CROSS.get(f.cr_h, '…')}.\n"
    )


def _clean_lines(text: str) -> list:
    t = (text or "").replace("*", "")
    return [re.sub(r"\s+", " ", ln).strip() for ln in t.splitlines()]


def _section_items(text: str, keyword: str, n: int, skip: str = "") -> list:
    """Пункты списка «- …» под заголовком, который начинается с keyword."""
    lines = _clean_lines(text)
    items, inside = [], False
    for ln in lines:
        if not inside:
            # заголовок раздела: «Желания Овна:», «Желания Скорпиона» (без двоеточия)
            if ln.lower().startswith(keyword.lower()) and len(ln) < 60 and not ln.startswith("-"):
                inside = True
            continue
        if ln.startswith("-"):
            item = ln.lstrip("- ").strip().rstrip(".")
            if item and not (skip and skip.lower() in item.lower()):
                items.append(item[0].lower() + item[1:] if len(item) > 1 and not item[1].isupper() else item)
        elif ln:
            break
        if len(items) >= n:
            break
    return items


def _section_paragraph(text: str, keyword: str) -> str:
    """Текст абзаца вида «Keyword: …»."""
    for ln in _clean_lines(text):
        if ln.lower().startswith(keyword.lower() + ":"):
            body = ln.split(":", 1)[1].strip()
            return body[:1].upper() + body[1:] if body else ""
    return ""


def _bullets(items: list) -> str:
    return "\n".join(f"— {esc(i)}" for i in items)


def render_story_fallback(f: Forecast, interp_data: dict) -> str:
    """Запасной текст из справочника, если нейросеть недоступна."""
    sign_text = interp_data.get("signs", {}).get(f.synth_sign, "")
    house_text = interp_data.get("houses", {}).get(str(f.synth_house), "")
    stem = SIGN_RU.get(f.synth_sign, "")[:4]

    wants = []
    for keyword in ("Желания", "Мотивации", "Потребности"):
        wants = _section_items(sign_text, keyword, 5, skip=stem)
        if wants:
            break
    wants = wants or FALLBACK_WANTS.get(f.synth_sign, [])
    life = _section_paragraph(house_text, "Жизнь заставляет")
    lessons = _section_items(house_text, "Чему учит", 3)
    tips = _section_items(house_text, "Рекомендации", 3)

    parts = []
    if wants:
        parts.append(f"<b>Тебе захочется:</b>\n{_bullets(wants)}")
    if life:
        parts.append(f"<b>А жизнь тебе:</b>\n{esc(life)}")
    if lessons:
        parts.append(f"<b>Чему учат обстоятельства:</b>\n{_bullets(lessons)}")
    if tips:
        parts.append(f"<b>Что поможет:</b>\n{_bullets(tips)}")
    return "\n\n".join(parts) or "Подробный текст для этого сочетания пока готовится."


def render_dynamics(f: Forecast, interp_data: dict) -> str:
    d = f.dynamics
    descr = interp_data.get("sign_descriptions", {})

    def part(sign, house):
        # «**Лев** - это обстоятельства, в которых…» → «Обстоятельства, в которых…»
        raw = re.sub(r"^\s*\*\*[^*]+\*\*\s*[-–—]\s*это\s+", "", descr.get(sign, ""))
        txt = _first_sentences(raw[:1].upper() + raw[1:], 380)
        sphere = ""
        try:
            title, _ = HOUSE_TASKS[int(house)]
            sphere = f"\nСфера: <b>{title.lower()}</b>."
        except (TypeError, ValueError, KeyError):
            pass
        return f"{esc(txt)}{sphere}"

    return (
        f"🧭 <b>Как начнётся и чем закончится месяц</b>\n"
        f"{LINE}\n\n"
        f"🏁 <b>Начало месяца</b>\n"
        f"{part(d['start_sign'], d.get('asc_ruler_house'))}\n\n"
        f"🎯 <b>Финал месяца</b>\n"
        f"{part(d['end_sign'], d.get('mc_ruler_house'))}"
    )


def render_expert(f: Forecast) -> str:
    """Раздел «Подробно для знатоков»: термины методики и все числа."""
    lines = []
    for p in f.planets:
        deg_in_sign = p["lon_deg"] % 30
        deg, mins = int(deg_in_sign), int((deg_in_sign - int(deg_in_sign)) * 60)
        retro = " ℞" if p.get("is_retro") else ""
        lines.append(
            f"• {PLANET_RU.get(p['name'], p['name'])}: {SIGN_RU[p['sign']]} {deg}°{mins:02d}'{retro}, дом {p['house']}"
        )

    def scores(d):
        return " · ".join(f"{k} {v}" for k, v in sorted(d.items(), key=lambda x: -x[1]))

    pts = f.points
    dyn = f.dynamics
    synth_house = f.synth_house or "—"
    return (
        f"🔭 <b>Подробно для знатоков</b>\n"
        f"{LINE}\n"
        f"Метод: лунарный возврат, Swiss Ephemeris, дома от знака Асцендента.\n"
        f"Начало цикла: {f.cycle_start_utc.strftime('%d.%m.%Y %H:%M')} UTC\n\n"
        f"<b>Планеты</b>\n" + "\n".join(lines) + "\n\n"
        f"<b>Баллы по знакам</b> (как хочу)\n"
        f"Стихии: {scores(f.sign_scores['elements'])}\n"
        f"Кресты: {scores(f.sign_scores['crosses'])}\n\n"
        f"<b>Баллы по домам</b> (как будет)\n"
        f"Стихии: {scores(f.house_scores['elements'])}\n"
        f"Кресты: {scores(f.house_scores['crosses'])}\n\n"
        f"Синтетический знак: {SIGN_RU.get(f.synth_sign, '—')} ({f.el_s} + {f.cr_s})\n"
        f"Синтетический дом: {synth_house} ({f.el_h} + {f.cr_h})\n"
        f"Асцендент: {SIGN_RU[pts['ascendant']]} {pts['ascendant_deg'] % 30:.0f}°, "
        f"управитель {PLANET_RU.get(dyn.get('asc_ruler'), '—')} в {dyn.get('asc_ruler_house') or '—'} доме\n"
        f"MC: {SIGN_RU[pts['midheaven']]} {pts['midheaven_deg'] % 30:.0f}°, "
        f"управитель {PLANET_RU.get(dyn.get('mc_ruler'), '—')} в {dyn.get('mc_ruler_house') or '—'} доме"
    )


def render_teaser() -> str:
    return (
        "🔒 <b>Полный разбор — в Звездице+</b>\n"
        "Живой разбор «как хочешь / как будет» и то, как начнётся "
        "и чем закончится твой месяц. /premium"
    )
