"""P2 #10a (+1b corrective) · Feb-2026 — Seed migration for the 2
MVP transactional-template slugs that are genuinely net-new (no
prior global or per-tenant seed migration).

Scope
─────
The P2 #10 audit (Flag 1) enumerated 11 transactional slugs. 9 are
already seeded by prior migrations:

  * ``job_completion_sms`` ← ``migrations/te_portal_job_templates_seed.py``
    (1780+ tenant rows at Commit 1b landing)
  * ``quote_declined_owner_email`` ← ``migrations/seed_quote_accepted_declined_templates.py``
  * ``quote_accepted_owner_email`` (not in our registry; sibling)
  * ``portal_invite_email`` ← ``migrations/te_portal_job_templates_seed.py``
  * ``lead_conversion_welcome_email`` / ``_sms`` ← ``migrations/seed_lead_conversion_welcome_template.py``
  * ``invoice_past_due_email`` / ``estimate_reminder_email`` ← pre-K72 seed path
  * ``password_reset_email`` + ``portal_chat_admin_notify_sms`` are
    hardcoded-only (TD-16 covers migrating them to DB; seed will
    happen when those slugs are first wired).

The 2 slugs below are the genuinely net-new MVP additions wired in
Commit 2 (``P2 #10b``):

  * ``welcome_on_first_accept_email``
  * ``quote_decline_admin_sms``

(Commit 1 originally included ``quote_decline_admin_email`` here but
the subsequent 1b correction removed it — a prior migration already
seeds ``quote_declined_owner_email``, which is the wire-level code
``services/quote_notifications.py::render_email`` reads today. No
split-brain slug.)

Idempotency
───────────
* **Boot sentinel** — ``db.migrations`` doc with ``id =
  feb2026_seed_transactional_templates_v1``. First run scans all
  tenants + stamps the sentinel. Second boot returns ``skipped=True``.
* **Per-tenant, per-slug secondary guard** — ``find_one({tenant_id,
  code})`` before every insert.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List

from config import db
from utils import new_id, now_iso


logger = logging.getLogger("seed_transactional_templates")


_SENTINEL_ID = "feb2026_seed_transactional_templates_v1"


# Minimal seed bodies — kept purposely short so the admin sees the
# editor as "my tenant has a visible default I can polish" rather
# than "the system shipped with a wall of boilerplate text." The
# richer production fallbacks live in the hardcoded branches in
# ``services/customer_welcome_email.py`` +
# ``services/quote_notifications.py::render_sms``.
_MVP_SEEDS: List[Dict[str, Any]] = [
    {
        "code": "credit_apply_backfill_summary",
        "channel": "email",
        "name": "Credit auto-apply · Backfill summary",
        "category": "admin",
        "subject": "Credit auto-apply backfill summary · {{run_id}}",
        "body": (
            "Credit auto-apply backfill completed.\n\n"
            "Customers touched: {{customers_touched}}\n"
            "Invoices updated:  {{invoices_updated}}\n"
            "Total applied:     ${{total_amount_applied}}\n"
            "Run id:            {{run_id}}\n"
        ),
    },
    {
        "code": "welcome_on_first_accept_email",
        "channel": "email",
        "name": "Welcome · First-accept",
        "category": "welcome",
        "subject": "Welcome to {{company_name}}!",
        "body": (
            "Hi {{customer_first_name}},\n\n"
            "Thanks for choosing {{company_name}} — we're glad to have "
            "you on board.\n\nYou can access your customer portal here: "
            "{{portal_url}}\n\n— The {{company_name}} team"
        ),
    },
    {
        "code": "quote_decline_admin_sms",
        "channel": "sms",
        "name": "Quote declined · Admin SMS",
        "category": "quotes",
        "subject": None,
        "body": "{{customer_name}} declined quote #{{quote_short_id}}.",
    },
]


async def _ensure_seed(tenant_id: str, seed: Dict[str, Any]) -> bool:
    """Insert the seed row for ``(tenant_id, seed['code'])`` if it's
    absent; return True if an insert happened. Idempotent on repeat
    runs (same ``(tenant_id, code)`` → ``find_one`` returns truthy →
    skip)."""
    existing = await db.marketing_templates.find_one(
        {"tenant_id": tenant_id, "code": seed["code"]},
        {"_id": 0, "id": 1},
    )
    if existing:
        return False
    doc = {
        "id": new_id(),
        "tenant_id": tenant_id,
        "code": seed["code"],
        "name": seed["name"],
        "channel": seed["channel"],
        "category": seed["category"],
        "subject": seed["subject"],
        "body": seed["body"],
        "active": True,
        "system": True,
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "created_by": None,  # system-authored
    }
    await db.marketing_templates.insert_one(doc)
    return True


async def seed_transactional_templates_for_tenant(
    tenant_id: str,
) -> Dict[str, Any]:
    """Seed all 3 MVP slugs for a single tenant. Returns a per-slug
    insert report. Used both by the all-tenants boot migration and
    by ``routers/tenants.py::create_tenant`` as a provisioning hook
    (same pattern as ``seed_system_templates_for_tenant``)."""
    inserted: List[str] = []
    skipped: List[str] = []
    for seed in _MVP_SEEDS:
        did = await _ensure_seed(tenant_id, seed)
        (inserted if did else skipped).append(seed["code"])
    return {
        "tenant_id": tenant_id,
        "inserted": inserted,
        "skipped": skipped,
    }


async def seed_transactional_templates_all_tenants() -> Dict[str, Any]:
    """Boot migration — iterate every active tenant, call the
    per-tenant helper, stamp the sentinel. Idempotent via the
    sentinel + the per-slug ``_ensure_seed`` guard."""
    sentinel = await db.migrations.find_one({"id": _SENTINEL_ID}, {"_id": 0})
    if sentinel:
        return {"skipped": True, "reason": "sentinel_already_stamped"}

    reports: List[Dict[str, Any]] = []
    total_inserted = 0
    total_skipped = 0
    tenants_processed = 0
    tenants_failed: List[Dict[str, Any]] = []

    async for t in db.tenants.find(
        {"$or": [{"active": {"$ne": False}}, {"active": {"$exists": False}}]},
        {"_id": 0, "id": 1},
    ):
        tid = t.get("id")
        if not tid:
            continue
        try:
            report = await seed_transactional_templates_for_tenant(tid)
            reports.append(report)
            total_inserted += len(report["inserted"])
            total_skipped += len(report["skipped"])
            tenants_processed += 1
        except Exception as e:
            tenants_failed.append({"tenant_id": tid,
                                     "error": f"{type(e).__name__}: {e}"})
            logger.warning(
                "[seed_transactional_templates] tenant=%s failed: %s", tid, e,
            )

    summary = {
        "sentinel_id": _SENTINEL_ID,
        "tenants_processed": tenants_processed,
        "tenants_failed": tenants_failed,
        "total_inserted": total_inserted,
        "total_skipped": total_skipped,
    }
    await db.migrations.insert_one({
        "id": _SENTINEL_ID,
        "stamped_at": now_iso(),
        "summary": summary,
    })
    logger.info(
        "[seed_transactional_templates] boot migration complete: %s", summary,
    )
    return summary
