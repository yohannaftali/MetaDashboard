"""Draws the MetaDashboard icon: a calendar page with green (profit) and red (loss) days on a blue tile.

    uv run --with pillow tools/make_icon.py    # writes src/metadashboard/assets/icon.ico and icon.png
"""
from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parents[1] / 'src' / 'metadashboard' / 'assets'
S = 1024  # drawn large, scaled down for each icon size
BLUE, PAGE, HEAD, EMPTY = '#2563eb', '#ffffff', '#1e3a8a', '#e3e6ea'
GREEN, RED = '#16a34a', '#dc2626'
# the days: g = profit, r = loss, . = no trade
DAYS = ['ggrg', 'rggr', 'g.gg']


def draw():
    img = Image.new('RGBA', (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((0, 0, S - 1, S - 1), radius=220, fill=BLUE)
    page = (150, 180, S - 150, S - 140)
    d.rounded_rectangle(page, radius=90, fill=PAGE)
    head = 150
    d.rounded_rectangle((page[0], page[1], page[2], page[1] + head), radius=90, fill=HEAD)
    d.rectangle((page[0], page[1] + 90, page[2], page[1] + head), fill=HEAD)
    for x in (330, S - 330):  # the rings of the calendar
        d.rounded_rectangle((x - 34, 110, x + 34, 290), radius=34, fill=PAGE)
    rows, cols, gap, margin = len(DAYS), len(DAYS[0]), 30, 50
    top = page[1] + head + margin
    cell = min((page[2] - page[0] - 2 * margin - (cols - 1) * gap) // cols,
               (page[3] - top - margin - (rows - 1) * gap) // rows)
    left = (page[0] + page[2] - cols * cell - (cols - 1) * gap) // 2
    for r, row in enumerate(DAYS):
        for c, day in enumerate(row):
            x = left + c * (cell + gap)
            y = top + r * (cell + gap)
            d.rounded_rectangle((x, y, x + cell, y + cell), radius=28,
                                fill={'g': GREEN, 'r': RED}.get(day, EMPTY))
    return img


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    img = draw()
    img.resize((256, 256), Image.LANCZOS).save(OUT / 'icon.png')
    img.save(OUT / 'icon.ico', sizes=[(n, n) for n in (16, 20, 24, 32, 40, 48, 64, 128, 256)])
    print('written', OUT / 'icon.ico', OUT / 'icon.png')


if __name__ == '__main__':
    main()
