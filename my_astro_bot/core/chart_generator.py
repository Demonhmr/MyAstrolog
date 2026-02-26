"""
chart_generator.py — v2
Generates a Lunar Return wheel chart as PNG using matplotlib (Agg backend).
Features: zodiac ring, houses, planets, aspects (6 types), retrograde markers.

IMPORTANT: Call generate_chart_png inside asyncio.run_in_executor — it is CPU-heavy
and will block the event loop for 2-60s on first run (matplotlib font cache build).
"""

import io
import math
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np


# ── Zodiac metadata ──────────────────────────────────────────────────────────

SIGN_SYMBOLS = ["♈", "♉", "♊", "♋", "♌", "♍", "♎", "♏", "♐", "♑", "♒", "♓"]

ELEMENT_COLORS = {
    0: "#e74c3c", 4: "#e74c3c", 8: "#e74c3c",   # Fire
    1: "#2ecc71", 5: "#2ecc71", 9: "#2ecc71",   # Earth
    2: "#f39c12", 6: "#f39c12", 10: "#f39c12",  # Air
    3: "#3498db", 7: "#3498db", 11: "#3498db",  # Water
}

PLANET_SYMBOLS = {
    "Sun": "☉", "Moon": "☽", "Mercury": "☿", "Venus": "♀",
    "Mars": "♂", "Jupiter": "♃", "Saturn": "♄",
    "Uranus": "♅", "Neptune": "♆", "Pluto": "♇",
}
PLANET_COLORS = {
    "Sun": "#f1c40f", "Moon": "#bdc3c7", "Mercury": "#9b59b6",
    "Venus": "#27ae60", "Mars": "#e74c3c", "Jupiter": "#e67e22",
    "Saturn": "#95a5a6", "Uranus": "#1abc9c", "Neptune": "#2980b9",
    "Pluto": "#8e44ad",
}

# (name, angle_deg, orb_deg, color, linestyle, alpha)
ASPECTS = [
    ("Conjunction",  0,   8, "#f1c40f", "-",  0.70),
    ("Opposition",   180, 8, "#e74c3c", "-",  0.60),
    ("Trine",        120, 7, "#2ecc71", "-",  0.50),
    ("Square",       90,  7, "#e74c3c", "--", 0.45),
    ("Sextile",      60,  5, "#3498db", "-",  0.40),
    ("Quincunx",     150, 3, "#9b59b6", ":",  0.30),
    ("Semi-sextile", 30,  2, "#bdc3c7", ":",  0.25),
]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _lon_to_angle(lon_deg: float, asc_deg: float) -> float:
    return math.radians((lon_deg - asc_deg + 180.0) % 360)


def _polar(r: float, theta: float):
    return r * math.cos(theta), r * math.sin(theta)


def _aspect_between(lon1: float, lon2: float):
    diff = abs(lon1 - lon2) % 360
    if diff > 180:
        diff = 360 - diff
    for name, angle, orb, color, ls, alpha in ASPECTS:
        if abs(diff - angle) <= orb:
            return {"color": color, "ls": ls, "alpha": alpha}
    return None


# ── Main function ─────────────────────────────────────────────────────────────

