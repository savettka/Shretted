"""
Draw the Shretted home-screen icons.

Run once after deploying:   python3.13 make_icons.py

iOS will not use an SVG for the Add to Home Screen icon, so the mark is drawn
here with Pillow rather than shipping a binary file. Same geometry as
templates/icons/logo.svg, worked in a 0-120 space and scaled up.
"""
import os

from PIL import Image, ImageDraw

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "img")

PAPER = (243, 242, 237)
SAGE = (156, 178, 149)

# Drawn at 4x then downsampled - Pillow has no anti-aliasing on arcs or thick
# lines, and at icon sizes the difference is very visible.
SS = 4


def draw_mark(size):
    px = size * SS
    u = px / 120.0                      # one unit of the 0-120 design space

    img = Image.new("RGB", (px, px), PAPER)
    d = ImageDraw.Draw(img)

    def w(units):
        return max(1, int(round(units * u)))

    def box(x0, y0, x1, y1):
        return [x0 * u, y0 * u, x1 * u, y1 * u]

    stroke = w(9.5)

    # --- the S -------------------------------------------------------------
    # Top bar, upper bowl (left half of a circle), waist, lower bowl (right
    # half), bottom bar.
    d.line(box(80, 26, 54, 26), fill=SAGE, width=stroke)
    d.arc(box(36, 26, 72, 62), 90, 270, fill=SAGE, width=stroke)
    d.line(box(54, 62, 66, 62), fill=SAGE, width=stroke)
    d.arc(box(48, 62, 84, 98), 270, 90, fill=SAGE, width=stroke)
    d.line(box(66, 98, 40, 98), fill=SAGE, width=stroke)

    # Pillow leaves notches where a line meets an arc, so cap the joins.
    for cx, cy in ((54, 26), (54, 62), (66, 62), (66, 98), (80, 26), (40, 98)):
        r = stroke / 2.0
        d.ellipse([cx * u - r, cy * u - r, cx * u + r, cy * u + r], fill=SAGE)

    # --- the dumbbell, on its own layer to keep the joins clean -----------
    bell = Image.new("RGBA", (px, px), (0, 0, 0, 0))
    b = ImageDraw.Draw(bell)
    b.line(box(50, 62, 70, 62), fill=SAGE + (255,), width=w(6.5))
    b.line(box(48, 53.5, 48, 70.5), fill=SAGE + (255,), width=w(7.5))
    b.line(box(72, 53.5, 72, 70.5), fill=SAGE + (255,), width=w(7.5))
    b.line(box(40, 57, 40, 67), fill=SAGE + (255,), width=w(6))
    b.line(box(80, 57, 80, 67), fill=SAGE + (255,), width=w(6))

    img.paste(bell, (0, 0), bell)

    return img.resize((size, size), Image.LANCZOS)


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    # 180 is what iOS wants for apple-touch-icon; 192/512 are for the manifest.
    for size in (180, 192, 512):
        path = os.path.join(OUT_DIR, "icon-" + str(size) + ".png")
        draw_mark(size).save(path, "PNG", optimize=True)
        print("wrote", path)


if __name__ == "__main__":
    main()
