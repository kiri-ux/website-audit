# 2026.08.20-66

**Do**

- Upload the zip.
- Reload a report and re-open its PDF. Most of this is render-time.

**Check**

- `/api/capabilities` now reports fonts and AI platforms. Confirm
  `"fonts": {"body": "GT Walsheim Pro", "headings": "Agdasima", "missing": []}`
  and that chatgpt and perplexity have left `ai_missing`.
- Homepage screenshot near the top, rounded with a shadow.
- AI Search section names the platforms and lists example questions.
- Headings never sit alone at the foot of a page.
- URLs in findings are short blue links, not printed in full.

**Needs a rerun** (written at scan time)

- Judgment wording, the example questions, the homepage shot, and the
  unmeasured-not-High severity rule.

**Pending**

- Pick a word to replace "Pass".
