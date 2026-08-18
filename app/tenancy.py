"""
The internal → partner-facing seam.

This module is the ENTIRE difference between the two deployment modes. Every
request resolves to a partner_id here, and every DB read is scoped by it. In
internal mode that resolution is a constant; in partner mode it comes from an
API key. Nothing else in the codebase knows which mode it is running in.

Why it matters: the usual way this goes wrong is shipping the internal tool with
no tenant concept, then discovering that "add multi-tenancy" means touching
every query, every route and every template. Carrying partner_id from day one
costs nothing now and removes that rewrite later.

Promoting internal → partner is three steps:
  1. APP_MODE=partner
  2. Insert partner rows with real API keys
  3. Nothing else.
"""
from __future__ import annotations
from dataclasses import dataclass

from .config import cfg
from . import db


class AuthError(Exception):
    pass


@dataclass
class Principal:
    partner_id: str
    name: str
    branding: dict
    is_internal: bool

    @property
    def scope(self) -> str | None:
        """
        The partner_id to filter queries by, or None for unscoped access.

        Internal mode returns None so an operator sees every audit — which is
        the point of an internal tool. Partner mode always returns a concrete
        id, so a partner can never read another partner's data.
        """
        return None if self.is_internal else self.partner_id


INTERNAL = Principal(cfg.default_partner, "Vici Media (internal)", {}, True)


def resolve(api_key: str | None) -> Principal:
    if not cfg.is_partner_mode:
        return INTERNAL
    if not api_key:
        raise AuthError("missing API key")
    import json
    with db.conn() as c:
        cur = c.cursor()
        cur.execute(db._q("SELECT id,name,branding FROM partners WHERE api_key=?"),
                    (api_key,))
        row = cur.fetchone()
    if not row:
        raise AuthError("invalid API key")
    return Principal(row[0], row[1], json.loads(row[2] or "{}"), False)


def owner_for_new_audit(p: Principal) -> str:
    """Who owns an audit created by this principal."""
    return p.partner_id
