"""Phase K42 · Feb-2026 — Tech-ID normalization service.

Symptom: filtering the Schedule by a technician returns zero jobs even
though the tech is active and has jobs assigned.  Root cause: the
codebase has TWO id spaces for the same person:

  ─────────────────────────────────────────────────────────────
   collection    field        role in the domain model
  ─────────────────────────────────────────────────────────────
   users         id           auth-linked account
   users         technician_id → technicians.id (link)
   technicians   id           legacy tech-employee record
   jobs          technician_id target of assignment
   jobs          assigned_to   duplicate of technician_id (alias)
   jobs          tech_user_id  duplicate of technician_id (alias)
   jobs          assigned_technician_id duplicate (alias)
   crews         tech_ids      list of technicians.id
  ─────────────────────────────────────────────────────────────

Historically some write paths wrote ``jobs.technician_id = users.id``
while others wrote ``jobs.technician_id = technicians.id``.  Any read
that matched exact-equals against one id variant would MISS jobs
written under the other.

Authoritative field: **``technicians.id``** — this is what
``scope_jobs_query`` reads from the JWT (``user["technician_id"]``),
what ``crews.tech_ids`` uses, and what ~75% of jobs already use.

This module exposes a single primitive
:func:`resolve_tech_id_variants` which, given any id (either flavour),
returns the ORDered pair ``(technicians_id, users_id)`` plus a de-
duped ``all`` list suitable for ``$in`` queries.  Callers use ``all``
to build defensive ``$or`` filters that match jobs written under
either variant.  The K42 migration then converges the write side so
new jobs consistently land under ``technicians.id`` going forward.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from config import db

logger = logging.getLogger("tech_id_resolver")

# Set of user roles considered "field-assignable" — mirrors
# ``routers.technicians.ASSIGNABLE_ROLES``.  Kept as a local constant
# so this module has no import edge on ``routers.*``.
_ASSIGNABLE_ROLES = frozenset({
    "technician", "tech", "landscaper",
    "landscape_tech", "pool_tech", "tech_both",
})

# Every field on ``db.jobs`` that has ever stored the assignee.  The
# migration + defensive read-side both consult all of these so an
# operator who filters by "Ethan" catches jobs regardless of which
# write path created them.
JOB_TECH_FIELDS: Tuple[str, ...] = (
    "technician_id",
    "assigned_technician_id",
    "assigned_to",
    "tech_user_id",
)


@dataclass
class TechIdVariants:
    """Result of resolving one tech-ID lookup."""
    input_id: str
    tenant_id: Optional[str]
    technicians_id: Optional[str] = None
    users_id: Optional[str] = None
    name: Optional[str] = None
    source: str = "unresolved"  # "technicians" | "users" | "unresolved"
    all_ids: List[str] = field(default_factory=list)

    @property
    def resolved(self) -> bool:
        return self.source != "unresolved"


async def resolve_tech_id_variants(
    tech_id: str,
    tenant_id: Optional[str] = None,
) -> TechIdVariants:
    """Resolve ``tech_id`` (either flavour) to both variants.

    ``tenant_id`` is optional — if provided we constrain the lookup to
    the same tenant so a stale token from a different workspace cannot
    resolve to another workspace's ids.  The scope_jobs_query call site
    always passes ``tenant["id"]``; ad-hoc test callers can omit it.
    """
    out = TechIdVariants(input_id=tech_id, tenant_id=tenant_id)
    if not tech_id:
        return out

    # 1) technicians hit first (authoritative)
    tech_q: Dict[str, Any] = {"id": tech_id}
    if tenant_id:
        tech_q["tenant_id"] = tenant_id
    trow = await db.technicians.find_one(
        tech_q, {"_id": 0, "id": 1, "user_id": 1, "name": 1},
    )
    if trow:
        out.technicians_id = trow["id"]
        out.users_id = trow.get("user_id")
        out.name = trow.get("name")
        out.source = "technicians"
    else:
        # 2) users hit — resolve to linked technicians.id
        user_q: Dict[str, Any] = {"id": tech_id,
                                    "role": {"$in": list(_ASSIGNABLE_ROLES)}}
        if tenant_id:
            user_q["tenant_id"] = tenant_id
        urow = await db.users.find_one(
            user_q, {"_id": 0, "id": 1, "name": 1, "email": 1,
                      "technician_id": 1},
        )
        if urow:
            out.users_id = urow["id"]
            out.technicians_id = urow.get("technician_id")
            out.name = urow.get("name") or urow.get("email")
            out.source = "users"

    # If we resolved via technicians and the row had a user_id but
    # that user was soft-deleted / doesn't exist, still emit users_id
    # because a legacy job may have used it verbatim.
    seen: Set[str] = set()
    for cand in (out.technicians_id, out.users_id, tech_id):
        if cand and cand not in seen:
            seen.add(cand)
            out.all_ids.append(cand)
    return out


def build_tech_field_or_clause(
    variants: Sequence[str],
) -> Dict[str, Any]:
    """Build the ``$or`` clause that catches every job pointing at any
    of ``variants`` via any of :data:`JOB_TECH_FIELDS`.  Result shape::

        {"$or": [{"technician_id": {"$in": [a, b]}},
                  {"assigned_technician_id": {"$in": [a, b]}},
                  ...] }

    Callers merge this with the rest of their find() filter.
    """
    id_list = [v for v in variants if v]
    if not id_list:
        return {}
    return {"$or": [
        {f: {"$in": id_list}} for f in JOB_TECH_FIELDS
    ]}


async def resolve_and_build_filter(
    tech_id: str, tenant_id: Optional[str] = None,
) -> Tuple[TechIdVariants, Dict[str, Any]]:
    """Convenience wrapper — one call for scope_jobs_query."""
    v = await resolve_tech_id_variants(tech_id, tenant_id=tenant_id)
    return v, build_tech_field_or_clause(v.all_ids)


__all__ = [
    "JOB_TECH_FIELDS",
    "TechIdVariants",
    "build_tech_field_or_clause",
    "resolve_and_build_filter",
    "resolve_tech_id_variants",
]
