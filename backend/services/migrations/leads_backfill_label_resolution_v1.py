"""Phase L2 · Feb-2026 — Historical lead backfill via label resolution.

Re-runs the L2 label-aware extractor
(``services.lead_extraction.extract_contact_fields_with_schema``)
against every lead that carries a ``submission_id`` link back to a
``form_submissions`` row.  For each canonical field the fixed
extractor now resolves, we ``$set`` it on the lead **only when the
lead's current value is empty / null** — hand-corrected values are
never touched.

Idempotency
-----------
A second run produces zero writes because the "empty target" gate
short-circuits when the first run has already filled every field
the extractor could recover.

Audit
-----
One entry per updated lead is written to ``db.audit_logs`` with:

.. code-block:: python

    {
      "action": "leads.backfill.label_resolution_v1",
      "target_type": "lead",
      "target_id": <lead.id>,
      "actor_user_id": <caller.id>,
      "run_id": <one-per-migration uuid>,
      "backfilled_from_submission_id": <submission.id>,
      "fields_written": [<canonical field names…>],
    }
"""
from __future__ import annotations

import logging
import uuid
from typing import Any, Dict, List, Optional

from services.lead_extraction import extract_contact_fields_with_schema
from utils import now_iso

logger = logging.getLogger("pool_crm")


# Canonical field → target column on ``db.leads``.
_CANONICAL_TO_LEAD_FIELD: Dict[str, str] = {
    "address":          "address",
    "notes":            "notes",         # message → notes/message twin
    "phone":            "phone",
    "email":            "email",
    "name":             "name",
    "first_name":       "first_name",
    "last_name":        "last_name",
    "company_name":     "company_name",
    "city":             "city",
    "state":            "state",
    "zip":              "zip",
    "service_interest": "service_interest",
}


def _is_empty(v: Any) -> bool:
    """Treat None / '' / '   ' / literal ``'Website Visitor'`` as
    empty so the sentinel doesn't block a real name from landing.
    """
    if v is None:
        return True
    if isinstance(v, str):
        return v.strip() == "" or v.strip() == "Website Visitor"
    return False


async def _load_form_schema(db, form_id: Optional[str],
                              form_slug: Optional[str]) -> List[Dict[str, Any]]:
    """Best-effort schema lookup.  Old submissions do not snapshot
    the schema on the submission doc — we fetch the CURRENT form
    schema by id / slug.  A note in the ship memo acknowledges the
    (small) risk of author-side drift between submit time and
    backfill time."""
    q = None
    if form_id:
        q = {"id": form_id}
    elif form_slug:
        q = {"slug": form_slug}
    if not q:
        return []
    form = await db.marketing_forms.find_one(q, {"_id": 0, "fields": 1})
    if not form:
        return []
    return form.get("fields") or []


async def backfill_leads_label_resolution(
    db,
    *,
    tenant_id: str,
    actor: Dict[str, Any],
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Idempotent backfill.  Returns a summary dict."""
    run_id = str(uuid.uuid4())
    counters: Dict[str, Any] = {
        "run_id": run_id,
        "tenant_id": tenant_id,
        "leads_scanned": 0,
        "leads_updated": 0,
        "leads_skipped_no_submission": 0,
        "leads_skipped_already_populated": 0,
        "fields_written": {},
        "dry_run": dry_run,
    }

    # We scan leads with a resolvable ``submission_id`` — the widget
    # path (``source == "website_form"``) never stores raw payloads
    # under ``form_submissions``, so those rows are correctly
    # skipped without spurious "no submission" churn.
    cursor = db.leads.find({
        "tenant_id": tenant_id,
        "submission_id": {"$exists": True, "$ne": None},
    })
    async for lead in cursor:
        counters["leads_scanned"] += 1
        sub_id = lead.get("submission_id")
        submission = await db.form_submissions.find_one({"id": sub_id})
        if not submission:
            counters["leads_skipped_no_submission"] += 1
            continue

        raw_vals = submission.get("data") or submission.get("answers") or {}
        schema = await _load_form_schema(
            db,
            submission.get("form_id"),
            submission.get("form_slug"),
        )
        extracted = extract_contact_fields_with_schema(raw_vals, schema)

        updates: Dict[str, Any] = {}
        for canonical, target in _CANONICAL_TO_LEAD_FIELD.items():
            new_val = None
            if canonical == "notes":
                new_val = extracted.get("message")
            else:
                new_val = extracted.get(canonical)
            if not new_val:
                continue
            if not _is_empty(lead.get(target)):
                continue  # do not overwrite a hand-corrected value
            updates[target] = new_val
            # Mirror ``address`` → ``service_address`` for
            # backwards-compat with the geocoder + admin UI which
            # read either name.
            if target == "address" and _is_empty(lead.get("service_address")):
                updates["service_address"] = new_val
            # Mirror ``notes`` → ``message`` similarly.
            if target == "notes" and _is_empty(lead.get("message")):
                updates["message"] = new_val

        if not updates:
            counters["leads_skipped_already_populated"] += 1
            continue

        counters["leads_updated"] += 1
        for k in updates:
            counters["fields_written"][k] = counters["fields_written"].get(k, 0) + 1

        if dry_run:
            continue

        updates["updated_at"] = now_iso()
        await db.leads.update_one({"id": lead["id"]}, {"$set": updates})
        try:
            await db.audit_logs.insert_one({
                "id": str(uuid.uuid4()),
                "tenant_id": tenant_id,
                "actor_user_id": (actor or {}).get("id"),
                "action": "leads.backfill.label_resolution_v1",
                "target_type": "lead",
                "target_id": lead["id"],
                "run_id": run_id,
                "backfilled_from_submission_id": sub_id,
                "fields_written": sorted(updates.keys()),
                "created_at": now_iso(),
            })
        except Exception as _exc:  # noqa: BLE001
            logger.warning("[leads-backfill-l2] audit log failed: %s", _exc)

    return counters
