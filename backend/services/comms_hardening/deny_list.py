"""Backlog #iv · Feb-2026 — Customer-facing recipient deny-list.

Root cause for Bug 2 (audit):

  * ``+16028874400`` is the tenant's ``RC_FROM_NUMBER`` and
    ``settings.business_card.phone``.  No code path programmatically
    appends the from-number to a customer-facing recipient list,
    but the ``COMMS_TEST_ALLOWLIST_PHONES`` env var acts as a
    non-production bypass — so any bogus recipient value that
    happens to match a live workforce / tenant number
    is delivered to a real admin line.

This module implements the belt-and-suspenders guardrail:

  * :func:`strip_admin_owned_recipients` — subtracts any recipient
    address that maps to a workforce user, a tenant business-card
    contact, or the ``RC_FROM_NUMBER`` / ``EMAIL_FROM`` env vars.
    Callers pass a list of recipient addresses along with the
    tenant scope; the helper returns ``(kept, stripped)``.  Every
    stripped recipient is logged with structured context so ops
    sees the guardrail firing.
  * :func:`allowlist_overlap_check` — R1 startup sanity check.
    Compares ``COMMS_TEST_ALLOWLIST_PHONES`` ∪
    ``COMMS_TEST_ALLOWLIST_EMAILS`` against every source the deny-
    list scans, emitting a single ``WARN`` line for each overlap.
    Log-only — never blocks startup.

Design notes
------------
* The deny-list applies to ``kind="customer_facing"`` sends only.
  Internal admin digests (weekly pool-service report, weekly
  digest, scorecard) still reach admins.  The helper's boolean
  arg is deliberately explicit — a caller has to pass
  ``kind="customer_facing"`` for stripping to apply.
* Per-tenant scoped:  admin numbers from OTHER tenants are NOT
  stripped.  A tenant's admin phone getting spammed by ANOTHER
  tenant's sequence is an entirely different bug we shouldn't
  regress on.
* Case + format tolerant:  emails compared lower-cased, phones
  compared on last-10 digits after stripping non-digits.
"""
from __future__ import annotations

import logging
import os
import re
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from config import db


logger = logging.getLogger("notifications.deny_list")


# ═════════════════════════════════════════════════════════════════════
# Normalisation helpers
# ═════════════════════════════════════════════════════════════════════
def _norm_email(v: Optional[str]) -> str:
    return (v or "").strip().lower()


def _norm_phone(v: Optional[str]) -> str:
    """Digits-only, last-10.  Empty when input is falsy or has < 4
    digits (guards against typo-only strings ending up in the set)."""
    digits = re.sub(r"\D+", "", v or "")
    if len(digits) < 4:
        return ""
    return digits[-10:]


# ═════════════════════════════════════════════════════════════════════
# Admin/workforce/tenant source scanners
# ═════════════════════════════════════════════════════════════════════
async def _tenant_workforce_addresses(
    tenant_id: str,
) -> Dict[str, Set[str]]:
    """Return every phone + email owned by any user in the tenant's
    workforce (admin / super_admin / manager / pool_tech /
    landscape_tech / office / dispatcher).  Non-workforce roles
    (customers, portal-only accounts) are NOT included."""
    out = {"emails": set(), "phones": set()}
    workforce_roles = {
        "admin", "super_admin", "manager",
        "pool_tech", "landscape_tech",
        "office", "dispatcher", "owner",
    }
    async for u in db.users.find(
        {"tenant_id": tenant_id, "role": {"$in": list(workforce_roles)}},
        {"_id": 0, "email": 1, "phone": 1, "phones": 1, "sms_phone": 1},
    ):
        e = _norm_email(u.get("email"))
        if e:
            out["emails"].add(e)
        for k in ("phone", "sms_phone"):
            p = _norm_phone(u.get(k))
            if p:
                out["phones"].add(p)
        for phn in (u.get("phones") or []):
            if isinstance(phn, dict):
                p = _norm_phone(phn.get("value") or phn.get("number"))
            else:
                p = _norm_phone(phn)
            if p:
                out["phones"].add(p)
    return out