def generate_chart_png(
    planets: list,
    chart_points: dict,
    name: str,
    birth_date: str,
    birth_time: str,
    city: str,
    chart_title: str = "Карта Лунарного возврата",
) -> bytes:
    SIGN_NAMES_EN = [
        "Aries", "Taurus", "Gemini", "Cancer", "Leo", "Virgo",
        "Libra", "Scorpio", "Sagittarius", "Capricorn", "Aquarius", "Pisces",
    ]

    asc_sign_en  = chart_points.get("ascendant", "Aries")
    asc_sign_idx = SIGN_NAMES_EN.index(asc_sign_en) if asc_sign_en in SIGN_NAMES_EN else 0
    asc_deg      = asc_sign_idx * 30.0

    # ── Figure ───────────────────────────────────────────────────────────────
    fig, ax = plt.subplots(figsize=(10, 10), facecolor="#ffffff")
    ax.set_facecolor("#ffffff")
    ax.set_aspect("equal")
    ax.set_xlim(-1.65, 1.65)
    ax.set_ylim(-1.65, 1.65)
    ax.axis("off")

    R_OUTER     = 1.42
    R_ZODIAC_IN = 1.16
    R_HOUSE_OUT = 1.14
    R_HOUSE_IN  = 0.76
    R_PLANET    = 0.94
    R_ASPECT    = 0.72
    R_CENTER    = 0.22

    # ── Zodiac ring ───────────────────────────────────────────────────────────
    for i in range(12):
        start_lon = i * 30.0
        start_a = math.degrees(_lon_to_angle(start_lon, asc_deg))
        end_a   = math.degrees(_lon_to_angle(start_lon + 30.0, asc_deg))
        if end_a < start_a:
            end_a += 360

        color = ELEMENT_COLORS.get(i, "#555555")
        ax.add_patch(mpatches.Wedge(
            (0, 0), R_OUTER,
            theta1=start_a, theta2=end_a,
            width=R_OUTER - R_ZODIAC_IN,
            facecolor=color, alpha=0.12,
            edgecolor="#999999", linewidth=0.4, zorder=2,
        ))

        mid_theta = _lon_to_angle(start_lon + 15.0, asc_deg)
        r_label = (R_OUTER + R_ZODIAC_IN) / 2
        sx, sy = _polar(r_label, mid_theta)
        ax.text(sx, sy, SIGN_SYMBOLS[i], ha="center", va="center",
                fontsize=14, color=color, alpha=0.95, zorder=5)

    # ── Circles ───────────────────────────────────────────────────────────────
    for r, lw, alpha in [(R_OUTER, 1.5, 0.4), (R_ZODIAC_IN, 0.8, 0.3), (R_HOUSE_IN, 0.8, 0.2)]:
        ax.add_patch(plt.Circle((0, 0), r, color="#222222", fill=False,
                                linewidth=lw, alpha=alpha, zorder=3))

    ax.add_patch(plt.Circle((0, 0), R_ASPECT - 0.01, color="#fefefe", fill=True, zorder=4))

    # ── House lines ───────────────────────────────────────────────────────────
    axis_labels = {0: "ASC", 3: "IC", 6: "DSC", 9: "MC"}
    for i in range(12):
        lon_h  = i * 30.0
        theta  = _lon_to_angle(lon_h, asc_deg)
        x_out, y_out = _polar(R_HOUSE_OUT, theta)
        x_in,  y_in  = _polar(R_HOUSE_IN,  theta)
        is_major = (i % 3 == 0)
        ax.plot([x_in, x_out], [y_in, y_out],
                color="#000000" if is_major else "#999999",
                linewidth=1.2 if is_major else 0.5,
                alpha=0.6 if is_major else 0.3, zorder=3)
        if is_major and i in axis_labels:
            lx, ly = _polar(R_HOUSE_OUT + 0.07, theta)
            ax.text(lx, ly, axis_labels[i], ha="center", va="center",
                    fontsize=8, color="#333333", fontweight="bold", alpha=0.85, zorder=6)
        elif not is_major:
            num_theta = _lon_to_angle(lon_h + 15.0, asc_deg)
            nx, ny = _polar((R_HOUSE_OUT + R_HOUSE_IN) / 2, num_theta)
            ax.text(nx, ny, str(i + 1), ha="center", va="center",
                    fontsize=6.5, color="#666666", alpha=0.7, zorder=5)

    # ── Aspects ───────────────────────────────────────────────────────────────
    for i, p1 in enumerate(planets):
        for j, p2 in enumerate(planets):
            if j <= i:
                continue
            asp = _aspect_between(p1.get("lon_deg", 0), p2.get("lon_deg", 0))
            if asp:
                t1 = _lon_to_angle(p1["lon_deg"], asc_deg)
                t2 = _lon_to_angle(p2["lon_deg"], asc_deg)
                x1, y1 = _polar(R_ASPECT, t1)
                x2, y2 = _polar(R_ASPECT, t2)
                ax.plot([x1, x2], [y1, y2],
                        color=asp["color"], linestyle=asp["ls"],
                        linewidth=0.8, alpha=asp["alpha"], zorder=5)

    ax.add_patch(plt.Circle((0, 0), R_CENTER + 0.10, color="#ffffff", fill=True, zorder=8))
    ax.add_patch(plt.Circle((0, 0), R_CENTER + 0.10, color="#9999bb", fill=False,
                            linewidth=0.8, alpha=0.5, zorder=8))

    # ── Planets ───────────────────────────────────────────────────────────────
    placed = []
    for p in planets:
        lon_p    = p.get("lon_deg", 0.0)
        theta    = _lon_to_angle(lon_p, asc_deg)
        is_retro = p.get("is_retro", False)

        r = R_PLANET
        for pt, _ in placed:
            diff = abs(theta - pt)
            if diff > math.pi:
                diff = 2 * math.pi - diff
            if diff < 0.13:
                r -= 0.13
        placed.append((theta, r))
        r = max(r, R_HOUSE_IN + 0.04)

        px, py = _polar(r, theta)
        symbol = PLANET_SYMBOLS.get(p["name"], p["name"][0])
        color  = PLANET_COLORS.get(p["name"], "#ffffff")

        dot_x, dot_y = _polar(R_ZODIAC_IN - 0.03, theta)
        ax.plot(dot_x, dot_y, "o", markersize=3, color=color, alpha=0.9, zorder=7)
        ax.plot([dot_x, px], [dot_y, py], "-", color=color, linewidth=0.5, alpha=0.35, zorder=6)
        ax.add_patch(plt.Circle((px, py), 0.058, color="#ffffff", fill=True, zorder=9))
        ax.text(px, py, symbol, ha="center", va="center",
                fontsize=13, color=color, fontweight="bold", zorder=10)

        if is_retro:
            rx, ry = _polar(r - 0.10, theta)
            ax.text(rx, ry, "℞", ha="center", va="center",
                    fontsize=7, color="#e74c3c", alpha=0.9, zorder=10)

    # ── Center info ───────────────────────────────────────────────────────────
    ax.text(0,  0.10, name,       ha="center", va="center", fontsize=10, color="#222222", fontweight="bold", zorder=11)
    ax.text(0,  0.00, birth_date, ha="center", va="center", fontsize=8,  color="#444444", zorder=11)
    ax.text(0, -0.09, birth_time, ha="center", va="center", fontsize=7,  color="#666666", zorder=11)
    ax.text(0, -0.18, city,       ha="center", va="center", fontsize=6,  color="#777777", zorder=11)

    # ── Title ─────────────────────────────────────────────────────────────────
    ax.text(0, -1.58, chart_title, ha="center", va="center",
            fontsize=11, color="#333333", fontstyle="italic", zorder=11)

    # ── Planet legend ─────────────────────────────────────────────────────────
    legend_y   = 1.53
    step       = 1.9 / max(len(planets) - 1, 1)
    for j, p in enumerate(planets):
        sym   = PLANET_SYMBOLS.get(p["name"], "?")
        col   = PLANET_COLORS.get(p["name"], "#fff")
        lx    = -0.95 + j * step
        label = (sym + "℞") if p.get("is_retro") else sym
        ax.text(lx, legend_y,        label,           ha="center", va="center", fontsize=9,   color=col,       zorder=11)
        ax.text(lx, legend_y - 0.10, p["name"][:3],  ha="center", va="center", fontsize=5.5, color="#444444", zorder=11)

    # ── Aspect legend ─────────────────────────────────────────────────────────
    asp_legend = [("☌", "#f1c40f"), ("☍", "#e74c3c"), ("△", "#2ecc71"),
                  ("□", "#e74c3c"), ("✶", "#3498db")]
    asp_names  = ["Соед.", "Оппоз.", "Трин", "Квадр.", "Секст."]
    for k, ((sym, col), nm) in enumerate(zip(asp_legend, asp_names)):
        lx = -0.80 + k * 0.40
        ax.text(lx, -1.44, sym, ha="center", va="center", fontsize=10, color=col,       zorder=11)
        ax.text(lx, -1.53, nm,  ha="center", va="center", fontsize=5,  color="#444444", zorder=11)

    # ── Export ────────────────────────────────────────────────────────────────
    buf = io.BytesIO()
    plt.savefig(buf, format="png", dpi=150, bbox_inches="tight",
                facecolor="#ffffff", edgecolor="none")
    plt.close(fig)
    buf.seek(0)
    return buf.read()
