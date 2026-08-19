# Changed files — build 2026.08.19-02

Delta against **2026.08.19-01**. Drop over the repo, keeping folders.

| File | Why |
|---|---|
| `engine/pdf_report.py` | No build in footer · no collection method · MM/DD/YYYY dates · Prepared by Vici · severity + status pills · visual roadmap · scope instead of instructions · appendix rewritten · AI Search naming |
| `engine/summarise.py` | `SERVICE_ACTION` — the client PDF states the work, not the fix |
| `engine/report.py` | PDF opens in a new tab; AI Search naming |
| `engine/glossary.py` | GEO term renamed to "AI Search (GEO)" |
| `engine/checks/tagdetect.py` | One-line N/A notes for tags that aren't installed and don't apply |
| `tests/test_voice.py`, `tests/test_glossary.py` | Kept in step with the above |

**Re-run needed?** No for anything here except the shorter N/A tag notes — those
are stored findings, so existing audits keep the long version until re-run.
