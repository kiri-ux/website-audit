"""
Brand assets, owned in code rather than only on disk.

The favicon is served from `static/`, but the <link> tag uses a data URI built
from the same bytes. That removes a whole class of failure: a missing static
directory, a route that never got hit, a CDN caching a 404 from before the
file existed. The icon is 1.2KB — cheaper to inline than to debug.

`static/favicon.svg` stays the editable source. This module reads it at import
and falls back to an embedded copy only if the file is unavailable, so there is
one place to change the artwork in the normal case.
"""
from __future__ import annotations
import base64
import os

STATIC_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          "static")

# Fallback copy — used only if static/favicon.svg cannot be read.
_FALLBACK_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">'
    '<rect width="64" height="64" rx="14" fill="#002D58"/>'
    '<path d="M19.27 44.73 A 18 18 0 1 1 44.73 44.73" fill="none" '
    'stroke="#FDFBF7" stroke-opacity=".28" stroke-width="7" stroke-linecap="round"/>'
    '<path d="M19.27 44.73 A 18 18 0 1 1 48.63 25.11" fill="none" '
    'stroke="#F1B434" stroke-width="7" stroke-linecap="round"/>'
    '<line x1="32" y1="32" x2="42.2" y2="27.8" stroke="#FDFBF7" '
    'stroke-width="5" stroke-linecap="round"/>'
    '<circle cx="32" cy="32" r="3.6" fill="#FDFBF7"/></svg>')


def _read(name: str) -> bytes | None:
    try:
        with open(os.path.join(STATIC_DIR, name), "rb") as f:
            return f.read()
    except Exception:
        return None


def _wellformed(blob: bytes | None) -> bytes | None:
    """
    SVG is XML, and browsers parse a standalone SVG document STRICTLY. One raw
    `&` in an attribute and the whole file fails to parse — the browser draws
    nothing and reports nothing. That is exactly what shipped: `aria-label`
    read "SEO & AI Search", so /favicon.svg returned a clean 200 containing a
    document no renderer would accept, and the data URI below was built from
    the same bytes. Three delivery mechanisms, one broken payload.

    A read that succeeds is not the test. Parsing is.
    """
    if not blob:
        return None
    try:
        import xml.etree.ElementTree as ET
        ET.fromstring(blob)
        return blob
    except Exception as exc:  # noqa: BLE001
        print(f"[brand] static/favicon.svg is not well-formed ({exc}) — "
              f"using the embedded copy", flush=True)
        return None


FAVICON_SVG: bytes = _wellformed(_read("favicon.svg")) or _FALLBACK_SVG.encode()
APPLE_ICON: bytes | None = _read("apple-touch-icon.png")

_DATA_URI = "data:image/svg+xml;base64," + base64.b64encode(FAVICON_SVG).decode()

# Inline data URI first, file second. A browser uses the first icon it can
# load, so this renders even when the static route is unreachable.
HEAD_TAGS = (f"<link rel='icon' href=\"{_DATA_URI}\" type='image/svg+xml'>"
             f"<link rel='alternate icon' href='/favicon.svg' type='image/svg+xml'>"
             f"<link rel='apple-touch-icon' href='/apple-touch-icon.png'>"
             f"<meta name='theme-color' content='#002D58'>")
