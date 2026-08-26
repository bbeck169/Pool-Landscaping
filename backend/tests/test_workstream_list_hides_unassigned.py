"""Feb-2026 · P0 · Bulk read-time technician-name enrichment.

Covers ``services.tech_assignment.bulk_enrich_technician_names`` and its
consumers on the list surfaces (``/api/workstream/jobs`` — the P0 case
in the tester's screenshot — and ``/api/jobs`` — the adjacent list that
previously read the stored ``technician_name`` verbatim).

Historical drift the helper repairs:
  * ``technician_id`` stamped in ``users.id`` shape (synth-from-users),
    stored ``technician_name`` == ``None``.
  * ``technician_id`` stamped in ``technicians.id`` shape but the
    write path missed the denorm.
  * Assignment lives under ``assigned_to`` / ``assigned_technician_id``
    / ``tech_user_id`` and ``technician_id`` itself is ``None`` (the
    4-shape ``effective_tid`` union still resolves).

Tenant scoping: cross-tenant lookups must return an empty name so a
tenant A caller never leaks a tenant B tech's display name.
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict, List

import pytest

from services.tech_assignment import bulk_enrich_technician_names


def _run(coro):
    return asyncio.run(coro)


class _AsyncCursor:
    def __init__(self, rows: List[Dict[str, Any]]):
        self._rows = list(rows)

    def __aiter__(self):
        self._i = 0
        return self

    async def __anext__(self):
        if self._i >= len(self._rows):
            raise StopAsyncIteration
        row = self._rows[self._i]
        self._i += 1
        return row


class _Collection:
    """Tiny Motor-shaped stub — only ``.find(query, projection)`` is used
    by ``resolve_technician_names``. The returned cursor is async-iterable
    and honours ``tenant_id`` scoping via a filter callback so tests can
    seed multi-tenant rows in a single fixture."""

    def __init__(self, rows: List[Dict[str, Any]]):
        self.rows = list(rows)

    def find(self, query: dict, _projection: dict = None):
        # Support only the shapes ``resolve_technician_names`` uses:
        #   {"tenant_id": X, "id": {"$in": [...]}}
        #   {"tenant_id": X, "user_id": {"$in": [...]}}
        #   {"tenant_id": X, "id": {"$in": [...]}, "role": {"$in": [...]}}
        def _matches(row):
            for k, v in query.items():
                rv = row.get(k)
                if isinstance(v, dict) and "$in" in v:
                    if rv not in v["$in"]:
                        return False
                else:
                    if rv != v:
                        return False
            return True
        return _AsyncCursor([r for r in self.rows if _matches(r)])


class _DB:
    def __init__(self, technicians: List[dict], users: List[dict]):
        self.technicians = _Collection(technicians)
        self.users = _Collection(users)


# ═══════════════════════════════════════════════════════════════════
# 1 · Synth-from-users shape resolves via the 4-rung cascade.
# ═══════════════════════════════════════════════════════════════════
def test_bulk_enrich_resolves_synth_from_users_shape():
    """Job has ``technician_id = <user.id>``, stored name is None
    (historical Feb-2026 drift). Cascade must resolve the user's
    display name via rung 3 (users.id + role in allowlist)."""
    db = _DB(
        technicians=[],  # No matching technicians row → forces rung 3.
        users=[
            {"tenant_id": "t1", "id": "u_synth",
             "role": "technician", "name": "Terry Gray"},
        ],
    )
    docs = [
        {"id": "j1", "technician_id": "u_synth", "technician_name": None},
    ]
    _run(bulk_enrich_technician_names(db, "t1", docs))
    assert docs[0]["technician_name"] == "Terry Gray"


# ═══════════════════════════════════════════════════════════════════
# 2 · Real-tech-doc shape still resolves (rung 1).
# ═══════════════════════════════════════════════════════════════════
def test_bulk_enrich_resolves_real_tech_doc_shape():
    """Job has ``technician_id = <technicians.id>`` (canonical shape)
    and stored name is stale/absent. Cascade rung 1 must hit."""
    db = _DB(
        technicians=[
            {"tenant_id": "t1", "id": "tech_1",
             "user_id": "u_link", "name": "Marshall Cuoco"},
        ],
        users=[],
    )
    docs = [
        {"id": "j2", "technician_id": "tech_1", "technician_name": None},
    ]
    _run(bulk_enrich_technician_names(db, "t1", docs))
    assert docs[0]["technician_name"] == "Marshall Cuoco"


# ═══════════════════════════════════════════════════════════════════
# 3 · Legitimately unassigned rows normalise to "" (never null).
# ═══════════════════════════════════════════════════════════════════
def test_bulk_enrich_normalises_truly_unassigned_to_empty_string():
    """Job with no assignment across any of the 4 shapes must land
    at ``""`` (not ``None``) so the frontend renders "Unassigned"
    uniformly."""
    db = _DB(technicians=[], users=[])
    docs = [
        {"id": "j3", "technician_id": None, "assigned_to": None,
         "assigned_technician_id": None, "tech_user_id": None,
         "technician_name": None},
    ]
    _run(bulk_enrich_technician_names(db, "t1", docs))
    assert docs[0]["technician_name"] == ""


# ═══════════════════════════════════════════════════════════════════
# 4 · Tenant scoping — a tenant A caller never leaks a tenant B name.
# ═══════════════════════════════════════════════════════════════════
def test_bulk_enrich_scopes_by_tenant_no_cross_tenant_leak():
    """Same ``technician_id`` value exists in tenant B (which happens
    when a demo pod reuses UUIDs) — tenant A's response must NOT
    surface tenant B's display name."""
    db = _DB(
        technicians=[
            # Tenant B has a row with the same id — MUST NOT leak.
            {"tenant_id": "tB", "id": "shared_id", "name": "TENANT-B-LEAK"},
        ],
        users=[
            {"tenant_id": "tA", "id": "shared_id",
             "role": "technician", "name": "Terry Gray"},
        ],
    )
    docs = [
        {"id": "j4", "technician_id": "shared_id", "technician_name": None},
    ]
    _run(bulk_enrich_technician_names(db, "tA", docs))
    assert docs[0]["technician_name"] == "Terry Gray"
    assert "TENANT-B-LEAK" not in docs[0]["technician_name"]


