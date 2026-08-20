"""
Report typeface.

Helvetica is one of the fourteen fonts every PDF reader must have, which is why
the report started there — nothing to install, nothing to embed, cannot fail.
The cost is that it looks like a PDF from 1998, and this document is trying to
read as something a consultancy wrote.

Roboto is registered when the TTFs are on disk and Helvetica is used when they
are not. The fallback is silent by design at RENDER time — a missing font must
never take a client's report down — but `status()` reports which one is in use
so a deploy that quietly lost the fonts is visible in the logs and in a test,
rather than only in the finished PDF.

The Dockerfile installs `fonts-roboto`. If you change base images, check that
package is still present: the failure is cosmetic and therefore easy to miss.
"""
from __future__ import annotations
import os

from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.fonts import addMapping

# Where Debian/Ubuntu put them, newest layout first. The `fonts-roboto` package
# has moved its files at least twice, so this is a list rather than a constant.
_DIRS = [
    "/usr/share/fonts/truetype/roboto/unhinted/RobotoTTF",
    "/usr/share/fonts/truetype/roboto/unhinted",
    "/usr/share/fonts/truetype/roboto/hinted",
    "/usr/share/fonts/truetype/roboto",
    "/usr/share/fonts/truetype/google-fonts",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                 "static", "fonts"),
]

_FACES = [
    ("Roboto", "Roboto-Regular.ttf", 0, 0),
    ("Roboto-Bold", "Roboto-Bold.ttf", 1, 0),
    ("Roboto-Italic", "Roboto-Italic.ttf", 0, 1),
    ("Roboto-BoldItalic", "Roboto-BoldItalic.ttf", 1, 1),
]

# Defaults, overwritten by register() on success.
BODY = "Helvetica"
BOLD = "Helvetica-Bold"
ITALIC = "Helvetica-Oblique"
BOLD_ITALIC = "Helvetica-BoldOblique"
_FAMILY = "Helvetica"
_REGISTERED = False


def _find(name: str) -> str | None:
    for d in _DIRS:
        p = os.path.join(d, name)
        if os.path.exists(p):
            return p
    return None


def register() -> str:
    """
    Register Roboto if all four faces are present. Returns the family in use.

    All four or none: registering regular and bold but not italic gives a
    document that switches typeface mid-sentence wherever an em-dash aside is
    italicised, which looks worse than plain Helvetica throughout.
    """
    global BODY, BOLD, ITALIC, BOLD_ITALIC, _FAMILY, _REGISTERED
    if _REGISTERED:
        return _FAMILY
    paths = {n: _find(f) for n, f, _b, _i in _FACES}
    if all(paths.values()):
        try:
            for name, _f, bold, italic in _FACES:
                pdfmetrics.registerFont(TTFont(name, paths[name]))
                # Without the mapping, reportlab's <b>/<i> markup inside a
                # Paragraph silently falls back to Helvetica, so bold runs
                # inside Roboto body copy would render in a different face.
                addMapping("Roboto", bold, italic, name)
            BODY, BOLD = "Roboto", "Roboto-Bold"
            ITALIC, BOLD_ITALIC = "Roboto-Italic", "Roboto-BoldItalic"
            _FAMILY = "Roboto"
        except Exception as exc:  # noqa: BLE001
            print(f"[fonts] Roboto found but would not register ({exc}); "
                  f"using Helvetica", flush=True)
    else:
        missing = [n for n, p in paths.items() if not p]
        print(f"[fonts] Roboto not installed (missing {', '.join(missing)}); "
              f"using Helvetica", flush=True)
    _REGISTERED = True
    return _FAMILY


def status() -> dict:
    return {"family": _FAMILY, "body": BODY, "bold": BOLD,
            "registered": _REGISTERED}
