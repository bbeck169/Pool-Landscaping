"""TD-tech-record-sync-and-fleet-enrollment · Feb-2026
=====================================================

Three-pass CLI backfill that heals mobile technician sync and fleet
enrollment data gaps:

  Pass A — ``technicians`` row linkage repair.
           For each live user with ``role in {technician, tech}``
           that has no linked technicians row (neither
           ``users.technician_id`` points at a live tech, nor does
           a live tech row carry ``user_id == users.id``), insert a
           minimal technicians doc using the user's name / email /
           phone and link both sides:
             * technicians doc is created with ``user_id = u.id``;
             * users.technician_id is stamped with the new tech id.
           Also covers "half-linked" users where ``users.technician_id``
           points at a live tech but ``technicians.user_id`` is missing
           — stamps the missing reverse pointer only.
           Idempotent via a double find_one probe PLUS the
           per-row ``technician_backfill_v1_at`` breadcrumb.

  Pass B — Job re-point for the orphan user cohort fixed in Pass A.
           Finds ``jobs.technician_id`` rows that still hold a bare
           ``users.id`` (one of the orphans Pass A just linked) and
           swaps them for the new ``technicians.id``, preserving the
           original value in ``technician_id_td_tp1_before`` (a new
           breadcrumb — DOES NOT collide with K42's
           ``technician_id_k42_before``).  Only ``technician_id`` is
           rewritten; alias fields (``assigned_to``, ``tech_user_id``,
           ``assigned_technician_id``) are LEFT AS-IS exactly like
           K42 (see ``services/tech_id_resolver.py``).

  Pass C — ``fleet_membership`` enrollment.
           For every live user with ``role in {technician, tech}``
           NOT already carrying a ``fleet_membership`` row, insert
           ``{tenant_id, tech_user_id: user.id, in_fleet=true,
             enabled_by="backfill_v1",
             source="tech_record_sync_and_fleet_enrollment_v1"}``.
           ``in_fleet`` defaults to TRUE per operator spec — the
           operator wants pings accepted immediately so mobile FE
           fleet tracking starts on first login.  The unique index
           ``fleet_membership_unique`` on ``(tenant_id,
           tech_user_id)`` backstops the pre-insert probe.

Role scope
----------
Matches ``routers.fleet._TECH_ROLES`` (``{"technician", "tech"}``).

Soft-deleted / inactive users
-----------------------------
Users with ``deleted_at`` set OR ``is_active == False`` are SKIPPED
in ALL three passes — if an admin later reactivates one, re-run
this CLI to catch them up.

Flags
-----
``--dry-run``       (default) — no writes, no sentinel. Prints
                                counts for every pass.
``--report-only``             — Per-tenant / per-user summary
                                table on stdout. No writes.
``--apply``                   — Perform the writes + record a
                                sentinel in ``db._migrations``.
                                Idempotent across re-runs.
``--tenant <id>``             — Restrict to one tenant.
``--force``                   — Bypass the sentinel short-circuit
                                on ``--apply``.
``--passes <A|B|C|AB|BC|ABC>`` — Restrict which passes run.
                                 Default ``ABC`` (all three).

Boot wiring
-----------
Deliberately NOT boot-wired.  Operator-triggered per the
TD-tech-record-sync-and-fleet-enrollment brief.  Mobile FE
behaviour changes AFTER apply (409 technician_not_linked gate
in services/mobile_tech_linkage.py starts passing for the
backfilled users).

Usage
-----
::

    cd /app/backend
    # 1. Dry-run — print aggregate counts across every pass.
    python -m migrations.tech_record_sync_and_fleet_enrollment_v1 --dry-run

    # 2. Report-only — per-tenant summary table.
    python -m migrations.tech_record_sync_and_fleet_enrollment_v1 --report-only

    # 3. Scoped apply — single tenant.
    python -m migrations.tech_record_sync_and_fleet_enrollment_v1 \\
        --apply --tenant <tenant_id>

    # 4. Full apply — every tenant.
    python -m migrations.tech_record_sync_and_fleet_enrollment_v1 --apply

    # 5. Pass B only (operator wants to re-check Pass A before B).
    python -m migrations.tech_record_sync_and_fleet_enrollment_v1 \\
        --apply --passes B

Revert
------
To revert a bad apply::

    db._migrations.deleteOne({"key":
      "tech_record_sync_and_fleet_enrollment_v1"})
    # Pass A revert: delete technicians rows created by backfill:
    db.technicians.deleteMany(
      {"source": "tech_record_sync_and_fleet_enrollment_v1"})
    # Pass B revert: restore technician_id from the breadcrumb:
    db.jobs.find({"technician_id_td_tp1_before": {"$exists": true}})
      .forEach(j => db.jobs.updateOne({_id: j._id},
        {$set: {technician_id: j.technician_id_td_tp1_before},
         $unset: {technician_id_td_tp1_before: ""}}))
    # Pass C revert: delete fleet_membership rows the CLI created:
    db.fleet_membership.deleteMany(
      {"source": "tech_record_sync_and_fleet_enrollment_v1"})
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))

from config import db, logger  # noqa: E402

_SENTINEL_KEY = "tech_record_sync_and_fleet_enrollment_v1"
_SENTINEL_COLLECTION = "_migrations"
_BACKFILL_SOURCE = _SENTINEL_KEY
_JOB_BREADCRUMB_FIELD = "technician_id_td_tp1_before"

# Role scope — matches routers.fleet._TECH_ROLES.
_TECH_ROLES = ["technician", "tech"]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id() -> str:
    # Local import so the module loads without the services graph.
    from utils import new_id as _nid  # noqa: PLC0415
    return _nid()


def _live_user_filter(tenant_id: str) -> Dict[str, Any]:
    """Live tech-role users for one tenant — soft-deleted + inactive
    stripped per operator spec (Q3 — skip entirely in all passes).

    The codebase has TWO fields that mark a user as inactive:
    ``is_active`` (used by admin_users.py / team.py write paths) and
    ``active`` (used by auth.py's deactivated-user gate at
    routers/auth.py:707).  A row is "live" only when BOTH read-paths
    would treat it as such — i.e. NEITHER field is explicitly False.
    """
    return {
        "tenant_id": tenant_id,
        "role": {"$in": _TECH_ROLES},
        "$and": [
            {"$or": [{"deleted_at": None},
                     {"deleted_at": {"$exists": False}}]},
            {"$or": [{"is_active": True},
                     {"is_active": {"$exists": False}},
                     {"is_active": None}]},
            {"$or": [{"active": True},
                     {"active": {"$exists": False}},
                     {"active": None}]},
        ],
    }


def _live_tech_filter() -> Dict[str, Any]:
    return {"$or": [{"deleted_at": None},
                    {"deleted_at": {"$exists": False}}]}


async def _load_tenant_ids(scoped: Optional[str]) -> List[str]:
    if scoped:
        return [scoped]
    out: List[str] = []
    async for t in db.tenants.find({}, {"_id": 0, "id": 1}):
        if t.get("id"):
            out.append(t["id"])
    return out


# ═══════════════════════════════════════════════════════════════════
# Pass A — technician row linkage repair
# ═══════════════════════════════════════════════════════════════════
async def _scan_pass_a_tenant(tenant_id: str) -> Dict[str, Any]:
    """Enumerate orphan + half-linked tech-role users in one tenant."""
    report: Dict[str, Any] = {
        "tenant_id": tenant_id,
        "orphans_to_create": [],       # need brand-new tech row
        "half_linked_to_backfill": [],  # tech row exists via user.technician_id but tech.user_id missing
    }
    async for u in db.users.find(
        _live_user_filter(tenant_id),
        {"_id": 0, "id": 1, "email": 1, "name": 1, "phone": 1,
         "role": 1, "technician_id": 1, "department": 1,
         "display_color_hex": 1},
    ):
        uid = u["id"]
        linked_tech_id = u.get("technician_id")
        resolved_tech = None
        if linked_tech_id:
            resolved_tech = await db.technicians.find_one(
                {"id": linked_tech_id, "tenant_id": tenant_id,
                 **_live_tech_filter()},
                {"_id": 0, "id": 1, "user_id": 1},
            )
        if resolved_tech:
            # Half-linked: user.technician_id → live tech, but tech.user_id missing or wrong.
            if resolved_tech.get("user_id") != uid:
                report["half_linked_to_backfill"].append({
                    "user_id": uid,
                    "tech_id": resolved_tech["id"],
                    "current_tech_user_id": resolved_tech.get("user_id"),
                    "email": u.get("email"),
                })
            continue
        # No forward link OR forward link stale — try reverse.
        reverse = await db.technicians.find_one(
            {"user_id": uid, "tenant_id": tenant_id,
             **_live_tech_filter()},
            {"_id": 0, "id": 1},
        )
        if reverse:
            # Reverse-linked but user.technician_id missing / stale.
            # Pass A stamps users.technician_id for symmetry.
            report["half_linked_to_backfill"].append({
                "user_id": uid,
                "tech_id": reverse["id"],
                "current_tech_user_id": uid,   # already matches
                "stamp_user_side_only": True,
                "email": u.get("email"),
            })
            continue
        # True orphan — needs a brand-new tech row.
        report["orphans_to_create"].append({
            "user_id": uid,
            "email": u.get("email") or "",
            "name": u.get("name") or (u.get("email") or "").split("@")[0] or uid,
            "phone": u.get("phone") or "",
            "role": u.get("role"),
            "department": u.get("department"),
            "display_color_hex": u.get("display_color_hex"),
        })
    return report


async def _apply_pass_a_tenant(report: Dict[str, Any]) -> Dict[str, int]:
    tenant_id = report["tenant_id"]
    now = _now_iso()
    created = 0
    backfilled = 0

    # Half-linked: back-stamp missing side.
    for entry in report["half_linked_to_backfill"]:
        uid = entry["user_id"]
        tid = entry["tech_id"]
        if entry.get("stamp_user_side_only"):
            # users.technician_id missing but technicians.user_id correct.
            res = await db.users.update_one(
                {"id": uid, "tenant_id": tenant_id,
                 "$or": [{"technician_id": None},
                         {"technician_id": {"$exists": False}}]},
                {"$set": {"technician_id": tid,
                          "technician_backfill_v1_at": now}},
            )
            if int(getattr(res, "modified_count", 0) or 0):
                backfilled += 1
            continue
        # technicians.user_id missing or mismatched — stamp it (and
        # also normalize users.technician_id in case of staleness).
        res_t = await db.technicians.update_one(
            {"id": tid, "tenant_id": tenant_id,
             "$or": [{"user_id": None},
                     {"user_id": {"$exists": False}},
                     {"user_id": {"$ne": uid}}]},
            {"$set": {"user_id": uid,
                      "technician_backfill_v1_at": now,
                      "linked_by": _BACKFILL_SOURCE,
                      "linked_at": now}},
        )
        res_u = await db.users.update_one(
            {"id": uid, "tenant_id": tenant_id,
             "$or": [{"technician_id": None},
                     {"technician_id": {"$exists": False}},
                     {"technician_id": {"$ne": tid}}]},
            {"$set": {"technician_id": tid,
                      "technician_backfill_v1_at": now}},
        )
        if (int(getattr(res_t, "modified_count", 0) or 0)
                or int(getattr(res_u, "modified_count", 0) or 0)):
            backfilled += 1

    # True orphans: insert a new tech row + stamp user.technician_id.
    for entry in report["orphans_to_create"]:
        uid = entry["user_id"]
        new_tech_id = _new_id()
        tech_doc = {
            "id": new_tech_id,
            "tenant_id": tenant_id,
            "user_id": uid,
            "name": entry["name"],
            "email": entry["email"],
            "phone": entry["phone"],
            "active": True,
            "department": entry.get("department"),
            "display_color_hex": entry.get("display_color_hex"),
            "created_at": now,
            "updated_at": now,
            "created_by": _BACKFILL_SOURCE,
            "linked_by": _BACKFILL_SOURCE,
            "linked_at": now,
            "source": _BACKFILL_SOURCE,
            "technician_backfill_v1_at": now,
        }
        try:
            await db.technicians.insert_one(tech_doc)
        except Exception as e:  # noqa: BLE001
            logger.warning(
                "[tech-record-sync-backfill] tech insert failed "
                "tenant=%s user=%s err=%r", tenant_id, uid, e,
            )
            continue
        # Stamp user side too (symmetric link per Q5).
        await db.users.update_one(
            {"id": uid, "tenant_id": tenant_id},
            {"$set": {"technician_id": new_tech_id,
                      "technician_backfill_v1_at": now}},
        )
        # Record the new mapping on the report so Pass B can use it
        # directly without re-querying.
        entry["new_tech_id"] = new_tech_id
        created += 1
    return {"created_tech_rows": created,
            "half_linked_backfilled": backfilled}


# ═══════════════════════════════════════════════════════════════════
# Pass B — re-point jobs keyed to bare user_id for the fixed cohort
# ═══════════════════════════════════════════════════════════════════
async def _scan_pass_b_tenant(
    tenant_id: str,
    orphan_cohort: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Count jobs keyed to any orphan ``user_id`` under ``technician_id``.

    ``orphan_cohort`` elements must carry ``user_id`` and ``new_tech_id``
    (produced in Pass A under ``--apply``, OR synthesized for dry-run
    reporting using the user's ``technician_id`` if already linked).
    """
    report: Dict[str, Any] = {
        "tenant_id": tenant_id,
        "candidate_jobs": [],
    }
    if not orphan_cohort:
        return report
    uid_to_new: Dict[str, str] = {
        e["user_id"]: e["new_tech_id"]
        for e in orphan_cohort if e.get("new_tech_id")
    }
    if not uid_to_new:
        return report
    cursor = db.jobs.find(
        {
            "tenant_id": tenant_id,
            "technician_id": {"$in": list(uid_to_new.keys())},
            # Belt-and-braces: skip rows K42 already re-pointed OR we
            # already touched in a prior run.
            _JOB_BREADCRUMB_FIELD: {"$exists": False},
            "technician_id_k42_before": {"$exists": False},
        },
        {"_id": 0, "id": 1, "technician_id": 1},
    )
    async for j in cursor:
        current = j.get("technician_id")
        new_tech = uid_to_new.get(current)
        if not new_tech or new_tech == current:
            continue
        report["candidate_jobs"].append({
            "job_id": j.get("id"),
            "from": current,
            "to": new_tech,
        })
    return report


