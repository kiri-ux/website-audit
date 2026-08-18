"""
AI Visibility Monitor (Phase 4).

Measures whether AI platforms cite the client as a source — the metric that
turns a one-time audit into a recurring monitoring product.

    from engine.aivis import ClientProfile, build_panel, run_panel
"""
from .panel import ClientProfile, Query, build_panel, panel_summary
from .providers import PROVIDERS, ReplayProvider, active_providers
from .analyze import analyse_answer, aggregate, headline, brand_patterns
from .monitor import run_panel, run_replay, record_corpus
from .geo_checks import findings_from_run, summary_row

__all__ = ["ClientProfile", "Query", "build_panel", "panel_summary",
           "PROVIDERS", "ReplayProvider", "active_providers",
           "analyse_answer", "aggregate", "headline", "brand_patterns",
           "run_panel", "run_replay", "record_corpus",
           "findings_from_run", "summary_row"]
