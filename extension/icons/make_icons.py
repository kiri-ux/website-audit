"""
The Site Scanner mark, generated rather than committed as an opaque blob.

Chrome wants PNGs at four sizes and there is no vector path in a manifest, so
the icon has to ship as bitmaps. Keeping the code that draws them means the
next palette change is an edit here rather than someone opening an image
editor and guessing at #1c5ba6.

The colors are the two sampled off the adtini screenshot — the rail blue and
the gold of its active tile — so the toolbar button, the rail item and the
audit page are one family.

    python3 extension/icons/make_icons.py

Requires Pillow. Nothing at runtime imports this; the PNGs it writes are what
ship.
"""
from __future__ import annotations
import os
from PIL import Image, ImageDraw

RAIL_BG = (28, 91, 166)     # --rail-bg
GOLD = (232, 172, 62)       # --gold
WHITE = (255, 255, 255)

HERE = os.path.dirname(os.path.abspath(__file__))


def render(px: int) -> Image.Image:
    """
    Two drawings, not one drawing scaled.

    The first cut drew the full mark — window, title bar, lens — at every size
    and downscaled. At 128 it was fine. At 16 it was four grey pixels: three
    concentric strokes cannot resolve inside sixteen of them, and 16px in the
    toolbar is where this icon actually lives. The small sizes drop the window
    and keep the lens, which is the half that carries the meaning.

    Everything is drawn on the same 24-unit grid the rail SVG uses, at 8x, and
    downsampled — which is how the strokes come out smooth without asking
    Pillow for antialiased lines it does not do.
    """
    s = px * 8
    im = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle([0, 0, s - 1, s - 1], radius=int(s * 0.22), fill=RAIL_BG)
    u = s / 24.0

    if px <= 32:
        w = max(2, int(u * 2.6))
        cx, cy, r = 10.6 * u, 10.6 * u, 5.0 * u
        d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=WHITE, width=w)
        d.line([cx + r * .72, cy + r * .72, 19.2 * u, 19.2 * u],
               fill=GOLD, width=int(w * 1.15))
        return im.resize((px, px), Image.LANCZOS)

    w = max(2, int(u * 1.75))
    d.rounded_rectangle([3.4 * u, 4.6 * u, 20.6 * u, 16.4 * u],
                        radius=1.7 * u, outline=WHITE, width=w)
    d.line([3.4 * u, 8.2 * u, 20.6 * u, 8.2 * u], fill=WHITE, width=w)
    for x in (5.9, 7.7, 9.5):                      # the three window dots
        d.ellipse([x * u - w * .55, 6.4 * u - w * .55,
                   x * u + w * .55, 6.4 * u + w * .55], fill=WHITE)

    # The lens sits low and right and BREAKS the window's edge. Centred inside
    # it read as a circle parked in a box; crossing the edge is what makes the
    # two shapes one object. The knockout behind it is what lets it cross.
    cx, cy, r = 13.9 * u, 15.0 * u, 3.9 * u
    d.ellipse([cx - r - w * 1.5, cy - r - w * 1.5,
               cx + r + w * 1.5, cy + r + w * 1.5], fill=RAIL_BG)
    d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=GOLD, width=w)
    d.line([cx + r * .75, cy + r * .75, 19.7 * u, 20.8 * u],
           fill=GOLD, width=int(w * 1.3))
    return im.resize((px, px), Image.LANCZOS)


def main() -> None:
    for px in (16, 32, 48, 128):
        p = os.path.join(HERE, f"icon{px}.png")
        render(px).save(p)
        print("wrote", p)


if __name__ == "__main__":
    main()
