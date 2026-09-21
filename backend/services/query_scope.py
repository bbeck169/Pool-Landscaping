"""Phase P12 · Feb-2026 — Tenant-scoped Mongo filter builder.

Root-cause helper for the P10 audit's recurring "``$or``-clobber" idiom
(``q = {**q, **_nd()}``). ``not_deleted_filter()`` returns a filter with
its own top-level ``$or`` for soft-delete; when the caller has ALREADY
put a top-level ``$or`` on the filter (tech-lane, address-shape,
scheduled_start-vs-scheduled_date, etc.), the dict-spread merge silently
drops one of the two — usually the tech-lane, because ``_nd()`` is
merged last and its ``$or`` wins.

This helper is the recommended way to compose any Mongo filter that
needs tenant scoping + soft-delete + one or more ``$or`` fragments.
Every ``$or`` fragment lands under a separate ``$and`` entry, so no
merge is possible.

Usage:

    from services.query_scope import tenant_scoped_filter

    q = tenant_scoped_filter(
        tenant_id,
        {"$or": [
            {"technician_id": target_uid},
            {"technician_id": tech_id},
            {"assigned_technician_id": target_uid},
        ]},
        {"$or": [
            {"scheduled_start": {"$gte": day_start, "$lte": day_end}},
            {"scheduled_date": date_str},
        ]},
        status={"$nin": ["completed", "cancelled"]},
    )

    async for j in db.jobs.find(q, {"_id": 0, "photos.data": 0}):
        ...

Design notes:
  * Not typed with ``Query`` / ``Mongo`` protocols to keep the helper
    dependency-free and easy to unit-test.
  * ``or_clauses`` accepts either a bare disjunction list (``[{...},
    {...}]``) OR an already-wrapped ``{"$or": [...]}`` dict — the helper
    normalises both.
  * ``exact`` kwargs land at the top level (``tenant_id`` etc); they
    are never re-merged, so they cannot collide.
  * Soft-delete is pulled from ``utils.not_deleted_filter`` so any
    future change to the soft-delete shape (e.g. renaming ``deleted``
    → ``deleted_at``) automatically flows here.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List

from utils import not_deleted_filter as _nd


def tenant_scoped_filter(
    tenant_id: str,
    *or_clauses: Any,
    **exact: Any,
) -> Dict[str, Any]:
    """Build a Mongo filter that always tenant-scopes AND applies
    soft-delete without any ``$or`` being clobbered by dict-merge.

    :param tenant_id: The current tenant id (mandatory).
    :param or_clauses: Zero or more disjunctions. Each item may be:
      * a list of clauses (``[{...}, {...}]``) — treated as an ``$or``.
      * a dict already wrapped (``{"$or": [...]}``) — unwrapped and
        re-wrapped verbatim.
      * ``None`` or an empty container — silently skipped.
    :param exact: Optional exact-match top-level kwargs (e.g.
      ``status={"$nin": [...]}``, ``scheduled_date="2026-11-11"``).
      These land directly under the top-level dict.
    :return: The composed Mongo filter dict.

    Shape:

        {
          "tenant_id": <tenant_id>,
          <exact kwargs at top level>,
          "$and": [
            {"$or": [<or_clauses[0]>]},
            {"$or": [<or_clauses[1]>]},
            ...
            <soft-delete fragment from _nd()>,
          ],
        }

    Rationale for ``$and``-wrapping every disjunction:
      * Any two ``$or`` at the top level would collide via dict-spread.
      * Nesting each under its own ``$and`` entry preserves the query
        planner's ability to reorder / index-hint them individually.
      * ``_nd()`` returns ``{"$or": [...]}`` too — treated identically.
    """
    if not tenant_id:
        raise ValueError("tenant_scoped_filter requires a non-empty tenant_id")

    base: Dict[str, Any] = {"tenant_id": tenant_id}
    # ``exact`` kwargs may include keys that themselves happen to be
    # ``$and`` / ``$or`` — that's a caller-side mistake we surface via
    # a clear error instead of silently blessing it (would just re-
    # introduce the merge-clobber bug this helper exists to prevent).
    for k in ("$and", "$or", "tenant_id"):
        if k in exact:
            raise ValueError(
                f"tenant_scoped_filter: {k!r} is reserved — pass "
                f"disjunctions via positional or_clauses"
            )
    base.update(exact)

    and_bag: List[Dict[str, Any]] = []
    for frag in or_clauses:
        if frag is None:
            continue
        # Wrapped shape: ``{"$or": [...]}`` — pass through if non-empty.
        if isinstance(frag, dict) and "$or" in frag:
            inner = frag.get("$or") or []
            if inner:
                and_bag.append({"$or": list(inner)})
            continue
        # Bare list shape: ``[{...}, {...}]``.
        if isinstance(frag, (list, tuple)) and len(frag) > 0:
            and_bag.append({"$or": list(frag)})
            continue
        # Anything else — a caller error worth surfacing loudly.
        raise TypeError(
            "tenant_scoped_filter: or_clauses must be a list of clauses "
            f"or a {{'$or': [...]}} dict, got {type(frag).__name__}"
        )

    # Always append soft-delete last so it stays in the same ``$and``
    # bag as every other disjunction — no dict-spread merge anywhere.
    and_bag.append(_nd())

    base["$and"] = and_bag
    return base


__all__ = ["tenant_scoped_filter"]
