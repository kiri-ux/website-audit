"""
State-by-state check map for US privacy-law scanning.

IMPORTANT - how to read and maintain this file:
- Each entry maps a state to TECHNICAL CHECKS the scanner can perform,
  not to legal conclusions. The scanner reports check failures
  ("GPC signal not visibly honored - required for CA targeting"),
  never "violates X law". Keep that language discipline.
- gpc: state requires honoring universal opt-out signals (GPC).
- optout_link: state requires a conspicuous opt-out method; the scanner
  checks for recognizable opt-out link text on the page.
- verify: sources conflicted on the effective date at last review -
  confirm with counsel before relying on it.
- Sources: state statutes and regulations (cited per entry), the IAPP
  US State Privacy Legislation Tracker, and state AG guidance.
  Compiled 2026-07-24 from primary/secondary sources; several 2026
  effective dates verified via current reporting at build time.

REVIEW PROCESS:
- LAST_REVIEWED below drives a staleness notice in the scanner UI when
  older than REVIEW_INTERVAL_DAYS. Update the date whenever this table
  is re-verified.
- Cadence: quarterly, plus whenever a new state law or UOOM rulemaking
  takes effect (the IAPP tracker and CPPA/state-AG announcements are
  the watch list).
- This table should be reviewed by legal counsel before any
  client-facing use. A formatted copy for that review accompanies the
  codebase (state-law-check-map.docx).
"""

LAST_REVIEWED = "2026-07-24"
REVIEW_INTERVAL_DAYS = 120

# Opt-out link phrases recognized on-page (lowercased substring match).
OPTOUT_LINK_PHRASES = [
    "do not sell or share my personal information",
    "do not sell my personal information",
    "do not sell or share",
    "do not sell my info",
    "your privacy choices",
    "privacy choices",
    "opt out of sale",
    "opt-out of sale",
]

# THE OTHER TWO LINKS CALIFORNIA ASKS FOR.
#
# The opt-out link is the famous one and was the only one checked, so a CA
# report said "missing one thing" about a site missing three. These are
# separate statutory obligations with separate link text, and a CMP that
# delivers the first does not automatically deliver the others.
#
# 1798.121 - the right to LIMIT the use and disclosure of sensitive personal
# information. Its own link, its own wording, and it applies whenever the site
# uses sensitive PI for anything beyond what the statute permits.
SENSITIVE_LINK_PHRASES = [
    "limit the use of my sensitive personal information",
    "limit the use of my sensitive information",
    "limit use of sensitive personal information",
    "limit the use and disclosure of my sensitive personal information",
    "your privacy choices",          # a combined-choices page satisfies both
    "privacy choices",
]

# 1798.100(a) - notice AT OR BEFORE the point of collection. A privacy policy
# buried in the footer is not a notice at collection; the statute wants the
# categories and purposes disclosed where the data is collected.
NOTICE_AT_COLLECTION_PHRASES = [
    "notice at collection",
    "notice of collection",
    "categories of personal information we collect",
    "information we collect",
    "at or before the point of collection",
]

