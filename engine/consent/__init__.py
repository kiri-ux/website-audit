"""
The consent scanner, folded in.

Vendored from the standalone Consent Scanner rather than reimplemented. The hard
part of this problem is not the idea — it is fourteen CMP signatures, an
accept-click that survives iframe banners, and knowing that a Google endpoint
carrying a denied-state `gcs=` parameter pre-consent is expected rather than a
violation. That knowledge took a long time to accumulate and exists in exactly
one place; a second implementation would be a second thing to keep correct.

What is NEW here is the adapter in `checks.py`, which turns one scan result into
audit checkpoints, and nothing else. The scanner modules are kept as close to
upstream as possible — only the imports are relative — so a fix on either side
can be carried across by diffing.
"""
from .scanner import scan_site, normalize_url, SCANNER_REV   # noqa: F401
