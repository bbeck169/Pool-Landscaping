"""Phase DOOR-HANGER · Feb 2026 — Seed the editable Door Hanger template.

Upserts a single canonical ``marketing_templates`` row keyed by
``code="door_hanger_job_completed"``.  When
:func:`routers.workstream_service_log._build_door_hanger_email`
composes the "job completed" email, it looks up this row first and
renders the ``body`` / ``subject`` through
:func:`services.marketing.merge_tags.render_template` — meaning a
tenant that clones + edits the row via the UI overrides the
hard-coded fallback.

Idempotency contract
--------------------
* First run inserts the row via ``$setOnInsert`` — every field
  becomes the DOOR-HANGER default.
* Second and subsequent runs are a no-op: an existing row is
  detected by ``code`` alone and its ``body`` / ``subject`` are
  preserved verbatim (a tenant may have edited them via the
  marketing-templates UI, and this migration is not permitted to
  clobber their work).
* Safe to run against a database that already contains the row —
  the ``$setOnInsert`` operator only writes on insert, so the
  ``updated_at`` field mirrors the ``created_at`` on first insert
  and never mutates on re-run.

Run in-session::

    python -m migrations.seed_door_hanger_template
"""
from __future__ import annotations

import asyncio
import sys

sys.path.insert(0, "/app/backend")

from config import db                       # noqa: E402  (post-sys.path)
from utils import new_id, now_iso           # noqa: E402


MIGRATION_NAME = "seed_door_hanger_template"
TEMPLATE_CODE = "door_hanger_job_completed"


# ═══════════════════════════════════════════════════════════════════
# DOOR-HANGER default subject + body.  The body is a merge-tag-driven
# shell — the section chunks (hero, water test, elevated CTA,
# chemicals, checklist, notes, portal CTA, footer) are pre-rendered
# by ``_build_door_hanger_email`` and slotted in via the
# ``DOOR_HANGER_<...>_HTML`` ctx-injection tags registered in
# ``services/marketing/merge_tags.py``.  ``{{JOB_PHOTOS}}`` renders
# the photo gallery via its own resolver so tenants that reposition
# the tag or copy it to other templates keep the responsive-grid
# semantics.
# ═══════════════════════════════════════════════════════════════════
DOOR_HANGER_SUBJECT_DEFAULT = "Job Completed - {{COMPANY_NAME}}"

DOOR_HANGER_BODY_DEFAULT = (
    '<table role="presentation" cellpadding="0" cellspacing="0" '
    'border="0" width="100%" style="border-collapse:collapse;'
    'background:#F1F5F9;">'
    '<tr><td align="center" style="padding:24px 12px;">'
    '<table role="presentation" cellpadding="0" cellspacing="0" '
    'border="0" width="640" style="border-collapse:collapse;'
    'max-width:640px;font-family:Inter,Arial,sans-serif;color:#0F172A;">'
    '<tr><td>'
    '{{DOOR_HANGER_HERO_HTML}}'
    '{{DOOR_HANGER_WATER_TEST_HTML}}'
    '{{DOOR_HANGER_ELEVATED_CTA_HTML}}'
    '{{DOOR_HANGER_CHEMICALS_HTML}}'
    '{{DOOR_HANGER_CHECKLIST_HTML}}'
    '{{DOOR_HANGER_NOTES_HTML}}'
    '{{JOB_PHOTOS}}'
    '{{DOOR_HANGER_PORTAL_CTA_HTML}}'
    '{{DOOR_HANGER_FOOTER_HTML}}'
    '</td></tr></table>'
    '</td></tr></table>'
)


def _seed_row_setoninsert() -> dict:
    """Return the ``$setOnInsert`` payload — the shape a fresh row
    gets on first insert.  Uses a computed ``created_at`` / new id
    on each call so a fresh insert on a fresh DB reflects the run
    time.
    """
    now = now_iso()
    return {
        "id": new_id(),
        "code": TEMPLATE_CODE,
        "tenant_id": None,          # global default; tenants clone to override
        "name": "Door Hanger — Job Completed",
        "category": "service_completed",
        "channel": "email",
        "kind": "transactional",
        "subject": DOOR_HANGER_SUBJECT_DEFAULT,
        "body": DOOR_HANGER_BODY_DEFAULT,
        "is_system": True,
        "is_default": True,
        "editable": True,
        "created_at": now,
        "updated_at": now,
    }


async def run() -> dict:
    """Upsert the DOOR-HANGER default row idempotently.

    Returns a ``{"inserted": bool, "code": str}`` summary suitable
    for the P21 structural-migration logger.
    """
    result = await db.marketing_templates.update_one(
        {"code": TEMPLATE_CODE},
        {"$setOnInsert": _seed_row_setoninsert()},
        upsert=True,
    )
    inserted = bool(result.upserted_id)
    return {"inserted": inserted, "code": TEMPLATE_CODE}


if __name__ == "__main__":
    summary = asyncio.run(run())
    print(f"[seed_door_hanger_template] {summary}")
