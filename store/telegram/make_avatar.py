"""Аватарка бота @zvezditsa_bot (640×640) из иконки приложения web/app/icons/icon-maskable-512.png.
Рисуется заново, а не растягивается: фон и свечение повторяют радиальный профиль иконки,
звезда та же (внутренняя вершина на 0,35 радиуса), но крупнее, т.к. Telegram обрезает аватар в круг
и показывает его очень маленьким в списке чатов."""
import math
from pathlib import Path
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "web/app/icons/icon-maskable-512.png"
OUT = Path(__file__).with_name("zvezditsa-bot-avatar.png")
SIZE, SS = 640, 4                 # итоговый размер и суперсэмплинг для гладких краёв
STAR_R = 0.27                     # внешний радиус звезды в долях стороны (в иконке 0,223)
INNER = 0.35                      # внутренняя вершина / внешний радиус — как в иконке
STAR = (240, 195, 90)

src = Image.open(SRC).convert("RGB")
n = src.width; c = n / 2
# берём по диагонали, где звезды нет дальше внутренней вершины
diag = [src.getpixel((int(c + t / math.sqrt(2)), int(c + t / math.sqrt(2)))) for t in range(int(c * math.sqrt(2)) - 2)]
inner_end = next(t for t, p in enumerate(diag) if p[0] < 200 and t > 5)
base = diag[-1]

def glow(rel):                    # rel — расстояние от центра в долях половины стороны иконки
    t = rel * c
    if t < inner_end:             # под звездой: продолжаем ближайшее значение
        t = inner_end + 1
    i = int(min(t, len(diag) - 1))
    return diag[i]

S = SIZE * SS; h = S / 2
bg = Image.new("RGB", (S, S))
px = bg.load()
k = 0.223 / STAR_R                # свечение масштабируем вместе со звездой
cache = {}
for y in range(0, S, SS):
    for x in range(0, S, SS):
        r = round(math.hypot(x - h, y - h) / h * k, 3)
        col = cache.get(r) or cache.setdefault(r, glow(r))
        for dy in range(SS):
            for dx in range(SS):
                px[x + dx, y + dy] = col
d = ImageDraw.Draw(bg)
R = STAR_R * S; r_in = R * INNER
pts = []
for i in range(8):
    a = -math.pi / 2 + i * math.pi / 4
    rr = R if i % 2 == 0 else r_in
    pts.append((h + rr * math.cos(a), h + rr * math.sin(a)))
d.polygon(pts, fill=STAR)
img = bg.resize((SIZE, SIZE), Image.LANCZOS)
img.save(OUT, optimize=True)
# превью круглой обрезки, как в Telegram
mask = Image.new("L", (SIZE * 2, SIZE * 2), 0)
ImageDraw.Draw(mask).ellipse((0, 0, SIZE * 2 - 1, SIZE * 2 - 1), fill=255)
prev = Image.new("RGB", (SIZE, SIZE), (255, 255, 255))
prev.paste(img, (0, 0), mask.resize((SIZE, SIZE), Image.LANCZOS))
prev.save(OUT.with_name("preview-circle.png"))
print(OUT, img.size, "inner_end", inner_end, "base", base)
