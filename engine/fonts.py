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

# ---- Vici brand typography -------------------------------------------------
#
# Agdasima for headlines, GT Walsheim Pro for body copy — the brand book's own
# pairing. Neither ships with Debian, so both are DROP-IN: put the files in
# `static/fonts/` in the repo and they are picked up on the next deploy.
#
#   static/fonts/Agdasima-Regular.ttf        headings
#   static/fonts/Agdasima-Bold.ttf
#   static/fonts/GTWalsheimPro-Regular.ttf   body
#   static/fonts/GTWalsheimPro-Bold.ttf
#   static/fonts/GTWalsheimPro-Italic.ttf        (optional)
#   static/fonts/GTWalsheimPro-BoldItalic.ttf    (optional)
#
# Agdasima is on Google Fonts and free. GT Walsheim Pro is licensed from
# Grilli Type — it cannot be downloaded here and must come from whoever holds
# the licence.
#
# EACH FAMILY REGISTERS INDEPENDENTLY. Headlines in Agdasima with body copy
# still in Roboto is a perfectly good document; refusing to use either until
# both are present would mean one missing file loses the whole brand.
_BODY_FACES = [
    ("GTWalsheim", "GTWalsheimPro-Regular.ttf", 0, 0),
    ("GTWalsheim-Bold", "GTWalsheimPro-Bold.ttf", 1, 0),
]
# Italic is optional for the body face: reportlab synthesises nothing, so a
# missing italic would silently drop asides back to Helvetica mid-sentence.
# When it is absent we map italic to the regular face instead, which is a
# smaller wrong than a typeface change inside one paragraph.
_BODY_ITALIC = [
    ("GTWalsheim-Italic", "GTWalsheimPro-Italic.ttf", 0, 1),
    ("GTWalsheim-BoldItalic", "GTWalsheimPro-BoldItalic.ttf", 1, 1),
]
_HEAD_FACES = [
    ("Agdasima", "Agdasima-Regular.ttf", 0, 0),
    ("Agdasima-Bold", "Agdasima-Bold.ttf", 1, 0),
]

# Defaults, overwritten by register() on success.
BODY = "Helvetica"
BOLD = "Helvetica-Bold"
ITALIC = "Helvetica-Oblique"
BOLD_ITALIC = "Helvetica-BoldOblique"
# Headings default to the body face, so a document with no brand headline font
# still sets consistently rather than mixing two unrelated families.
HEAD = "Helvetica"
HEAD_BOLD = "Helvetica-Bold"
_FAMILY = "Helvetica"
_HEAD_FAMILY = "Helvetica"
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
    global BODY, BOLD, ITALIC, BOLD_ITALIC, HEAD, HEAD_BOLD
    global _FAMILY, _HEAD_FAMILY, _REGISTERED
    if _REGISTERED:
        return _FAMILY

    # ---- brand body face, if the files are there --------------------------
    bpaths = {n: _find(f) for n, f, _b, _i in _BODY_FACES}
    if all(bpaths.values()):
        try:
            for name, _f, bold, italic in _BODY_FACES:
                pdfmetrics.registerFont(TTFont(name, bpaths[name]))
                addMapping("GTWalsheim", bold, italic, name)
            ipaths = {n: _find(f) for n, f, _b, _i in _BODY_ITALIC}
            if all(ipaths.values()):
                for name, _f, bold, italic in _BODY_ITALIC:
                    pdfmetrics.registerFont(TTFont(name, ipaths[name]))
                    addMapping("GTWalsheim", bold, italic, name)
                ITALIC, BOLD_ITALIC = "GTWalsheim-Italic", "GTWalsheim-BoldItalic"
            else:
                addMapping("GTWalsheim", 0, 1, "GTWalsheim")
                addMapping("GTWalsheim", 1, 1, "GTWalsheim-Bold")
                ITALIC, BOLD_ITALIC = "GTWalsheim", "GTWalsheim-Bold"
            BODY, BOLD = "GTWalsheim", "GTWalsheim-Bold"
            HEAD, HEAD_BOLD = BODY, BOLD
            _FAMILY = "GT Walsheim Pro"
            _HEAD_FAMILY = _FAMILY
            print("[fonts] GT Walsheim Pro registered for body copy", flush=True)
        except Exception as exc:  # noqa: BLE001
            print(f"[fonts] GT Walsheim found but would not register ({exc})",
                  flush=True)

    # ---- brand headline face ---------------------------------------------
    hpaths = {n: _find(f) for n, f, _b, _i in _HEAD_FACES}
    if all(hpaths.values()):
        try:
            for name, _f, bold, italic in _HEAD_FACES:
                pdfmetrics.registerFont(TTFont(name, hpaths[name]))
                addMapping("Agdasima", bold, italic, name)
            HEAD, HEAD_BOLD = "Agdasima", "Agdasima-Bold"
            _HEAD_FAMILY = "Agdasima"
            print("[fonts] Agdasima registered for headlines", flush=True)
        except Exception as exc:  # noqa: BLE001
            print(f"[fonts] Agdasima found but would not register ({exc})",
                  flush=True)

    if _FAMILY != "Helvetica":
        _REGISTERED = True
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
            if _HEAD_FAMILY == "Helvetica":
                HEAD, HEAD_BOLD = BODY, BOLD
                _HEAD_FAMILY = "Roboto"
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
            "heading_family": _HEAD_FAMILY, "heading": HEAD,
            "registered": _REGISTERED}
