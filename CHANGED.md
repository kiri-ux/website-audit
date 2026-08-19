# Changed files — build 2026.08.19-11

**Cumulative since 2026.08.18-16.** Apply and you are current whatever you last
uploaded.

## This build — the favicon

One line, three builds. `static/favicon.svg` was not well-formed XML:

```
aria-label="Vici SEO & AI Search Audit"
```

A bare `&` in an XML attribute is a parse error. SVG is XML, and a browser
parses a standalone SVG document **strictly** — it does not repair it the way
it repairs HTML. So the file failed to parse, the browser drew nothing, and
nothing anywhere reported an error.

That explains why none of the three delivery mechanisms helped. The static
route served the file and returned a clean 200. The `/favicon.ico` route
served the same bytes. `app/brand.py` read the same bytes and base64-encoded
them into the `<link>` tag. Three routes, one broken payload. Every test I had
asserted the response contained `<svg` — which it did.

| File | Why |
|---|---|
| `static/favicon.svg` | `&` → `and`. This is the actual fix |
| `app/brand.py` | The embedded fallback now fires when the file is unparseable, not only when it is unreadable. A successful `open()` was never the test — parsing is. Logs a line when it falls back |
| `app/ui.py` | `_shell()` imported `HEAD_TAGS` and then hand-wrote its own link tags, so the dashboard and status pages never got the inline copy. Now uses the import |
| `tests/test_routes.py` | Asserts the served icon **parses** as XML, and that the inlined data URI decodes and parses too |
| `app/version.py` | 2026.08.19-11 |

## Carried from 2026.08.19-10

| File | Why |
|---|---|
| `app/api.py`, `app/ui.py` | **Re-run** — form + JSON endpoints, on the card and on every earlier run. Creates a NEW audit rather than re-queuing the row, so the "before" survives |
| `engine/summarise.py` | Plan items are verb-led work: "Rewrite duplicate page titles", not "Duplicate title tags" |
| `engine/charts.py` | Score + rating auto-fits its column |
| `engine/checks/tagdetect.py`, `engine/collectors/dataforseo.py` | "Not detected." / "Not measured." — no scope commentary |
| `engine/pdf_report.py` | Priority Issues column header is "What we found" |

## Verified before sending

- Rasterized the fixed SVG at 16px and 256px and looked at it.
- `xml.etree` parses the served bytes and the base64 payload out of the head.
- 14 suites green; `import app.api, app.worker` succeeds on a clean tree.

## What to check on this build

- Header chip reads **2026.08.19-11**.
- Tab icon on the dashboard: navy rounded square, gold gauge, cream needle.
- `/favicon.svg` opened directly should draw the icon. If you get an XML error
  page instead, the deploy did not take.
- Chrome caches favicons in a database separate from the page cache, so a hard
  refresh may not clear a remembered blank. A new tab to the URL usually does.
