#!/usr/bin/env python3
"""SMS-RECIPIENT-FIX · Feb-2026 — Customer phone overlap audit (+ cleanup).

Surfaces customer records whose ``phone`` field (or any
``mobiles[].number_e164``) collides with a tenant-owned outbound
SMS from-number. Read-only by default. Optional ``--fix`` planner +
``--confirm`` apply mode blanks the contaminated field values and
writes an audit trail to the ``customer_phone_cleanup_log`` Mongo
collection.

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
rows directly, and (via ``--fix --confirm``) perform the actual
data cleanup once the plan has been reviewed.

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

Cleanup behaviour (``--fix`` / ``--fix --confirm``)
---------------------------------------------------
* ``--fix`` alone → **DRY-RUN**. Prints the write plan (per-customer
  diff) and exits ``0`` without touching any document.
* ``--fix --confirm`` → **APPLY**. Prints the plan, then (unless
  ``--yes`` is also passed) prints a 3-second countdown, then
  performs the writes atomically per-customer.
* Writes blank:
    - ``customers.phone`` → ``""`` when the stored value overlaps.
    - ``customers.mobiles[i].number_e164`` → ``""`` for each mobile
      entry whose number overlaps. The array's ordering, ``label``,
      ``is_primary``, and all other fields on the entry are
      preserved verbatim.
* An append-only audit trail is written to the
  ``customer_phone_cleanup_log`` Mongo collection. One row per
  blanked field with shape::

    {
      "run_id":          "<uuid4 per invocation>",
      "tenant_id":       "<customer's tenant_id>",
      "customer_id":     "<customer's id>",
      "field":           "phone" | "mobiles[<idx>].number_e164",
      "old_value":       "<raw string prior to blanking>",
      "new_value":       "",
      "matched_sources": ["tenants.rc_sms_from_number", ...],
      "cleaned_at":      "<ISO-8601 UTC timestamp>"
    }

* Idempotent — re-running ``--fix --confirm`` after cleanup finds
  zero overlapping rows and performs zero writes.

Usage
-----
::

    cd /app/backend
    # Read-only audit (default)
    python3 -m scripts.audit_customer_phone_overlap
    python3 -m scripts.audit_customer_phone_overlap --tenant-id <uuid>
    python3 -m scripts.audit_customer_phone_overlap --format json

    # Cleanup planner (prints plan, no writes)
    python3 -m scripts.audit_customer_phone_overlap --fix

    # Cleanup apply (prints plan, countdown, then writes)
    python3 -m scripts.audit_customer_phone_overlap --fix --confirm
    python3 -m scripts.audit_customer_phone_overlap --fix --confirm --yes

Exit codes
----------
* ``0`` — scan / dry-run completed successfully (hits may or may
  not be present; dry-runs are informational).
* ``0`` — ``--fix --confirm`` write completed successfully.
* ``1`` — a Mongo write failed during ``--fix --confirm``.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

from dotenv import load_dotenv


load_dotenv("/app/backend/.env")


# Cleanup audit trail collection — append-only, written by the
# ``--fix --confirm`` path. One row per blanked field. See module
# docstring for the exact row shape.
CLEANUP_LOG_COLLECTION = "customer_phone_cleanup_log"


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
# Cleanup helpers
# ═════════════════════════════════════════════════════════════════════
def _utcnow_iso() -> str:
    """ISO-8601 UTC timestamp (``...+00:00``). Stored on every audit row."""
    return datetime.now(timezone.utc).isoformat()


def _group_hits_by_customer(
    hits: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Collapse the flat hit list into per-customer plan rows."""
    by_cid: Dict[str, Dict[str, Any]] = {}
    for h in hits:
        cid = h["customer_id"]
        row = by_cid.setdefault(cid, {
            "customer_id": cid,
            "tenant_id": h["tenant_id"],
            "name": h.get("name") or "",
            "email": h.get("email") or "",
            "hits": [],
        })
        row["hits"].append(h)
    # Stable ordering helps diff review.
    return sorted(
        by_cid.values(), key=lambda r: (r["tenant_id"], r["customer_id"]),
    )