async def _apply_pass_b_tenant(report: Dict[str, Any]) -> int:
    tenant_id = report["tenant_id"]
    now = _now_iso()
    moved = 0
    for row in report["candidate_jobs"]:
        res = await db.jobs.update_one(
            {
                "tenant_id": tenant_id,
                "id": row["job_id"],
                "technician_id": row["from"],
                _JOB_BREADCRUMB_FIELD: {"$exists": False},
            },
            {"$set": {
                "technician_id": row["to"],
                _JOB_BREADCRUMB_FIELD: row["from"],
                "technician_id_td_tp1_at": now,
            }},
        )
        if int(getattr(res, "modified_count", 0) or 0):
            moved += 1
    return moved


# ═══════════════════════════════════════════════════════════════════
# Pass C — fleet_membership enrollment
# ═══════════════════════════════════════════════════════════════════
async def _scan_pass_c_tenant(tenant_id: str) -> Dict[str, Any]:
    report: Dict[str, Any] = {
        "tenant_id": tenant_id,
        "to_enroll": [],
    }
    # Collect live tech-role user ids.
    user_ids: List[str] = []
    async for u in db.users.find(
        _live_user_filter(tenant_id),
        {"_id": 0, "id": 1, "email": 1},
    ):
        user_ids.append(u["id"])
    if not user_ids:
        return report
    existing: Set[str] = set()
    async for m in db.fleet_membership.find(
        {"tenant_id": tenant_id, "tech_user_id": {"$in": user_ids}},
        {"_id": 0, "tech_user_id": 1},
    ):
        existing.add(m["tech_user_id"])
    for uid in user_ids:
        if uid in existing:
            continue
        report["to_enroll"].append({"user_id": uid})
    return report


