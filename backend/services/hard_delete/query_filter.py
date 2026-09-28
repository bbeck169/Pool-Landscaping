"""HD-A · Shared read filter.

The one true way for backend code to filter out soft-deleted rows.
Guarantees a uniform ``deleted_at`` shape across every eligible
collection so a single helper suffices.

Historical drift: the pre-existing per-router filters use a mix of
``{"deleted_at": None}``, ``{"$or": [{"deleted_at": None},
{"deleted_at": {"$exists": False}}]}``, and (on ``files``)
``{"is_deleted": False}``. All three are semantically equivalent —
the helper collapses them to the ``$or`` form so callsites don't
diverge again.

Usage
-----
::

    from services.hard_delete.query_filter import apply_soft_delete_filter

    q = apply_soft_delete_filter(
        {"tenant_id": tenant["id"]},
        collection="customers",
    )
    async for row in db.customers.find(q):
        ...

Pass ``include_trashed=True`` to short-circuit — the query is
returned unchanged, which is the required shape for the Trash view
endpoint that intentionally wants soft-deleted rows.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from .registry import ELIGIBLE_COLLECTIONS


# The canonical "not-deleted" predicate — either ``deleted_at`` is
# NULL or the field is absent from the document. Both shapes exist
# in the wild (older documents predate the field entirely).
_NOT_DELETED_OR: list = [
    {"deleted_at": None},
    {"deleted_at": {"$exists": False}},
]

# Files also carry an ``is_deleted`` boolean (see
# routers/files.py) — treat both shapes as "soft-deleted".
_NOT_DELETED_OR_WITH_IS_DELETED: list = _NOT_DELETED_OR + [{"is_deleted": False}]


def apply_soft_delete_filter(
    query: Optional[Dict[str, Any]] = None,
    *,
    collection: Optional[str] = None,
    include_trashed: bool = False,
) -> Dict[str, Any]:
    """Merge a soft-delete guard into ``query``.

    Args:
        query: The Mongo query to augment. ``None`` is treated as
            an empty query. NEVER mutated — a shallow copy is
            returned so callers can safely pass ``self._query``.
        collection: Optional collection name; when supplied and it
            equals ``"files"``, the ``is_deleted`` legacy field is
            also honoured. All other eligible collections use the
            ``deleted_at``-only predicate.
        include_trashed: When True, no guard is applied — the
            query passes through unchanged. This is the shape used
            by the Trash view endpoint.

    Returns:
        A new dict that layers the appropriate ``$and``/``$or``
        guards on top of ``query``. If ``query`` already carries an
        ``$and`` list, the guards are appended to it. Otherwise the
        guards are folded in flat.
    """
    q = dict(query or {})
    if include_trashed:
        return q

    if collection == "files":
        # Files use ``is_deleted`` in addition to ``deleted_at``;
        # treat any of the three not-deleted shapes as visible.
        guard: Dict[str, Any] = {"$or": list(_NOT_DELETED_OR_WITH_IS_DELETED)}
    else:
        guard = {"$or": list(_NOT_DELETED_OR)}

    # If the caller already carries an ``$or``, wrap both in ``$and``
    # so both predicates apply simultaneously. Mongo's default merge
    # semantics would silently drop one of them.
    if "$or" in q:
        existing_and = q.pop("$and", None) or []
        existing_or = q.pop("$or")
        q["$and"] = existing_and + [{"$or": existing_or}, guard]
        return q

    # No pre-existing $or — fold guard in flat (attach the $or key).
    q["$or"] = guard["$or"]
    return q


def only_trashed_filter(
    query: Optional[Dict[str, Any]] = None,
    *,
    collection: Optional[str] = None,
) -> Dict[str, Any]:
    """Return a query that matches ONLY soft-deleted rows.

    Used by the ``GET /trash`` list. The dual of
    ``apply_soft_delete_filter``.
    """
    q = dict(query or {})
    if collection == "files":
        # A row is "trashed" if either flag is set — the two legacy
        # paths are unified under one predicate.
        q["$or"] = [
            {"deleted_at": {"$ne": None, "$exists": True}},
            {"is_deleted": True},
        ]
        return q
    q["deleted_at"] = {"$ne": None, "$exists": True}
    return q


def is_eligible_collection(collection: str) -> bool:
    """Callsite audit helper — used by the coverage test to enumerate
    which collection queries the helper is expected to guard."""
    return collection in ELIGIBLE_COLLECTIONS
