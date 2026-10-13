"""P2 #10a · Feb-2026 — Seed migration for the 3 MVP transactional
template slugs that are NOT already present in production tenants.

Scope
─────
The P2 #10 audit (Flag 1) enumerated 11 transactional slugs. 8 of
those are already written to ``db.marketing_templates`` across one
or more tenants by prior migrations (``te_portal_job_templates_seed``,
``seed_lead_conversion_welcome_template``, etc.). The 3 slugs below
are the net-new MVP additions wired in Commit 2 (``P2 #10b``):

  * ``welcome_on_first_accept_email``
  * ``quote_decline_admin_email``
  * ``quote_decline_admin_sms``

For each active tenant missing one of these ``(tenant_id, code)``
pairs, this migration inserts a seed row with:

  * ``active: true``         — ready to use (admin can disable via
    the Commit-3 editor if they'd rather fall back to the hardcoded
    body)
  * ``system: true``         — matches the shape of
    ``seed_system_templates.py`` so the DELETE guard already in
    place (409 → "deactivate instead") protects these too.
  * ``code: "<slug>"``        — the discriminator that makes the row
    show up in the transactional editor UI (per audit Flag 4).

Fallback body text is INTENTIONALLY MINIMAL — the seed row carries
a short "safe default" that gets admin's eyes on the editor. The
richer production bodies live in the hardcoded fallback branches
in ``services/customer_welcome_email.py`` +
``services/quote_notifications.py``; those remain the source of
truth for text until an admin edits the DB row.

Idempotency
───────────
* **Boot sentinel** — ``db.migrations`` doc with ``id =
  feb2026_seed_transactional_templates_v1``. First run scans all
  tenants + stamps the sentinel. Second boot returns ``skipped=True``
  immediately.
* **Per-tenant, per-slug secondary guard** — even when the sentinel
  hasn't fired for a brand-new tenant, ``find_one({tenant_id, code})``
  before every insert prevents double-writes.
* Pytest-covered: ``test_p2_10a_transactional_registry_and_seed.py``
  pins the idempotency + per-slug seed insertion behaviour.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Set

from config import db
from utils import new_id, now_iso


logger = logging.getLogger("seed_transactional_templates")


_SENTINEL_ID = "feb2026_seed_transactional_templates_v1"


# Minimal seed bodies — kept purposely short so the admin sees the
# editor as "my tenant has a visible default I can polish" rather
# than "the system shipped with a wall of boilerplate text I need
# to understand". Admins editing these REPLACES the body entirely;
# the hardcoded production fallback branch is a sibling path that
# only fires when the DB row is absent / inactive.
_MVP_SEEDS: List[Dict[str, Any]] = [
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
        "code": "quote_decline_admin_email",
        "channel": "email",
        "name": "Quote declined · Admin notification",
        "category": "quotes",
        "subject": "Quote #{{quote_number}} declined by {{customer_name}}",
        "body": (
            "{{customer_name}} declined quote #{{quote_number}}.\n\n"
            "Reason: {{decline_reason}}"
        ),
    },
    {
        "code": "quote_decline_admin_sms",
        "channel": "sms",
        "name": "Quote declined · Admin SMS",
        "category": "quotes",
        "subject": None,
        "body": "Quote #{{quote_number}} declined by {{customer_name}}.",
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