async def _apply_pass_c_tenant(report: Dict[str, Any]) -> int:
    tenant_id = report["tenant_id"]
    now = _now_iso()
    enrolled = 0
    for entry in report["to_enroll"]:
        uid = entry["user_id"]
        # Idempotency probe — the unique index is the backstop but
        # a pre-check avoids a flood of DuplicateKey warnings.
        existing = await db.fleet_membership.find_one(
            {"tenant_id": tenant_id, "tech_user_id": uid},
            {"_id": 0, "id": 1},
        )
        if existing:
            continue
        doc = {
            "id": _new_id(),
            "tenant_id": tenant_id,
            "tech_user_id": uid,
            "in_fleet": True,  # operator default (Q2 b)
            "notes": None,
            "enabled_by": _BACKFILL_SOURCE,
            "enabled_by_email": None,
            "enabled_at": now,
            "created_at": now,
            "source": _BACKFILL_SOURCE,
        }
        try:
            await db.fleet_membership.insert_one(doc)
            enrolled += 1
        except Exception as e:  # noqa: BLE001
            logger.warning(
                "[tech-record-sync-backfill] fleet enroll failed "
                "tenant=%s user=%s err=%r", tenant_id, uid, e,
            )
    return enrolled


# ═══════════════════════════════════════════════════════════════════
# Sentinel + driver
# ═══════════════════════════════════════════════════════════════════
async def _is_sentinel_clean() -> bool:
    doc = await db[_SENTINEL_COLLECTION].find_one({"key": _SENTINEL_KEY})
    if not doc or doc.get("mode") != "apply":
        return False
    stats = doc.get("stats") or {}
    # Clean when every pass has 0 remaining candidates after.
    return (int(stats.get("pass_a_remaining_after", 1)) == 0
            and int(stats.get("pass_b_remaining_after", 1)) == 0
            and int(stats.get("pass_c_remaining_after", 1)) == 0)


