"""
Generate the home-screen icons.

Run once after deploying:   python make_icons.py

iOS needs a real PNG for the Add to Home Screen icon (it will not use an SVG),
so we draw one with Pillow rather than shipping a binary file.
"""
import os

from PIL import Image, ImageDraw

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "img")

BG = (11, 15, 20)
BAR = (37, 99, 235)
PLATE = (232, 237, 244)


def draw_icon(size):
    img = Image.new("RGB", (size, size), BG)
    d = ImageDraw.Draw(img)
    u = size / 100.0  # work in percentage units so both sizes match exactly

    def box(x0, y0, x1, y1, fill, radius):
        d.rounded_rectangle(
            [x0 * u, y0 * u, x1 * u, y1 * u], radius=radius * u, fill=fill
        )

    # A dumbbell: two outer plates, two inner plates, one bar.
    box(20, 46, 80, 54, BAR, 4)          # bar
    box(12, 34, 24, 66, PLATE, 5)        # left outer plate
    box(76, 34, 88, 66, PLATE, 5)        # right outer plate
    box(26, 40, 34, 60, BAR, 3)          # left inner plate
    box(66, 40, 74, 60, BAR, 3)          # right inner plate
    return img


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    # 180 is what iOS wants for apple-touch-icon; 192/512 are for the manifest.
    for size in (180, 192, 512):
        path = os.path.join(OUT_DIR, "icon-" + str(size) + ".png")
        draw_icon(size).save(path, "PNG", optimize=True)
        print("wrote", path)


if __name__ == "__main__":
    main()
