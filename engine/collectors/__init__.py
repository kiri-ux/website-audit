"""
External-data collectors — the ones blocked on credentials rather than code.

Each returns {checkpoint_id: finding} and degrades to Need Access (confidence 0)
when its credentials are absent. That degradation is the contract: an audit
never reports "we could not ask" as "your site is broken".

Two vendors answer the off-page section. DataForSEO is preferred because Vici
already pays for it (the SEO quote tool runs on the same credentials); the
Ahrefs/Semrush adapter stays as the fallback so a partner deployment with its
own subscription is a config change rather than a code change.
"""
import os

from .analytics import (collect_gsc, collect_ga4, consent_url, exchange_code,
                        GSC_IDS, GA4_IDS)
from .backlinks import collect_backlinks as collect_backlinks_vendor, OFF_IDS
from . import dataforseo
from .dataforseo import collect_rankings, collect_lighthouse, capture_screenshot


def collect_backlinks(domain: str) -> dict:
    """DataForSEO when configured, otherwise the Ahrefs/Semrush adapter."""
    if dataforseo.configured():
        return dataforseo.collect_backlinks(domain)
    return collect_backlinks_vendor(domain)


__all__ = ["collect_gsc", "collect_ga4", "collect_backlinks",
           "collect_rankings", "collect_lighthouse", "capture_screenshot",
           "consent_url", "exchange_code", "GSC_IDS", "GA4_IDS", "OFF_IDS",
           "dataforseo"]
