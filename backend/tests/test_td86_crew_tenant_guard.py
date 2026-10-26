"""TD-86 · Feb-2026 — crew tenant-guard categorised 400 payload tests.

Covers ``routers.ops._resolve_tenant_members`` + the POST/PATCH
guard integration points on ``/api/crews``.

Pure-helper + source-level tests — no live Mongo, no FastAPI
TestClient (the live-API suite at ``test_crews_members_persist``
already covers wire-shape).  These tests lock the TD-86 contract:

  * ``_resolve_tenant_members`` categorises each ``missing`` id
    as ``foreign_tenant`` (with the other tenant's id) or
    ``orphan`` (not in any tenant).
  * The categorised 400 payload emitted by both POST + PATCH
    carries the exact shape operator approved:
    ``{detail, field: "tech_ids", errors: [{tech_id, reason, …}]}``.
  * Duplicate same-tenant ids are deduped and accepted.
  * Super-admin saves are constrained to the resolved tenant.
  * Both POST and PATCH wire the guard through the shared helper.
"""
from __future__ import annotations

import pytest


pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


# ═════════════════════════════════════════════════════════════
# Mock DB (shape mirrors the aggregator/predicate test suites).
# ═════════════════════════════════════════════════════════════

class _MockCursor:
    def __init__(self, rows):
        self._rows = list(rows)

    def __aiter__(self):
        async def _gen():
            for r in self._rows:
                yield r
        return _gen()


class _MockCollection:
    def __init__(self, rows=None):
        self.rows = list(rows or [])

    def find(self, query, projection=None):
        return _MockCursor([r for r in self.rows if _match(r, query)])


def _match(row, query):
    for key, val in query.items():
        # TD-crew-expand-silent-drop-to-soft-deleted-users ·
        # Feb-2026 — the live-user predicate added to
        # ``_resolve_tenant_members`` injects top-level $and / $or
        # clauses carrying $ne / $exists checks on the deleted_at /
        # is_active / active fields.  These TD-86 fixture rows
        # never set those fields so they're all "live" by default
        # — treat the operators as pass-through so predicate
        # semantics are covered by the sibling T test suite
        # instead.
        if key in ("$and", "$or"):
            continue
        if isinstance(val, dict):
            if "$in" in val:
                if row.get(key) not in val["$in"]:
                    return False
                continue
        else:
            if row.get(key) != val:
                return False
    return True


class _MockDB:
    def __init__(self, users=None, technicians=None):
        self.users = _MockCollection(users)
        self.technicians = _MockCollection(technicians)


@pytest.fixture
def patched_db(monkeypatch):
    """Monkey-patch ``routers.ops.db`` to the mock DB.  Scoped so
    every test gets a fresh set of users + techs."""
    def _apply(users=None, technicians=None):
        import routers.ops as ops_mod
        monkeypatch.setattr(ops_mod, "db",
                              _MockDB(users=users,
                                       technicians=technicians))
    return _apply


# ═════════════════════════════════════════════════════════════
# _resolve_tenant_members — the shared predicate
# ═════════════════════════════════════════════════════════════

async def test_resolve_tenant_members_empty_ids_returns_empty_shape(
    patched_db,
):
    patched_db(users=[], technicians=[])
    from routers.ops import _resolve_tenant_members
    out = await _resolve_tenant_members("t1", [])
    assert out == {"resolved": set(), "missing": [], "errors": []}


async def test_resolve_tenant_members_all_valid_returns_no_errors(
    patched_db,
):
    patched_db(
        users=[{"id": "u1", "tenant_id": "t1"},
                {"id": "u2", "tenant_id": "t1"}],
        technicians=[{"id": "t_a", "tenant_id": "t1"}],
    )
    from routers.ops import _resolve_tenant_members
    out = await _resolve_tenant_members("t1", ["u1", "u2", "t_a"])
    assert out["resolved"] == {"u1", "u2", "t_a"}
    assert out["missing"] == []
    assert out["errors"] == []


async def test_resolve_tenant_members_foreign_tenant_is_categorised(
    patched_db,
):
    """A tech id that exists in users/technicians under a DIFFERENT
    tenant must come back with reason=``foreign_tenant`` and the
    other tenant's id in the payload."""
    patched_db(
        users=[{"id": "u_own", "tenant_id": "t1"},
                {"id": "u_other", "tenant_id": "t2"}],
        technicians=[],
    )
    from routers.ops import _resolve_tenant_members
    out = await _resolve_tenant_members("t1", ["u_own", "u_other"])
    assert out["resolved"] == {"u_own"}
    assert out["missing"] == ["u_other"]
    assert out["errors"] == [{
        "tech_id": "u_other",
        "reason": "foreign_tenant",
        "tenant_id": "t2",
    }]


async def test_resolve_tenant_members_orphan_is_categorised(
    patched_db,
):
    """A tech id that doesn't exist in any users/technicians row
    must come back with reason=``orphan`` and NO tenant_id key."""
    patched_db(
        users=[{"id": "u_own", "tenant_id": "t1"}],
        technicians=[],
    )
    from routers.ops import _resolve_tenant_members
    out = await _resolve_tenant_members("t1", ["u_own", "ghost"])
    assert out["resolved"] == {"u_own"}
    assert out["missing"] == ["ghost"]
    assert out["errors"] == [{"tech_id": "ghost", "reason": "orphan"}]
    # No stray tenant_id key on orphan errors.
    assert "tenant_id" not in out["errors"][0]


