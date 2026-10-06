#!/usr/bin/env python3
"""SMS-RECIPIENT-FIX · Feb-2026 — Customer phone overlap audit.

Surfaces customer records whose ``phone`` field (or any
``mobiles[].number_e164``) collides with a tenant-owned outbound
SMS from-number. Read-only. No writes. No ``--fix`` flag. Exits
0 regardless of hits.

Why this exists
---------------
The user-reported "automated SMS lands at the tenant's own number
instead of the customer's" bug has no code-path misroute (verified
in Phase A pre-ship report, Feb-2026). The resolver on every
automated SMS site correctly reads ``customer.phone``.  The
remaining explanation is a data contamination: at least one
``customers`` row has ``phone`` set to the tenant's
``rc_sms_from_number`` / ``settings.business_card.phone`` / an env
``RC_FROM_NUMBER`` / an entry in
``COMMS_TEST_ALLOWLIST_PHONES``.  When that number IS allowlisted
in preview env, the adapter happily delivers the SMS to it — hence
the tenant's own line receives customer-facing SMS.

Phases A + B of SMS-RECIPIENT-FIX also wire a belt-and-suspenders
``strip_admin_owned_recipients`` guard on every customer-facing
send site, which neutralises this failure mode even when a
contaminated row survives.  This script lets ops see the contaminated
rows directly so they can be cleaned up as a separate cleanup
operation.

Scanned sources (per tenant):
  * ``tenants.rc_sms_from_number``
  * ``tenants.settings.business_card.phone``
  * ``tenants.phone`` (if present on the tenant doc)

Plus (tenant-agnostic env-level sources):
  * ``RC_FROM_NUMBER`` / ``RC_SMS_DEFAULT_FROM`` /
    ``RC_VOICE_DEFAULT_FROM``
  * ``COMMS_TEST_ALLOWLIST_PHONES`` (CSV)

Comparison is normalised to the last-10-digits (digits-only) form
so ``+1 (602) 887-4400``, ``6028874400``, and ``+16028874400`` all
collide. Minimum 4-digit guard rejects typo-only strings.

Usage
-----
::

    cd /app/backend
    python3 -m scripts.audit_customer_phone_overlap
    python3 -m scripts.audit_customer_phone_overlap --tenant-id <uuid>
    python3 -m scripts.audit_customer_phone_overlap --format json

Exit codes
----------
* ``0`` — scan completed. Hits (if any) printed to stdout.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
from typing import Any, Dict, List, Optional, Set

from dotenv import load_dotenv


load_dotenv("/app/backend/.env")


def _late():
    from config import db  # noqa: WPS433
    return db


# ═════════════════════════════════════════════════════════════════════
# Normalisation
# ═════════════════════════════════════════════════════════════════════
def _norm_phone(v: Optional[str]) -> str:
    """Digits-only, last-10. Empty for falsy / < 4 digits."""
    digits = re.sub(r"\D+", "", v or "")
    if len(digits) < 4:
        return ""
    return digits[-10:]


# ═════════════════════════════════════════════════════════════════════
# Env-level from-number collection
# ═════════════════════════════════════════════════════════════════════
def _collect_env_from_numbers() -> Dict[str, Set[str]]:
    """Return a {source_label: {last10 digits}} map so the audit
    report can tell operators WHICH env var owns the collision."""
    out: Dict[str, Set[str]] = {}
    for key in ("RC_FROM_NUMBER", "RC_SMS_DEFAULT_FROM",
                "RC_VOICE_DEFAULT_FROM"):
        v = os.environ.get(key) or ""
        p = _norm_phone(v)
        if p:
            out.setdefault(key, set()).add(p)
    allow = os.environ.get("COMMS_TEST_ALLOWLIST_PHONES") or ""
    for token in allow.split(","):
        p = _norm_phone(token.strip())
        if p:
            out.setdefault("COMMS_TEST_ALLOWLIST_PHONES", set()).add(p)
    return out


# ═════════════════════════════════════════════════════════════════════
# Tenant-level from-number collection
# ═════════════════════════════════════════════════════════════════════
async def _collect_tenant_from_numbers(
    db: Any, tenant_id: Optional[str],
) -> Dict[str, Dict[str, Set[str]]]:
    """Return ``{tenant_id: {source_label: {last10 digits}}}`` so each
    hit can be traced back to the exact tenant field."""
    q: Dict[str, Any] = {}
    if tenant_id:
        q["id"] = tenant_id
    out: Dict[str, Dict[str, Set[str]]] = {}
    projection = {
        "_id": 0, "id": 1, "settings": 1, "phone": 1,
        "rc_sms_from_number": 1,
    }
    async for t in db.tenants.find(q, projection):
        tid = t.get("id") or ""
        per_tenant: Dict[str, Set[str]] = {}
        p = _norm_phone(t.get("rc_sms_from_number"))
        if p:
            per_tenant.setdefault("tenants.rc_sms_from_number",
                                   set()).add(p)
        p = _norm_phone(t.get("phone"))
        if p:
            per_tenant.setdefault("tenants.phone", set()).add(p)
        card = ((t.get("settings") or {}).get("business_card") or {})
        p = _norm_phone(card.get("phone"))
        if p:
            per_tenant.setdefault(
                "tenants.settings.business_card.phone", set(),
            ).add(p)
        if per_tenant:
            out[tid] = per_tenant
    return out


# ═════════════════════════════════════════════════════════════════════
# Customer scan
# ═════════════════════════════════════════════════════════════════════
async def _scan_customers(
    db: Any,
    tenant_map: Dict[str, Dict[str, Set[str]]],
    env_map: Dict[str, Set[str]],
    tenant_id: Optional[str],
) -> List[Dict[str, Any]]:
    hits: List[Dict[str, Any]] = []
    # Flattened per-tenant union for quick membership check.
    tenant_union: Dict[str, Set[str]] = {
        tid: set().union(*srcs.values())
        for tid, srcs in tenant_map.items()
    }
    env_union: Set[str] = set().union(*env_map.values()) if env_map else set()
    q: Dict[str, Any] = {}
    if tenant_id:
        q["tenant_id"] = tenant_id
    projection = {
        "_id": 0, "id": 1, "tenant_id": 1,
        "email": 1, "name": 1, "phone": 1, "mobiles": 1,
    }
    async for c in db.customers.find(q, projection):
        tid = c.get("tenant_id") or ""
        candidates = []
        p_norm = _norm_phone(c.get("phone"))
        if p_norm:
            candidates.append(("customers.phone", c.get("phone"), p_norm))
        for m in (c.get("mobiles") or []):
            if isinstance(m, dict):
                raw = m.get("number_e164") or m.get("number") or ""
                mp = _norm_phone(raw)
                if mp:
                    candidates.append(
                        ("customers.mobiles[].number_e164", raw, mp),
                    )
        tenant_set = tenant_union.get(tid, set())
        tenant_src_map = tenant_map.get(tid, {})
        for field, raw, norm in candidates:
            matched_sources: List[str] = []
            if norm in tenant_set:
                for src_label, digits in tenant_src_map.items():
                    if norm in digits:
                        matched_sources.append(src_label)
            if norm in env_union:
                for env_label, digits in env_map.items():
                    if norm in digits:
                        matched_sources.append(env_label)
            if matched_sources:
                hits.append({
                    "tenant_id": tid,
                    "customer_id": c.get("id"),
                    "name": c.get("name") or "",
                    "email": c.get("email") or "",
                    "matched_field": field,
                    "matched_number": raw,
                    "matched_normalised": norm,
                    "matched_sources": sorted(set(matched_sources)),
                })
    return hits


# ═════════════════════════════════════════════════════════════════════
# Entry point
# ═════════════════════════════════════════════════════════════════════
async def _run(args: argparse.Namespace) -> int:
    db = _late()
    env_map = _collect_env_from_numbers()
    tenant_map = await _collect_tenant_from_numbers(db, args.tenant_id)
    hits = await _scan_customers(db, tenant_map, env_map, args.tenant_id)

    if args.format == "json":
        print(json.dumps({
            "scanned_tenants": len(tenant_map),
            "env_sources": {k: sorted(v) for k, v in env_map.items()},
            "hit_count": len(hits),
            "hits": hits,
        }, indent=2, default=str))
        return 0

    print(
        f"=== SMS-RECIPIENT-FIX audit · "
        f"{len(tenant_map)} tenants scanned · "
        f"{sum(len(v) for v in env_map.values())} env from-numbers ===",
    )
    if env_map:
        print("Env from-numbers:")
        for label, digits in sorted(env_map.items()):
            print(f"  {label}: {sorted(digits)}")
    if not hits:
        print("No contaminated customer records found.")
        return 0
    print(f"{len(hits)} contaminated row(s):")
    for h in hits:
        print(
            f"  tenant={h['tenant_id']} customer={h['customer_id']} "
            f"name={h['name']!r} email={h['email']!r} "
            f"field={h['matched_field']} number={h['matched_number']} "
            f"normalised={h['matched_normalised']} "
            f"sources={h['matched_sources']}",
        )
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Read-only audit — surface customer records whose "
                     "phone overlaps a tenant-owned SMS from-number. "
                     "Never writes. See SMS-RECIPIENT-FIX in handover.",
    )
    ap.add_argument("--tenant-id", default=None,
                     help="Scope the scan to one tenant.")
    ap.add_argument("--format", choices=("table", "json"), default="table")
    args = ap.parse_args()
    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())