async def _tenant_business_card_addresses(
    tenant_id: str,
) -> Dict[str, Set[str]]:
    """Return the tenant's admin-editable ``settings.business_card``
    email + phone (documented per-tenant contact fields)."""
    out = {"emails": set(), "phones": set()}
    t = await db.tenants.find_one(
        {"id": tenant_id},
        {"_id": 0, "settings": 1, "phone": 1, "email": 1,
          "rc_sms_from_number": 1},
    ) or {}
    card = ((t.get("settings") or {}).get("business_card") or {})
    for src in (card.get("email"), t.get("email")):
        e = _norm_email(src)
        if e:
            out["emails"].add(e)
    for src in (card.get("phone"), t.get("phone"), t.get("rc_sms_from_number")):
        p = _norm_phone(src)
        if p:
            out["phones"].add(p)
    return out


def _env_from_addresses() -> Dict[str, Set[str]]:
    """Return the outbound "from" addresses configured in env
    (``RC_FROM_NUMBER`` / ``RC_SMS_DEFAULT_FROM`` / ``EMAIL_FROM``
    / ``RESEND_FROM``)."""
    out = {"emails": set(), "phones": set()}
    for k in ("RC_FROM_NUMBER", "RC_SMS_DEFAULT_FROM",
              "RC_VOICE_DEFAULT_FROM"):
        v = os.environ.get(k)
        p = _norm_phone(v)
        if p:
            out["phones"].add(p)
    for k in ("EMAIL_FROM", "RESEND_FROM"):
        v = os.environ.get(k)
        e = _norm_email(v)
        if e and "@" in e:
            out["emails"].add(e)
    return out


async def _load_deny_sets(tenant_id: str) -> Dict[str, Set[str]]:
    """Union the three scanners into one deny-set per channel."""
    wf = await _tenant_workforce_addresses(tenant_id)
    bc = await _tenant_business_card_addresses(tenant_id)
    envs = _env_from_addresses()
    return {
        "emails": wf["emails"] | bc["emails"] | envs["emails"],
        "phones": wf["phones"] | bc["phones"] | envs["phones"],
    }


# ═════════════════════════════════════════════════════════════════════
# Public API — strip on the send-path
# ═════════════════════════════════════════════════════════════════════
async def strip_admin_owned_recipients(
    *,
    tenant_id: str,
    kind: str,
    channel: str,
    recipients: Iterable[str],
    context: Optional[Dict[str, Any]] = None,
) -> Tuple[List[str], List[Dict[str, str]]]:
    """Subtract admin-owned / tenant-owned addresses from the caller's
    recipient list.

    ``kind`` must be ``"customer_facing"`` for stripping to apply.
    Any other kind (e.g., ``"admin"`` / ``"internal"``) short-circuits
    to a pass-through — internal admin digests still reach admins.

    Returns a tuple ``(kept, stripped)`` where each entry in
    ``stripped`` is ``{"address": <as-passed>, "reason": <source>}``
    for structured logging.  Every stripped recipient is also logged
    at INFO level with the tenant scope so ops sees the guardrail
    firing.
    """
    recip_list = [r for r in recipients if r and str(r).strip()]
    if kind != "customer_facing":
        return list(recip_list), []
    if not tenant_id:
        # Missing tenant — refuse to strip (fail-open); caller
        # decides whether to abort.
        return list(recip_list), []

    deny = await _load_deny_sets(tenant_id)
    kept: List[str] = []
    stripped: List[Dict[str, str]] = []
    for r in recip_list:
        r_s = str(r).strip()
        if channel == "email":
            k = _norm_email(r_s)
            if k and k in deny["emails"]:
                stripped.append({"address": r_s, "reason": "workforce_or_tenant_email"})
                logger.warning(
                    "notifications.deny_list.stripped kind=%s channel=email "
                    "tenant_id=%s address=%s context=%s",
                    kind, tenant_id, r_s, context or {},
                )
                continue
        elif channel == "sms":
            k = _norm_phone(r_s)
            if k and k in deny["phones"]:
                stripped.append({"address": r_s, "reason": "workforce_or_tenant_phone"})
                logger.warning(
                    "notifications.deny_list.stripped kind=%s channel=sms "
                    "tenant_id=%s address=%s context=%s",
                    kind, tenant_id, r_s, context or {},
                )
                continue
        kept.append(r_s)
    return kept, stripped