def _print_plan(plan: List[Dict[str, Any]]) -> None:
    total_fields = sum(len(p["hits"]) for p in plan)
    print(
        f"=== Cleanup plan: {len(plan)} customer doc(s), "
        f"{total_fields} field value(s) to blank ===",
    )
    for p in plan:
        print(
            f"  tenant={p['tenant_id']} customer={p['customer_id']} "
            f"name={p['name']!r} email={p['email']!r}",
        )
        for h in p["hits"]:
            print(
                f"    - field={h['matched_field']} "
                f"old={h['matched_number']!r} new='' "
                f"sources={h['matched_sources']}",
            )


async def _apply_cleanup(
    db: Any,
    hits: List[Dict[str, Any]],
    run_id: str,
    yes: bool,
) -> Tuple[int, int, int]:
    """Blank contaminated field values + write audit rows.

    Returns ``(docs_updated, mongo_update_calls, audit_rows_written)``.
    Raises on write failure (surfaced to ``main()`` as exit code 1).
    """
    plan = _group_hits_by_customer(hits)
    if not plan:
        return (0, 0, 0)

    if not yes:
        print("Applying in 3 second(s)... (pass --yes to skip countdown)")
        for i in (3, 2, 1):
            print(f"  {i}...", flush=True)
            time.sleep(1)

    cleaned_at = _utcnow_iso()
    docs_updated = 0
    update_calls = 0
    audit_rows_written = 0

    for p in plan:
        tenant_id = p["tenant_id"]
        cid = p["customer_id"]
        doc = await db.customers.find_one(
            {"id": cid, "tenant_id": tenant_id},
        )
        if not doc:
            print(
                f"  skip tenant={tenant_id} customer={cid} "
                f"(doc disappeared between scan and apply)",
            )
            continue
        updates: Dict[str, Any] = {}
        log_rows: List[Dict[str, Any]] = []
        # --- phone field --------------------------------------------
        phone_hits = [h for h in p["hits"]
                       if h["matched_field"] == "customers.phone"]
        if phone_hits:
            old = doc.get("phone") or ""
            if old != "":
                updates["phone"] = ""
                # One audit row covers the phone field; collect every
                # distinct source label across phone_hits (should be
                # a single hit per customer in practice).
                sources: Set[str] = set()
                for ph in phone_hits:
                    sources.update(ph["matched_sources"])
                log_rows.append({
                    "run_id": run_id,
                    "tenant_id": tenant_id,
                    "customer_id": cid,
                    "field": "phone",
                    "old_value": old,
                    "new_value": "",
                    "matched_sources": sorted(sources),
                    "cleaned_at": cleaned_at,
                })
        # --- mobiles[].number_e164 ----------------------------------
        mobile_hits = [
            h for h in p["hits"]
            if h["matched_field"] == "customers.mobiles[].number_e164"
        ]
        if mobile_hits:
            mobiles_in = list(doc.get("mobiles") or [])
            # Map {normalised_last10 -> set(matched_sources)}.
            targets: Dict[str, Set[str]] = {}
            for mh in mobile_hits:
                targets.setdefault(
                    mh["matched_normalised"], set(),
                ).update(mh["matched_sources"])
            mobiles_out: List[Any] = []
            mutated = False
            for idx, m in enumerate(mobiles_in):
                if not isinstance(m, dict):
                    mobiles_out.append(m)
                    continue
                raw = m.get("number_e164") or m.get("number") or ""
                norm = _norm_phone(raw)
                if norm and norm in targets:
                    new_entry = dict(m)
                    new_entry["number_e164"] = ""
                    mobiles_out.append(new_entry)
                    mutated = True
                    log_rows.append({
                        "run_id": run_id,
                        "tenant_id": tenant_id,
                        "customer_id": cid,
                        "field": f"mobiles[{idx}].number_e164",
                        "old_value": raw,
                        "new_value": "",
                        "matched_sources": sorted(targets[norm]),
                        "cleaned_at": cleaned_at,
                    })
                else:
                    mobiles_out.append(m)
            if mutated:
                updates["mobiles"] = mobiles_out
        # --- commit per-customer -----------------------------------
        if updates:
            try:
                res = await db.customers.update_one(
                    {"id": cid, "tenant_id": tenant_id},
                    {"$set": updates},
                )
            except Exception as exc:
                raise RuntimeError(
                    f"customers.update_one failed for "
                    f"tenant={tenant_id} customer={cid}: {exc}",
                ) from exc
            update_calls += 1
            if (res.modified_count or 0) > 0 or (res.matched_count or 0) > 0:
                docs_updated += 1
            if log_rows:
                try:
                    await db[CLEANUP_LOG_COLLECTION].insert_many(log_rows)
                except Exception as exc:
                    raise RuntimeError(
                        f"{CLEANUP_LOG_COLLECTION}.insert_many failed "
                        f"for tenant={tenant_id} customer={cid}: {exc}",
                    ) from exc
                audit_rows_written += len(log_rows)
            print(
                f"  cleaned tenant={tenant_id} customer={cid} "
                f"fields={sorted(updates.keys())}",
            )
    return (docs_updated, update_calls, audit_rows_written)


