"""Feb-2026 · P0 hotfix — Write-side tech-assignment denormalization.

Shared helper that resolves the ``technician_name`` + ``technician_avatar``
denorm-cache pair a create/update-job flow needs to stamp onto the job
doc so downstream reads (Job Details, list rows, mobile card, etc.)
render the assignee correctly.

The problem it solves
─────────────────────
``GET /api/technicians`` returns a UNION of two collections:

  1. Real ``db.technicians`` docs (id shape = ``technicians._id``)
  2. Synthesized rows from ``db.users`` (id shape = ``user.technician_id``
     if present, else ``user.id``) — these represent real team members
     added through the roster UI who never got a matching
     ``db.technicians`` row.

The frontend picker binds ``<option value={t.id}>`` and POSTs that value
back as ``technician_id``. Historically the write handlers did a
single-collection lookup:

    tech = await db.technicians.find_one(
        {"id": body.technician_id, ...}, {"_id": 0},
    )
    tech_name = tech["name"] if tech else None    # ← None for synth

For every synthesized tech (every real team member added via the roster
UI!) the lookup missed, the denorm was stamped ``None``, and the Job
Details page rendered "Unassigned" even though ``technician_id`` was
correctly persisted on the doc.

This helper delegates to the same 4-rung cascade the read side already
uses (``services.service_report_view.resolve_technician_names``), plus
an avatar lookup that covers both the real-tech-doc case (``avatar``
on ``db.technicians``) and the synth-from-users case (empty string,
since ``db.users`` doesn't carry the field yet).
"""
from typing import Any, Dict, Optional


async def resolve_tech_write_denorms(db, tenant_id: str,
                                       tech_id: Optional[str]) -> Dict[str, Any]:
    """Resolve the write-side denorm cache for a job's tech assignment.

    Returns ``{"name": Optional[str], "avatar": str}``. Never raises.

    Empty inputs (``None`` / ``""``) return the empty denorms — same
    shape as the ``no tech assigned`` case so callers can unconditionally
    stamp the result on the job doc.
    """
    empty = {"name": None, "avatar": ""}
    if not tech_id:
        return empty
    # Cascade name lookup — 4 rungs, handles both real-tech-doc and
    # synth-from-users shapes.
    from services.service_report_view import resolve_technician_names
    names = await resolve_technician_names(db, tenant_id, [tech_id])
    name = names.get(tech_id) or None

    # Avatar lookup — try the real-tech-doc first (matches the historical
    # behaviour of the write handler). Then fall back to the technicians
    # doc indexed by ``user_id`` for the case where the incoming
    # ``tech_id`` is a ``users.id`` shape but a linked technicians row
    # exists. Synth-only techs return an empty avatar (users doesn't
    # carry the field today).
    avatar = ""
    tdoc = await db.technicians.find_one(
        {"tenant_id": tenant_id, "id": tech_id},
        {"_id": 0, "avatar": 1},
    )
    if not tdoc:
        tdoc = await db.technicians.find_one(
            {"tenant_id": tenant_id, "user_id": tech_id},
            {"_id": 0, "avatar": 1},
        )
    if tdoc:
        avatar = tdoc.get("avatar") or ""
    return {"name": name, "avatar": avatar}