# ═════════════════════════════════════════════════════════════════════
# R1 — Startup allowlist-hygiene sanity check
# ═════════════════════════════════════════════════════════════════════
def _split_env_csv(name: str) -> Set[str]:
    raw = os.environ.get(name) or ""
    return {v.strip() for v in raw.split(",") if v.strip()}


async def allowlist_overlap_check() -> Dict[str, Any]:
    """R1 · Feb-2026 — Detect when the ``COMMS_TEST_ALLOWLIST_*`` env
    vars contain a live workforce / tenant / from-number address.

    Emits one WARN log line per overlap with:

        notifications.allowlist.overlap kind=<sms|email>
        number=<addr> tenant_ids=<tid1,tid2> sources=<...>

    Always log-only — never blocks startup.  Returns a summary dict
    so callers (and tests) can assert behaviour.
    """
    allow_phones = {_norm_phone(v) for v in _split_env_csv("COMMS_TEST_ALLOWLIST_PHONES") if _norm_phone(v)}
    allow_emails = {_norm_email(v) for v in _split_env_csv("COMMS_TEST_ALLOWLIST_EMAILS") if _norm_email(v)}
    if not allow_phones and not allow_emails:
        return {"overlaps": 0, "checked_phones": 0, "checked_emails": 0,
                "details": []}

    # Walk every tenant so we know WHICH tenants own the collision.
    overlaps: List[Dict[str, Any]] = []
    envs = _env_from_addresses()

    # Env-level overlaps first (tenant-agnostic).
    for p in allow_phones & envs["phones"]:
        overlaps.append({
            "kind": "sms", "value": p,
            "tenant_ids": [], "sources": ["env_from_number"],
        })
    for e in allow_emails & envs["emails"]:
        overlaps.append({
            "kind": "email", "value": e,
            "tenant_ids": [], "sources": ["env_from_email"],
        })

    # Per-tenant scan.
    async for t in db.tenants.find({}, {"_id": 0, "id": 1}):
        tid = t["id"]
        wf = await _tenant_workforce_addresses(tid)
        bc = await _tenant_business_card_addresses(tid)
        for p in (allow_phones & (wf["phones"] | bc["phones"])):
            sources = []
            if p in wf["phones"]:
                sources.append("workforce")
            if p in bc["phones"]:
                sources.append("tenant_business_card")
            _merge_overlap(overlaps, kind="sms", value=p,
                            tenant_id=tid, sources=sources)
        for e in (allow_emails & (wf["emails"] | bc["emails"])):
            sources = []
            if e in wf["emails"]:
                sources.append("workforce")
            if e in bc["emails"]:
                sources.append("tenant_business_card")
            _merge_overlap(overlaps, kind="email", value=e,
                            tenant_id=tid, sources=sources)

    # Emit one WARN per (kind, value).
    for ov in overlaps:
        logger.warning(
            "notifications.allowlist.overlap kind=%s value=%s "
            "tenant_ids=%s sources=%s",
            ov["kind"], ov["value"],
            ",".join(ov["tenant_ids"]) or "-",
            ",".join(ov["sources"]),
        )

    return {
        "overlaps": len(overlaps),
        "checked_phones": len(allow_phones),
        "checked_emails": len(allow_emails),
        "details": overlaps,
    }


def _merge_overlap(
    overlaps: List[Dict[str, Any]], *, kind: str, value: str,
    tenant_id: str, sources: List[str],
) -> None:
    """Dedupe overlaps by (kind, value) so a single number owned by
    N tenants surfaces as one log line with all tenants listed."""
    for ov in overlaps:
        if ov["kind"] == kind and ov["value"] == value:
            if tenant_id and tenant_id not in ov["tenant_ids"]:
                ov["tenant_ids"].append(tenant_id)
            for s in sources:
                if s not in ov["sources"]:
                    ov["sources"].append(s)
            return
    overlaps.append({
        "kind": kind, "value": value,
        "tenant_ids": [tenant_id] if tenant_id else [],
        "sources": list(sources),
    })