# ═════════════════════════════════════════════════════════════════════
# Entry point
# ═════════════════════════════════════════════════════════════════════
async def _run(args: argparse.Namespace) -> int:
    db = _late()
    env_map = _collect_env_from_numbers()
    tenant_map = await _collect_tenant_from_numbers(db, args.tenant_id)
    hits = await _scan_customers(db, tenant_map, env_map, args.tenant_id)

    if args.format == "json" and not args.fix:
        print(json.dumps({
            "scanned_tenants": len(tenant_map),
            "env_sources": {k: sorted(v) for k, v in env_map.items()},
            "hit_count": len(hits),
            "hits": hits,
        }, indent=2, default=str))
        return 0

    if not args.fix:
        # Standard read-only audit report (pre-existing behaviour).
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

    # ── --fix path (dry-run OR apply) ────────────────────────────────
    run_id = str(uuid.uuid4())
    plan = _group_hits_by_customer(hits)
    if not hits:
        print("No contaminated customer records found — nothing to clean.")
        return 0
    _print_plan(plan)
    if not args.confirm:
        print(
            "\nDry-run — no writes applied. "
            "Pass --fix --confirm to apply (add --yes to skip countdown).",
        )
        return 0
    print(
        f"\n--fix --confirm requested. run_id={run_id} "
        f"audit_collection={CLEANUP_LOG_COLLECTION}",
    )
    try:
        docs, calls, audit_rows = await _apply_cleanup(
            db, hits, run_id, args.yes,
        )
    except Exception as exc:
        print(f"ERROR during cleanup: {exc}", file=sys.stderr)
        return 1
    print(
        f"\n=== Cleanup complete · run_id={run_id} · "
        f"updated={docs} doc(s) · mongo_update_calls={calls} · "
        f"audit_rows={audit_rows} ===",
    )
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Audit (and optionally clean up) customer records "
                     "whose phone / mobile numbers overlap a tenant-owned "
                     "SMS from-number. Read-only by default; pass --fix "
                     "--confirm to apply the cleanup. See "
                     "SMS-RECIPIENT-FIX / SMS-DATA-CLEANUP in handover.",
    )
    ap.add_argument("--tenant-id", default=None,
                     help="Scope the scan / cleanup to one tenant.")
    ap.add_argument("--format", choices=("table", "json"), default="table",
                     help="Output format for the read-only audit report "
                          "(ignored when --fix is set).")
    ap.add_argument(
        "--fix", action="store_true",
        help="Enable cleanup planner. Alone (without --confirm) prints "
             "the write plan and exits 0 without touching Mongo.",
    )
    ap.add_argument(
        "--confirm", action="store_true",
        help="Required alongside --fix to actually perform the writes. "
             "Without --confirm, --fix is a dry-run.",
    )
    ap.add_argument(
        "--yes", action="store_true",
        help="Skip the 3-second countdown before --fix --confirm writes. "
             "Intended for CI / scripted runs.",
    )
    args = ap.parse_args()
    if args.confirm and not args.fix:
        ap.error("--confirm requires --fix")
    if args.yes and not args.fix:
        ap.error("--yes requires --fix (and typically --confirm)")
    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())