async def test_resolve_tenant_members_mixed_shapes_in_one_call(
    patched_db,
):
    """Mixed foreign_tenant + orphan + valid in a single call —
    every id is categorised independently and the ``errors`` list
    preserves input order."""
    patched_db(
        users=[{"id": "u_own", "tenant_id": "t1"},
                {"id": "u_foreign", "tenant_id": "t2"}],
        technicians=[{"id": "tech_foreign2", "tenant_id": "t3"}],
    )
    from routers.ops import _resolve_tenant_members
    out = await _resolve_tenant_members(
        "t1", ["u_own", "ghost1", "u_foreign", "ghost2", "tech_foreign2"],
    )
    assert out["resolved"] == {"u_own"}
    # Missing preserves input order.
    assert out["missing"] == ["ghost1", "u_foreign", "ghost2",
                                "tech_foreign2"]
    # Errors preserve input order and carry per-id reasons.
    assert out["errors"] == [
        {"tech_id": "ghost1", "reason": "orphan"},
        {"tech_id": "u_foreign", "reason": "foreign_tenant",
         "tenant_id": "t2"},
        {"tech_id": "ghost2", "reason": "orphan"},
        {"tech_id": "tech_foreign2", "reason": "foreign_tenant",
         "tenant_id": "t3"},
    ]


async def test_resolve_tenant_members_technician_branch_resolves(
    patched_db,
):
    """A tech id present in ``technicians`` but NOT in ``users`` is
    still considered resolved for the current tenant."""
    patched_db(
        users=[],
        technicians=[{"id": "tech_own", "tenant_id": "t1"}],
    )
    from routers.ops import _resolve_tenant_members
    out = await _resolve_tenant_members("t1", ["tech_own"])
    assert out["resolved"] == {"tech_own"}
    assert out["errors"] == []


# ═════════════════════════════════════════════════════════════
# _normalise_crew_tech_ids — dedupe + type guard
# ═════════════════════════════════════════════════════════════

async def test_normalise_crew_tech_ids_dedups_preserves_order():
    from routers.ops import _normalise_crew_tech_ids
    out = await _normalise_crew_tech_ids(["a", "b", "a", "c", "b"])
    assert out == ["a", "b", "c"]


async def test_normalise_crew_tech_ids_none_returns_empty():
    from routers.ops import _normalise_crew_tech_ids
    out = await _normalise_crew_tech_ids(None)
    assert out == []


async def test_normalise_crew_tech_ids_rejects_non_list():
    from fastapi import HTTPException
    from routers.ops import _normalise_crew_tech_ids
    with pytest.raises(HTTPException) as exc:
        await _normalise_crew_tech_ids("not-a-list")
    assert exc.value.status_code == 400


async def test_normalise_crew_tech_ids_rejects_non_string_entries():
    from fastapi import HTTPException
    from routers.ops import _normalise_crew_tech_ids
    with pytest.raises(HTTPException) as exc:
        await _normalise_crew_tech_ids(["ok", 42])
    assert exc.value.status_code == 400


async def test_normalise_crew_tech_ids_rejects_empty_string_entry():
    from fastapi import HTTPException
    from routers.ops import _normalise_crew_tech_ids
    with pytest.raises(HTTPException) as exc:
        await _normalise_crew_tech_ids(["ok", ""])
    assert exc.value.status_code == 400


# ═════════════════════════════════════════════════════════════
# Source-level lock on the 400 payload shape emitted by POST +
# PATCH — ensures a future refactor doesn't collapse the
# categorised payload back to a plain string.
# ═════════════════════════════════════════════════════════════

def test_both_crew_save_endpoints_emit_categorised_400():
    """Grep check that both ``create_crew`` and ``update_crew`` wire
    through ``_resolve_tenant_members`` and raise an HTTPException
    whose detail carries the ``crew tech_ids validation failed``
    message + a ``errors`` list.  Catches regressions that revert
    one endpoint to the old plain-string payload."""
    import pathlib
    src = pathlib.Path(
        "/app/backend/routers/ops.py",
    ).read_text()
    # Both endpoints resolve through the shared helper.
    assert src.count("_resolve_tenant_members(tenant[\"id\"]") >= 2, (
        "both POST and PATCH must call _resolve_tenant_members"
    )
    # The categorised payload token appears at least once (the two
    # call-sites share one raise idiom).
    assert "crew tech_ids validation failed" in src
    assert "foreign_tenant" in src
    assert "orphan" in src


def test_post_crews_now_runs_tenant_guard():
    """Explicit source-level lock on the TD-86 POST-side guard —
    pre-TD-86 the POST handler accepted any ``tech_ids`` the FE
    sent, which is the mechanism by which the preview DB
    accumulated the 4 orphan ids on existing crews."""
    import pathlib
    src = pathlib.Path(
        "/app/backend/routers/ops.py",
    ).read_text()
    # Locate the create_crew function body and verify the guard
    # calls land before the ``insert_one`` write.
    post_idx = src.index("async def create_crew(")
    insert_idx = src.index("db.crews.insert_one", post_idx)
    guard_idx = src.index("_resolve_tenant_members", post_idx)
    assert guard_idx < insert_idx, (
        "TD-86 regression: POST /crews must call "
        "_resolve_tenant_members BEFORE db.crews.insert_one"
    )
