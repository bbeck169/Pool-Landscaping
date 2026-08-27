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


async def bulk_enrich_technician_names(
    db,
    tenant_id: str,
    docs: list,
    *,
    out_field: str = "technician_name",
) -> None:
    """Read-side, response-only bulk enrichment for a list of job docs.

    Mirrors the pattern already used in ``routers/workstream.py``:
      1. Union the 4-shape tech-id fields via ``effective_tid``.
      2. One batched call to ``resolve_technician_names`` (the same
         4-rung cascade the write helper uses).
      3. Precedence per doc: **cascade → stored → ""**. The cascade
         wins because the write helper started stamping the correct
         name only after Feb-2026; older jobs carry ``None`` /
         ``"Unassigned"`` on the stored field and the frontend renders
         empty strings as "Unassigned".

    Mutates ``docs`` in place — pass raw Mongo dicts or projected rows.
    Never mutates the DB (this is a response-shape helper, not a
    backfill). Never raises. Empty inputs no-op.

    Callers still need ``effective_tid`` themselves if they want to
    surface a canonical ``technician_id`` alongside the name (see the
    workstream aggregator for the reference wiring).
    """
    if not docs:
        return
    from services.job_assignee import effective_tid
    from services.service_report_view import resolve_technician_names

    tids = list({t for t in (effective_tid(d) for d in docs) if t})
    if not tids:
        # No candidates → still normalise the field type to "" (never
        # ``None``) so the frontend renders "Unassigned" via the empty
        # string, not a null-vs-empty spread across rows.
        for d in docs:
            if not d.get(out_field):
                d[out_field] = ""
        return
    name_map = await resolve_technician_names(db, tenant_id, tids)
    for d in docs:
        tid = effective_tid(d)
        cascaded = name_map.get(tid) if tid else None
        # Cascade first, then stored (may be stale), then "".
        d[out_field] = cascaded or d.get(out_field) or ""



async def bulk_enrich_technicians(
    db: Any,
    tenant_id: str,
    docs: list,
) -> None:
    """Feb 2026 · Rich variant — stamps BOTH ``technician_name`` +
    ``technician_active`` on every doc.

    Resolver-first (self-healing at read time before the boot
    backfill lands), then falls back to the stored value, then to
    the raw TID string per the resolver-cascade contract (never
    crashes).

    Mutates ``docs`` in place. Never touches the DB.
    """
    if not docs:
        return
    from services.job_assignee import effective_tid
    from services.service_report_view import resolve_technicians

    tids = list({t for t in (effective_tid(d) for d in docs) if t})
    if not tids:
        for d in docs:
            if not d.get("technician_name"):
                d["technician_name"] = ""
            d.setdefault("technician_active", True)
        return
    tmap = await resolve_technicians(db, tenant_id, tids)
    for d in docs:
        tid = effective_tid(d)
        info = tmap.get(tid) if tid else None
        if info:
            # Resolver wins over the stored value — self-heal at
            # read time so stale ``technician_name`` never leaks.
            d["technician_name"] = info["name"]
            d["technician_active"] = info["active"]
        else:
            # Neither resolver nor stored have a value → fall back
            # to the raw TID so downstream renderers still get
            # something identifying, per the resolver-cascade
            # spec ("Fall back to the string ID itself if nothing
            # matches — never crash").
            d["technician_name"] = d.get("technician_name") or tid or ""
            d.setdefault("technician_active", True)