STATE_CHECKS = {
    "CA": {"name": "California", "law": "CCPA/CPRA + CCPA Regulations",
           "gpc": True, "gpc_effective": "2021 (regs; enforced, e.g. Sephora)",
           "optout_link": True,
           "cite": "Cal. Civ. Code 1798.135; CCPA Regs 7025 (opt-out "
                   "preference signals); AG/CPPA guidance naming GPC",
           # OPT-OUT FOR ADULTS, OPT-IN FOR MINORS — and the second half was
           # missing entirely. CCPA/CPRA is an opt-out regime for adults, so
           # "no opt-out method" is the right finding for a general audience.
           # But selling or sharing the personal information of a consumer
           # KNOWN to be under 16 requires affirmative opt-in (13-15 from the
           # consumer, under 13 from a parent), and sensitive personal
           # information carries a separate right to limit its use. A site
           # that attracts families is exactly where that distinction bites,
           # and reporting only "opt-out" there understates what the law asks.
           "optin_minors": True,
           "optin_cite": "Cal. Civ. Code 1798.120(c) (under-16 opt-in); "
                         "1798.121 (right to limit sensitive PI)",
           # The two obligations that are NOT the opt-out link, and were not
           # being checked at all — so a site missing three CA requirements
           # was reported as missing one.
           "sensitive_link": True,
           "sensitive_cite": "Cal. Civ. Code 1798.121; CCPA Regs 7027",
           "notice_at_collection": True,
           "notice_cite": "Cal. Civ. Code 1798.100(a); CCPA Regs 7012",
           "notes": "Active enforcement incl. 2025-26 CA/CO/CT sweep. 2026 "
                    "regs add opt-out status display expectations."},
    "CO": {"name": "Colorado", "law": "Colorado Privacy Act",
           "gpc": True, "gpc_effective": "2024-07-01",
           "optout_link": True,
           "cite": "C.R.S. 6-1-1306(1)(a); CPA Rules 5.07; CO AG public "
                   "UOOM list (GPC is the sole recognized mechanism)",
           "notes": "Only state with a formal AG-maintained UOOM list."},
    "CT": {"name": "Connecticut", "law": "Connecticut Data Privacy Act",
           "gpc": True, "gpc_effective": "2025-01-01",
           "optout_link": True,
           "cite": "Conn. Gen. Stat. 42-518 to 42-525 (CTDPA)",
           "notes": "Part of the 2025-26 coordinated enforcement sweep."},
    "TX": {"name": "Texas", "law": "Texas Data Privacy & Security Act",
           "gpc": True, "gpc_effective": "2025-01-01",
           "optout_link": True,
           "cite": "Tex. Bus. & Com. Code ch. 541 (TDPSA)",
           "notes": "No revenue threshold - applies broadly."},
    "MT": {"name": "Montana", "law": "Montana Consumer Data Privacy Act",
           "gpc": True, "gpc_effective": "2025-01-01",
           "optout_link": True,
           "cite": "Mont. Code Ann. 30-14-2801 et seq. (MTCDPA)"},
    "OR": {"name": "Oregon", "law": "Oregon Consumer Privacy Act",
           "gpc": True, "gpc_effective": "2026-01-01",
           "optout_link": True,
           "cite": "ORS 646A.570 et seq. (OCPA)"},
    "DE": {"name": "Delaware", "law": "Delaware Personal Data Privacy Act",
           "gpc": True, "gpc_effective": "2026-01-01",
           "optout_link": True,
           "cite": "6 Del. C. ch. 12D (DPDPA)"},
    "NH": {"name": "New Hampshire", "law": "NH Privacy Act (SB 255)",
           "gpc": True, "gpc_effective": "2026-01-01",
           "optout_link": True,
           "cite": "N.H. RSA 507-H"},
    "NJ": {"name": "New Jersey", "law": "NJ Data Privacy Act (S332)",
           "gpc": True, "gpc_effective": "2026 (rulemaking-dependent)",
           "verify": True,
           "optout_link": True,
           "cite": "N.J.S.A. 56:8-166.4 et seq.",
           "notes": "UOOM timing tied to rulemaking - confirm with counsel."},
    "NE": {"name": "Nebraska", "law": "Nebraska Data Privacy Act",
           "gpc": True, "gpc_effective": "2026-01-01",
           "optout_link": True,
           "cite": "Neb. Rev. Stat. 87-1101 et seq. (NDPA)"},
    "MD": {"name": "Maryland", "law": "MD Online Data Privacy Act",
           "gpc": True, "gpc_effective": "2026 (sources conflict: in effect "
                                         "vs. 2026-07)",
           "verify": True,
           "optout_link": True,
           "cite": "Md. Code, Com. Law 14-46 (MODPA)",
           "notes": "Strictest substantive rules (sensitive-data sale ban). "
                    "Confirm UOOM effective date with counsel."},
    "MN": {"name": "Minnesota", "law": "MN Consumer Data Privacy Act",
           "gpc": True, "gpc_effective": "2026 (sources conflict: in effect "
                                         "vs. 2026-07)",
           "verify": True,
           "optout_link": True,
           "cite": "Minn. Stat. 325O (MCDPA)",
           "notes": "Confirm UOOM effective date with counsel."},
    # States with comprehensive laws but NO universal opt-out signal
    # mandate at last review - opt-out method/notice checks only.
    "VA": {"name": "Virginia", "law": "VCDPA", "gpc": False,
           "optout_link": True, "cite": "Va. Code 59.1-575 et seq."},
    "UT": {"name": "Utah", "law": "UCPA", "gpc": False,
           "optout_link": True, "cite": "Utah Code 13-61"},
    "IA": {"name": "Iowa", "law": "ICDPA", "gpc": False,
           "optout_link": True, "cite": "Iowa Code ch. 715D"},
    "IN": {"name": "Indiana", "law": "INCDPA (eff. 2026-01)", "gpc": False,
           "optout_link": True, "cite": "Ind. Code 24-15"},
    "KY": {"name": "Kentucky", "law": "KCDPA (eff. 2026-01)", "gpc": False,
           "optout_link": True, "cite": "KRS 367.3611 et seq."},
    "TN": {"name": "Tennessee", "law": "TIPA", "gpc": False,
           "optout_link": True, "cite": "Tenn. Code 47-18-3201 et seq."},
    "RI": {"name": "Rhode Island", "law": "RIDTPPA (eff. 2026-01, no cure "
                                          "period)", "gpc": False,
           "optout_link": True, "cite": "R.I. Gen. Laws 6-48.1"},
    "FL": {"name": "Florida", "law": "FDBR (narrow applicability)",
           "gpc": False, "optout_link": True,
           "cite": "Fla. Stat. 501.701 et seq.",
           "notes": "High revenue threshold - applies to few clients."},
}

STATE_CODES = list(STATE_CHECKS.keys())