# ═══════════════════════════════════════════════════════════════════
# 5 · Effective-tid union — assignment under any of the 4 shapes
#     still resolves.
# ═══════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("shape_field", [
    "technician_id", "assigned_to", "assigned_technician_id", "tech_user_id",
])
def test_bulk_enrich_reads_all_four_tid_shapes(shape_field):
    """The 4-shape ``effective_tid`` union is required — historical
    write drift lands the id under any of these fields."""
    db = _DB(
        technicians=[],
        users=[
            {"tenant_id": "t1", "id": "u_1",
             "role": "technician", "name": "Diane Lloyd"},
        ],
    )
    docs = [
        {"id": f"j_{shape_field}", shape_field: "u_1",
         "technician_name": None},
    ]
    _run(bulk_enrich_technician_names(db, "t1", docs))
    assert docs[0]["technician_name"] == "Diane Lloyd", (shape_field, docs[0])


# ═══════════════════════════════════════════════════════════════════
# 6 · Response-only — DB is never touched.
# ═══════════════════════════════════════════════════════════════════
def test_bulk_enrich_never_writes_to_db():
    """The helper mutates the in-memory doc list only. No DB writes,
    ever. We exercise this by giving the stub NO update / insert
    methods — any attempt would raise AttributeError."""
    class _NoWriteCollection(_Collection):
        # Deliberately omit update_one / insert_one / update_many.
        # Any write attempt would ``AttributeError`` immediately.
        pass

    class _NoWriteDB:
        def __init__(self):
            self.technicians = _NoWriteCollection([])
            self.users = _NoWriteCollection([
                {"tenant_id": "t1", "id": "u_x",
                 "role": "technician", "name": "Laurie Garcia"},
            ])

    docs = [
        {"id": "j6", "technician_id": "u_x", "technician_name": None},
    ]
    _run(bulk_enrich_technician_names(_NoWriteDB(), "t1", docs))
    assert docs[0]["technician_name"] == "Laurie Garcia"


# ═══════════════════════════════════════════════════════════════════
# 7 · Cascade takes precedence over stored (stale) value.
# ═══════════════════════════════════════════════════════════════════
def test_bulk_enrich_cascade_overrides_stale_stored_name():
    """A job's stored ``technician_name`` may be stale (tech was
    renamed after the job was stamped). The cascade wins so the
    UI always sees the live name."""
    db = _DB(
        technicians=[],
        users=[
            {"tenant_id": "t1", "id": "u_r",
             "role": "technician", "name": "Benjamin Enriquez"},
        ],
    )
    docs = [
        {"id": "j7", "technician_id": "u_r",
         "technician_name": "Old Name (stale)"},
    ]
    _run(bulk_enrich_technician_names(db, "t1", docs))
    assert docs[0]["technician_name"] == "Benjamin Enriquez"


# ═══════════════════════════════════════════════════════════════════
# 8 · Batch efficiency — one query batch per collection, not N+1.
# ═══════════════════════════════════════════════════════════════════
def test_bulk_enrich_batches_queries_no_n_plus_1():
    """Given N docs across 3 distinct tech ids, the helper must
    issue at most a small constant number of DB queries — no
    per-doc lookup."""
    call_count = {"technicians": 0, "users": 0}

    class _CountingCollection(_Collection):
        def __init__(self, rows, kind):
            super().__init__(rows)
            self._kind = kind
        def find(self, q, p=None):
            call_count[self._kind] += 1
            return super().find(q, p)

    class _CountingDB:
        def __init__(self):
            self.technicians = _CountingCollection([], "technicians")
            self.users = _CountingCollection([
                {"tenant_id": "t1", "id": "u_a",
                 "role": "technician", "name": "Alpha"},
                {"tenant_id": "t1", "id": "u_b",
                 "role": "technician", "name": "Beta"},
                {"tenant_id": "t1", "id": "u_c",
                 "role": "technician", "name": "Gamma"},
            ], "users")

    # 20 docs sharing 3 distinct tech ids.
    docs = [
        {"id": f"j{i}", "technician_id": ["u_a", "u_b", "u_c"][i % 3],
         "technician_name": None}
        for i in range(20)
    ]
    _run(bulk_enrich_technician_names(_CountingDB(), "t1", docs))
    # cascade calls each collection at most once per rung → constant.
    assert call_count["technicians"] <= 2, call_count
    assert call_count["users"] <= 2, call_count
    # Every doc enriched correctly.
    expected = {"Alpha", "Beta", "Gamma"}
    assert {d["technician_name"] for d in docs} == expected
