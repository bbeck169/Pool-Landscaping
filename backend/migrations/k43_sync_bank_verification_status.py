"""Phase K43 · Feb-2026 — Sync ``payment_methods.verification_status``
for every ACH (``us_bank_account``) mirror row against Stripe.

Motivation
──────────
K38 bulk-charge and the K43 direct ``charge_ach_on_file`` helper both
gate ACH charges on ``payment_methods.verification_status == "verified"``.
Rows created before K43 shipped never had a verification status
written, so admins today see stale/blank pills in the customer
detail UI and the K38 modal has to guess based on Stripe's live
response.

This migration is a one-shot reconciliation:

  1. For every ``payment_methods`` row where ``type == "us_bank_account"``,
     retrieve the corresponding Stripe ``PaymentMethod`` and map its
     ``us_bank_account.status_details.verification`` (or the K37 legacy
     shape) onto our canonical set:
        * ``verified``               — Stripe reports the PM as chargeable.
        * ``pending_microdeposit``   — SetupIntent still expecting the
                                        customer to confirm cent amounts.
        * ``unverified``             — Stripe considers the PM unusable.
        * ``unknown``                — Stripe returned a state we
                                        haven't mapped (rare).
  2. Update the mirror row + emit an audit event so ops can see
     exactly which PMs flipped.
  3. Idempotent — safe to re-run.  A sentinel row lands in ``migrations``
     under the K33 boot-check pattern.

Behaviour
─────────
* Dry-run (default): scans and reports per-tenant counts + a short
  sample list.  Writes NOTHING.
* ``--apply``: mutates mirror rows.

Boot-wiring
───────────
The BG runner ``run()`` (below) is imported by ``server.py`` on
startup after the K33 sentinel check.  It short-circuits when the
sentinel is already present so we don't hit Stripe on every reboot.

Usage
─────
    cd /app/backend && python -m migrations.k43_sync_bank_verification_status
    cd /app/backend && python -m migrations.k43_sync_bank_verification_status --apply
    cd /app/backend && python -m migrations.k43_sync_bank_verification_status --tenant <tid>
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))

from config import db, logger  # noqa: E402

_SENTINEL_KEY = "k43_sync_bank_verification_status_v1"


# ─────────────────────────────────────────────────────────────────────
# Stripe status → canonical mapping
# ─────────────────────────────────────────────────────────────────────
def _canonical_from_stripe(pm: Dict[str, Any]) -> str:
    """Extract the canonical verification status from a Stripe
    ``PaymentMethod`` dict.

    Stripe surfaces the state in two places depending on the
    verification method used:

      * ``us_bank_account.status_details.verification`` — Financial
        Connections path.
      * ``us_bank_account.financial_connections_account`` presence +
        ``us_bank_account.linked_account`` — instant path.
      * ``us_bank_account.microdeposit_type`` presence — micro-deposit
        path (state = ``pending`` until the customer confirms).

    We collapse everything into the four canonical states used by
    the K38 bulk modal + the K43 charge helper.
    """
    if not pm:
        return "unknown"
    us = (pm.get("us_bank_account") or {}) if isinstance(pm, dict) else {}
    # Preferred — Stripe's own verification state.
    v_state = ((us.get("status_details") or {}).get("verification") or "").lower()
    if v_state == "verified":
        return "verified"
    if v_state in ("pending", "pending_microdeposit"):
        return "pending_microdeposit"
    # Financial Connections rows w/o an explicit state — presence of
    # a linked FC account implies verified (FC never surfaces
    # unverified rows here).
    if us.get("financial_connections_account") or us.get("linked_account"):
        return "verified"
    # Micro-deposit path — customer hasn't confirmed the cents yet.
    if us.get("microdeposit_type"):
        return "pending_microdeposit"
    return "unverified"


# ─────────────────────────────────────────────────────────────────────
# Scan + apply
# ─────────────────────────────────────────────────────────────────────
async def _load_tenant_ids(only: Optional[str]) -> List[str]:
    if only:
        return [only]
    return await db.tenants.distinct("id")


async def _scan_tenant(tenant_id: str) -> Dict[str, Any]:
    """Return the flip plan for one tenant without mutating."""
    # Lazy import so a missing STRIPE_SECRET_KEY doesn't crash the
    # module import.
    from services.payments import stripe_charge as stripe_svc
    stripe_svc._init_api_key()

    scanned = 0
    already_verified = 0
    flips: List[Dict[str, Any]] = []
    async for row in db.payment_methods.find(
        {"tenant_id": tenant_id, "type": "us_bank_account",
         "provider": "stripe"},
        {"_id": 0, "id": 1, "customer_id": 1,
         "provider_payment_method_id": 1,
         "verification_status": 1, "last4": 1},
    ):
        scanned += 1
        pm_id = row.get("provider_payment_method_id") or ""
        current = (row.get("verification_status") or "").lower() or None
        if not pm_id:
            continue
        try:
            pm_obj = await stripe_svc._to_thread(
                stripe_svc._stripe.PaymentMethod.retrieve, pm_id,
            )
            pm_dict = stripe_svc._asdict(pm_obj) if pm_obj else {}
        except Exception as exc:  # pragma: no cover — resilience
            logger.info(
                "[k43-migrate] retrieve failed cid=%s pm=%s: %s",
                row.get("customer_id"), pm_id, exc,
            )
            continue
        desired = _canonical_from_stripe(pm_dict)
        if current == desired:
            if desired == "verified":
                already_verified += 1
            continue
        flips.append({
            "customer_id": row.get("customer_id"),
            "pm_id": pm_id,
            "last4": row.get("last4") or "",
            "before": current,
            "after": desired,
        })
    return {
        "tenant_id": tenant_id,
        "scanned": scanned,
        "already_verified": already_verified,
        "flips": flips,
    }


async def _apply_tenant(tenant_id: str, rep: Dict[str, Any]) -> int:
    applied = 0
    now = datetime.now(timezone.utc).isoformat()
    for f in rep["flips"]:
        r = await db.payment_methods.update_one(
            {"tenant_id": tenant_id, "customer_id": f["customer_id"],
             "provider_payment_method_id": f["pm_id"],
             "provider": "stripe"},
            {"$set": {"verification_status": f["after"],
                       "k43_sync_before": f["before"] or "",
                       "k43_synced_at": now}},
        )
        if r.modified_count:
            applied += 1
            try:
                await db.audit_events.insert_one({
                    "id": f"k43-sync-{f['customer_id']}-{f['pm_id'][:8]}",
                    "event_type": "bank_verification_synced_k43",
                    "tenant_id": tenant_id,
                    "customer_id": f["customer_id"],
                    "payment_method_id": f["pm_id"],
                    "before": f["before"] or "",
                    "after": f["after"],
                    "timestamp": now,
                    "source": "migrations.k43_sync_bank_verification_status",
                })
            except Exception:  # pragma: no cover — audit best-effort
                pass
    return applied


async def _write_sentinel(stats: Dict[str, Any], mode: str) -> None:
    doc = {
        "id": f"migrations::{_SENTINEL_KEY}",
        "key": _SENTINEL_KEY,
        "mode": mode,
        "stats": stats,
        "ran_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.migrations.update_one(
        {"key": _SENTINEL_KEY}, {"$set": doc}, upsert=True,
    )


async def main(
    apply: bool = False, tenant_id: Optional[str] = None,
) -> Dict[str, Any]:
    tenant_ids = await _load_tenant_ids(tenant_id)
    print(f"[k43] tenants: {len(tenant_ids)} · apply={apply}")
    total_scanned = 0
    total_flips = 0
    all_reports: List[Dict[str, Any]] = []
    for tid in tenant_ids:
        rep = await _scan_tenant(tid)
        all_reports.append(rep)
        total_scanned += rep["scanned"]
        total_flips += len(rep["flips"])
        print(
            f"[k43] tenant={tid}: scanned={rep['scanned']} "
            f"already_verified={rep['already_verified']} "
            f"flips_pending={len(rep['flips'])}"
        )
        for f in rep["flips"][:5]:
            print(
                f"    · pm={f['pm_id'][:12]}… "
                f"last4={f['last4']} {f['before']} → {f['after']}"
            )
        if apply and rep["flips"]:
            applied = await _apply_tenant(tid, rep)
            print(f"[k43] tenant={tid}: applied={applied}")

    stats = {"tenants": len(tenant_ids),
             "scanned": total_scanned, "flips": total_flips}
    print(f"[k43] SUMMARY: {stats}")
    if apply:
        await _write_sentinel(stats, "apply")
    return {"stats": stats, "reports": all_reports}


# ─────────────────────────────────────────────────────────────────────
# Boot-wired background runner (K33 pattern)
# ─────────────────────────────────────────────────────────────────────
async def run() -> None:
    """One-shot BG runner invoked from ``server.py`` at boot.

    Idempotent — if the sentinel is already present in ``migrations``
    we short-circuit so we don't re-hit Stripe on every restart.
    """
    try:
        existing = await db.migrations.find_one(
            {"key": _SENTINEL_KEY}, {"_id": 0, "mode": 1},
        )
        if existing and existing.get("mode") == "apply":
            logger.info("[k43-migrate] sentinel present — skipping")
            return
        logger.info("[k43-migrate] starting boot-wired sync")
        await main(apply=True, tenant_id=None)
        logger.info("[k43-migrate] complete")
    except Exception as exc:  # pragma: no cover — resilience
        logger.warning("[k43-migrate] boot run failed: %s", exc)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--tenant", default=None)
    ns = parser.parse_args()
    asyncio.run(main(apply=ns.apply, tenant_id=ns.tenant))
