# 2026.08.20-67

**Do**

- Upload the zip. It re-includes `app/ui.py`, `engine/preflight.py` and
  `tests/test_preflight.py` - your form still shows the pre-60 labels, which
  means those three never landed.
- Re-run: Full audit + Consent check, all four phases ticked, Ask the AI
  assistants ON, Reuse the last crawl ON.

**Check**

- The form's Browser user-agent and Render JavaScript pills read
  "auto - tick to force". If they still say "if the site blocks bots", ui.py
  did not upload.
- Consent rows say "No issue seen", never "Pass", and the section opens with
  a disclaimer.
- No Current Strengths heading when there are no strengths.
- AI Search names the platforms and lists example questions.

**Pending**

- Nothing outstanding.