async def _write_sentinel(stats: Dict[str, Any], mode: str) -> None:
    doc = {
        "id": _SENTINEL_KEY,
        "key": _SENTINEL_KEY,
        "phase": "TD-tech-record-sync-and-fleet-enrollment",
        "mode": mode,
        "completed_at": _now_iso(),
        "stats": stats,
    }
    await db[_SENTINEL_COLLECTION].update_one(
        {"key": _SENTINEL_KEY},
        {"$set": doc},
        upsert=True,
    )


def _parse_passes(spec: str) -> Set[str]:
    """Parse ``'A'``/``'AB'``/``'ABC'``/``'BC'`` etc. into a set."""
    allowed = {"A", "B", "C"}
    out: Set[str] = set()
    for ch in (spec or "").upper():
        if ch in allowed:
            out.add(ch)
    if not out:
        raise ValueError(
            f"--passes must contain at least one of A/B/C "
            f"(got {spec!r})")
    return out


async def run(
    *,
    apply: bool = False,
    report_only: bool = False,
    tenant_id: Optional[str] = None,
    force: bool = False,
    passes: str = "ABC",
) -> Dict[str, Any]:
    # Loop-rebind shim for Motor's ``_io_loop`` guard (mirrors
    # paid_invoice_status_backfill_v1).
    try:
        from config import client as _client  # noqa: PLC0415
        _client._io_loop = asyncio.get_running_loop()
    except Exception:  # noqa: BLE001
        pass

    if report_only and apply:
        raise ValueError(
            "--report-only and --apply are mutually exclusive "
            "(report-only forbids writes).")

    passes_set = _parse_passes(passes)

    if (apply and not force and not tenant_id
            and "A" in passes_set
            and "B" in passes_set
            and "C" in passes_set
            and await _is_sentinel_clean()):
        return {"status": "skipped", "reason": "sentinel-clean"}

    tenant_ids = await _load_tenant_ids(tenant_id)
    all_reports: List[Dict[str, Any]] = []
    totals = {
        "tenants": len(tenant_ids),
        "pass_a_orphans": 0,
        "pass_a_half_linked": 0,
        "pass_a_created": 0,
        "pass_a_backfilled": 0,
        "pass_b_candidate_jobs": 0,
        "pass_b_moved": 0,
        "pass_c_to_enroll": 0,
        "pass_c_enrolled": 0,
    }

    for tid in tenant_ids:
        tenant_report: Dict[str, Any] = {"tenant_id": tid}
        pass_a_rep = None
        if "A" in passes_set:
            pass_a_rep = await _scan_pass_a_tenant(tid)
            tenant_report["pass_a"] = pass_a_rep
            totals["pass_a_orphans"] += len(pass_a_rep["orphans_to_create"])
            totals["pass_a_half_linked"] += len(pass_a_rep["half_linked_to_backfill"])
            if apply and (pass_a_rep["orphans_to_create"]
                          or pass_a_rep["half_linked_to_backfill"]):
                a_stats = await _apply_pass_a_tenant(pass_a_rep)
                tenant_report["pass_a_apply"] = a_stats
                totals["pass_a_created"] += a_stats["created_tech_rows"]
                totals["pass_a_backfilled"] += a_stats["half_linked_backfilled"]

        if "B" in passes_set:
            # Pass B operates on the cohort of newly-created tech rows
            # from Pass A.  For dry-run reporting (no apply) we still
            # want a count — synthesize new_tech_id from the user's
            # existing ``technician_id`` where present (half-linked
            # orphans already have one on the user side), else skip
            # the row (true orphans without --apply have no tech id
            # yet so there's nothing to re-point TO).
            cohort: List[Dict[str, Any]] = []
            if pass_a_rep is not None:
                for e in pass_a_rep["orphans_to_create"]:
                    nt = e.get("new_tech_id")
                    if nt:
                        cohort.append({"user_id": e["user_id"], "new_tech_id": nt})
                for h in pass_a_rep["half_linked_to_backfill"]:
                    cohort.append({"user_id": h["user_id"],
                                   "new_tech_id": h["tech_id"]})
            else:
                # Pass B invoked without Pass A — read current linkage
                # directly from users so operator can re-run B after a
                # clean A.
                async for u in db.users.find(
                    _live_user_filter(tid),
                    {"_id": 0, "id": 1, "technician_id": 1},
                ):
                    if u.get("technician_id"):
                        cohort.append({"user_id": u["id"],
                                       "new_tech_id": u["technician_id"]})
            pass_b_rep = await _scan_pass_b_tenant(tid, cohort)
            tenant_report["pass_b"] = pass_b_rep
            totals["pass_b_candidate_jobs"] += len(pass_b_rep["candidate_jobs"])
            if apply and pass_b_rep["candidate_jobs"]:
                moved = await _apply_pass_b_tenant(pass_b_rep)
                tenant_report["pass_b_moved"] = moved
                totals["pass_b_moved"] += moved

        if "C" in passes_set:
            pass_c_rep = await _scan_pass_c_tenant(tid)
            tenant_report["pass_c"] = pass_c_rep
            totals["pass_c_to_enroll"] += len(pass_c_rep["to_enroll"])
            if apply and pass_c_rep["to_enroll"]:
                enrolled = await _apply_pass_c_tenant(pass_c_rep)
                tenant_report["pass_c_enrolled"] = enrolled
                totals["pass_c_enrolled"] += enrolled

        all_reports.append(tenant_report)

    logger.info(
        "[tech-record-sync-backfill] apply=%s report_only=%s passes=%s "
        "tenants=%s totals=%s",
        apply, report_only, "".join(sorted(passes_set)),
        totals["tenants"], totals,
    )

    if apply:
        # Re-scan each tenant to confirm each pass is clean afterwards.
        pass_a_remaining = 0
        pass_b_remaining = 0
        pass_c_remaining = 0
        for tid in tenant_ids:
            if "A" in passes_set:
                a2 = await _scan_pass_a_tenant(tid)
                pass_a_remaining += len(a2["orphans_to_create"])
                pass_a_remaining += len(a2["half_linked_to_backfill"])
            if "C" in passes_set:
                c2 = await _scan_pass_c_tenant(tid)
                pass_c_remaining += len(c2["to_enroll"])
            # Pass B remaining requires a fresh cohort read mirroring
            # the apply branch.
            if "B" in passes_set:
                cohort2: List[Dict[str, Any]] = []
                async for u in db.users.find(
                    _live_user_filter(tid),
                    {"_id": 0, "id": 1, "technician_id": 1},
                ):
                    if u.get("technician_id"):
                        cohort2.append({"user_id": u["id"],
                                        "new_tech_id": u["technician_id"]})
                b2 = await _scan_pass_b_tenant(tid, cohort2)
                pass_b_remaining += len(b2["candidate_jobs"])
        totals["pass_a_remaining_after"] = pass_a_remaining
        totals["pass_b_remaining_after"] = pass_b_remaining
        totals["pass_c_remaining_after"] = pass_c_remaining
        totals["clean"] = (pass_a_remaining == 0 and pass_b_remaining == 0
                           and pass_c_remaining == 0)
        totals["passes_run"] = "".join(sorted(passes_set))
        await _write_sentinel(totals, "apply")

    status = (
        "report-only" if report_only
        else "applied" if apply
        else "dry-run"
    )
    return {
        "status": status,
        "passes_run": "".join(sorted(passes_set)),
        "stats": totals,
        "reports": all_reports,
    }


