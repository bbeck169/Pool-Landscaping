"""TD-search-technicians-bucket · Feb-2026 — shared technician roster helper.

Extracts the union + dedupe + inactive/deleted exclusion logic that was
previously inlined in ``routers.technicians.list_technicians`` so both the
roster endpoint and the ``/api/search`` technicians bucket resolve against
one source of truth.

The helper intentionally STOPS at the sorted + deduped set so the caller
owns post-fetch enrichment decisions:

  * ``/api/technicians`` applies display-color overlay + K65 ``active_jobs``
    aggregation on top of this result (preserves byte-identical response
    shape).
  * ``/api/search?entities=technicians`` skips enrichment entirely — search
    hits only need ``id / name / email / phone / role``.

Role allowlist (``ASSIGNABLE_ROLES``) is pinned here as the canonical
source. Admin / super_admin / manager are deliberately excluded —
field-assignability only. See history on
``routers/technicians.py:89-90`` for the pre-extraction call site.
"""
from __future__ import annotations

from typing import List, Set, Tuple

from config import db


# Field-assignable roles for the tenant's technician roster. Mirrors
# the previous inline list in ``list_technicians``. Admin / super_admin
# / manager are deliberately excluded — field-assignability only.
ASSIGNABLE_ROLES: List[str] = [
    "technician", "tech", "landscaper",
    "landscape_tech", "pool_tech", "tech_both",
]


async def fetch_tenant_technician_roster(
    tenant_id: str,
) -> Tuple[List[dict], Set[str]]:
    """Return the deduped (tech-row ∪ synth-from-users) roster for the tenant.

    Returns ``(docs, linked_user_ids)`` where ``docs`` is the sorted +
    deduped list of technician dicts (pre-enrichment) and
    ``linked_user_ids`` is the set of ``users.id`` values linked to a
    real ``db.technicians`` row (used by the caller for display-color
    + active-jobs fanout).

    The helper preserves the exact field set emitted by
    ``list_technicians`` prior to extraction so the regression test
    (``test_td_technicians_core_regression``) can assert byte-identical
    output on ``/api/technicians`` post-refactor.
    """
    # (a) Real technician rows for THIS tenant — soft-deleted stripped
    #     to match the Schedule / Dispatch / Workstream dropdown truth.
    tech_docs = await db.technicians.find(
        {"tenant_id": tenant_id,
         "$or": [{"deleted_at": None},
                 {"deleted_at": {"$exists": False}}]},
        {"_id": 0},
    ).sort("name", 1).to_list(1000)
    linked_user_ids: Set[str] = {t.get("user_id") for t in tech_docs
                                  if t.get("user_id")}

    # (b) Synth rows for field-assignable users without a matching
    #     tech row. Excludes migration-artifact ``@t.local`` emails,
    #     soft-deleted rows, and ``active=false`` rows.
    synth_docs: List[dict] = []
    async for u in db.users.find(
        {"tenant_id": tenant_id,
         "role": {"$in": ASSIGNABLE_ROLES},
         "email": {"$not": {"$regex": "@t\\.local$", "$options": "i"}},
         "$and": [
             {"$or": [{"deleted_at": None},
                        {"deleted_at": {"$exists": False}}]},
             {"$or": [{"active": {"$ne": False}},
                        {"active": {"$exists": False}}]},
         ]},
        {"_id": 0, "id": 1, "email": 1, "first_name": 1,
         "last_name": 1, "name": 1, "phone": 1, "role": 1,
         "display_color_hex": 1, "technician_id": 1},
    ):
        if u.get("id") in linked_user_ids:
            continue
        if u.get("technician_id") in {t.get("id") for t in tech_docs}:
            continue
        synth_docs.append({
            "id": u.get("technician_id") or u.get("id"),
            "user_id": u.get("id"),
            "name": (u.get("name")
                      or " ".join([u.get("first_name") or "",
                                    u.get("last_name") or ""]).strip()
                      or u.get("email") or "Unnamed"),
            "email": u.get("email"),
            "phone": u.get("phone"),
            "role": u.get("role"),
            "tenant_id": tenant_id,
            "display_color_hex": u.get("display_color_hex"),
            "synthesized_from_users": True,
        })

    # Exclude tech rows whose linked user was soft-deactivated via
    # the Roster Cleanup flow. ``db.technicians`` rows don't carry an
    # ``active`` field; we pull the flag from the linked user.
    inactive_user_ids: Set[str] = set()
    if linked_user_ids:
        async for u in db.users.find(
            {"id": {"$in": list(linked_user_ids)}, "active": False},
            {"_id": 0, "id": 1},
        ):
            inactive_user_ids.add(u["id"])
    tech_docs = [t for t in tech_docs
                  if t.get("user_id") not in inactive_user_ids]

    docs = tech_docs + synth_docs

    # Robust cross-shape dedupe — first row through wins. Real tech
    # rows come first so they take precedence over synth rows
    # (preserves ``display_color_hex`` + ``phone`` stamped on the
    # tech row).
    seen_uids: Set[str] = set()
    seen_emails: Set[str] = set()
    seen_names: Set[str] = set()
    deduped: List[dict] = []
    for d in docs:
        uid = d.get("user_id")
        did = d.get("id")
        email = (d.get("email") or "").strip().lower()
        name = (d.get("name") or "").strip().lower()
        if uid and (uid in seen_uids or uid in seen_emails):
            continue
        if did and did in seen_uids:
            continue
        if email and email in seen_emails:
            continue
        if name and name in seen_names:
            continue
        if uid:
            seen_uids.add(uid)
        if did:
            seen_uids.add(did)
        if email:
            seen_emails.add(email)
        if name:
            seen_names.add(name)
        deduped.append(d)

    # Sort: field-worker roles first, then alphabetical.
    def _sort_key(d: dict) -> tuple:
        r = (d.get("role") or "").lower()
        rank = 0 if r in {"technician", "tech", "landscaper",
                            "landscape_tech", "pool_tech", "tech_both"} else 1
        return (rank, (d.get("name") or "").lower())

    sorted_docs = sorted(deduped, key=_sort_key)
    return sorted_docs, linked_user_ids