def _format_report_table(out: Dict[str, Any]) -> str:
    lines: List[str] = []
    lines.append("=" * 78)
    lines.append("TD-tech-record-sync-and-fleet-enrollment · report-only")
    lines.append("=" * 78)
    s = out["stats"]
    lines.append(f"tenants scanned:              {s['tenants']}")
    lines.append(f"passes run:                   {out['passes_run']}")
    lines.append("-" * 78)
    lines.append("Pass A — technicians linkage")
    lines.append(f"  orphans needing new tech:   {s['pass_a_orphans']}")
    lines.append(f"  half-linked back-stamps:    {s['pass_a_half_linked']}")
    lines.append("Pass B — jobs re-point")
    lines.append(f"  candidate jobs:             {s['pass_b_candidate_jobs']}")
    lines.append("Pass C — fleet_membership enrollment")
    lines.append(f"  to enroll:                  {s['pass_c_to_enroll']}")
    lines.append("-" * 78)
    for rep in out["reports"]:
        tid = rep["tenant_id"]
        a = rep.get("pass_a") or {}
        b = rep.get("pass_b") or {}
        c = rep.get("pass_c") or {}
        orphans = len(a.get("orphans_to_create") or [])
        halfs = len(a.get("half_linked_to_backfill") or [])
        jobs = len(b.get("candidate_jobs") or [])
        enroll = len(c.get("to_enroll") or [])
        if not (orphans or halfs or jobs or enroll):
            continue
        lines.append(
            f"[tenant={tid}]  orphans={orphans}  "
            f"half-linked={halfs}  jobs={jobs}  enroll={enroll}")
        for row in (a.get("orphans_to_create") or [])[:6]:
            lines.append(
                f"  orphan  user={row['user_id']}  email={row['email']}"
                f"  role={row.get('role')}")
        if len(a.get("orphans_to_create") or []) > 6:
            lines.append(
                f"  … +{len(a['orphans_to_create']) - 6} more orphan rows")
        for row in (b.get("candidate_jobs") or [])[:6]:
            lines.append(
                f"  job     id={row['job_id']}  "
                f"from={row['from'][:8]}…  to={row['to'][:8]}…")
        if len(b.get("candidate_jobs") or []) > 6:
            lines.append(
                f"  … +{len(b['candidate_jobs']) - 6} more job rows")
    lines.append("=" * 78)
    return "\n".join(lines)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description=(
            "Three-pass backfill for TD-tech-record-sync-and-fleet-"
            "enrollment: (A) create technicians rows for orphan "
            "tech-role users, (B) re-point jobs keyed to bare "
            "user_id, (C) enroll tech-role users in fleet_membership."
        ),
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--apply", action="store_true",
                        help="Perform writes (default: dry-run)")
    group.add_argument("--dry-run", action="store_true",
                        help="Explicit dry-run (default behaviour)")
    group.add_argument("--report-only", action="store_true",
                        help="Per-tenant summary table; no writes.")
    parser.add_argument("--tenant", default=None,
                        help="Restrict to a single tenant id")
    parser.add_argument("--force", action="store_true",
                        help=("Bypass the sentinel short-circuit "
                              "on --apply"))
    parser.add_argument("--passes", default="ABC",
                        help=("Restrict which passes run — any "
                              "combination of A/B/C (default ABC)"))
    ns = parser.parse_args()
    out = asyncio.run(run(
        apply=ns.apply,
        report_only=ns.report_only,
        tenant_id=ns.tenant,
        force=ns.force,
        passes=ns.passes,
    ))
    if ns.report_only:
        print(_format_report_table(out))
    else:
        print(json.dumps(out, indent=2, default=str))
