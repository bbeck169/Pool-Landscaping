"""Task G · Feb-2026 — Coverage for the P59 HIGH #1 closure +
Task G server-side filter params on ``GET /items``.

Companion to Commit 1 (``2eeb52191``) which refactored
``list_items`` (``routers/items.py`` L89-…) to:

  1. Scope every read to ``user.get('tenant_id')`` via
     ``services.query_scope.tenant_scoped_filter``.  This closes
     the P59 HIGH #1 leak documented in the P58 handoff — prior
     to this fix the handler ran ``db.items.find({...deleted...})``
     with NO tenant filter, so any admin could enumerate cross-
     tenant pricebook rows.
  2. Accept optional query params ``search`` (case-insensitive,
     regex-escaped substring on ``name`` OR ``description``),
     ``active`` (default true; false includes soft-deleted), and
     ``limit`` (default 1000, ``ge=1, le=1000``).

Precedent: ``test_p58_patch_item_tenant_isolation.py`` shares the
fixture shape (``_login`` / ``super_headers`` / ``aq_tenant_id`` /
``foreign_tenant_id`` / ``_plant_item``) and the two-tenant
cross-write assertion pattern.
"""
from __future__ import annotations

import os
import uuid
from typing import Optional

import pytest

from tests._phase34_http_shim import http
from tests._phase34_asyncio import batch_safe_run as _run


BASE_URL = (
    os.environ.get("REACT_APP_BACKEND_URL")
    or os.environ.get("EXPO_PUBLIC_BACKEND_URL")
    or "http://localhost:8001"
).rstrip("/")
API = f"{BASE_URL}/api"


def _login(email: str, password: str = "password123") -> str:
    r = http.post(
        f"{API}/auth/login",
        json={"email": email, "password": password}, timeout=30,
    )
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def db():
    from config import db as _db  # noqa: PLC0415
    return _db


@pytest.fixture(scope="module")
def aq_tenant_id(db) -> str:
    async def _go():
        t = await db.tenants.find_one(
            {"slug": "aquaterra"}, {"_id": 0, "id": 1},
        )
        return t["id"]
    return _run(_go())


@pytest.fixture(scope="module")
def super_headers() -> dict:
    return {"Authorization": f"Bearer {_login('super@aquaterra.com')}"}


@pytest.fixture(scope="module")
def foreign_tenant_id(db) -> Optional[str]:
    """Locate any tenant that is NOT aquaterra so we can plant a
    cross-tenant target row. Skips the cross-tenant assertion when
    the preview seed only carries one tenant."""
    async def _go():
        aq = await db.tenants.find_one(
            {"slug": "aquaterra"}, {"_id": 0, "id": 1},
        )
        aq_id = aq["id"] if aq else None
        other = await db.tenants.find_one(
            {"id": {"$ne": aq_id}}, {"_id": 0, "id": 1},
        )
        return other["id"] if other else None
    return _run(_go())


def _plant_item(
    db,
    tenant_id: str,
    name: str,
    description: str = "P59 seed row",
    unit_price: float = 25.0,
    deleted: bool = False,
) -> str:
    """Seed a pricebook row in the given tenant. Returns the item
    id. Mirrors ``test_p58_patch_item_tenant_isolation``'s planter
    shape so the ``list_items`` filter path treats it as well-
    formed."""
    iid = uuid.uuid4().hex

    async def _go():
        doc = {
            "id": iid,
            "tenant_id": tenant_id,
            "name": name,
            "description": description,
            "category": "Pool",
            "unit": "each",
            "unit_price": unit_price,
            "cost": 5.0,
            "tax_rate": 8.0,
            "active": True,
            "created_at": "2026-02-01T00:00:00Z",
        }
        if deleted:
            doc["deleted_at"] = "2026-02-05T00:00:00Z"
        await db.items.insert_one(doc)
    _run(_go())
    return iid


def _cleanup_planted(db, iids: list[str]) -> None:
    """Hard-delete every planted row so serial test runs stay
    idempotent. Called from the fixture teardown of each test
    function that plants — kept out of a module-level teardown so
    each test isolates its own seed."""
    async def _go():
        if iids:
            await db.items.delete_many({"id": {"$in": iids}})
    _run(_go())


# ─────────────────────────────────────────────────────────────────
# P59 HIGH #1 primary security assertion — isolated test function
# ─────────────────────────────────────────────────────────────────

def test_list_items_cross_tenant_scoping_closes_p59_high_1(
    db, super_headers, aq_tenant_id, foreign_tenant_id,
):
    """P59 HIGH #1 closure — a super-admin from aquaterra
    listing ``/items`` must receive ONLY aquaterra rows. Prior to
    Commit 1 the handler ran an unscoped ``db.items.find`` and
    would return every tenant's rows to any caller. This is the
    canonical cross-tenant read-leak regression guard."""
    if not foreign_tenant_id:
        pytest.skip(
            "preview seed has only one tenant; cross-tenant "
            "assertion cannot be exercised in this environment"
        )
    planted: list[str] = []
    try:
        aq_iid = _plant_item(
            db, tenant_id=aq_tenant_id,
            name=f"P59-aq-{uuid.uuid4().hex[:6]}",
        )
        foreign_iid = _plant_item(
            db, tenant_id=foreign_tenant_id,
            name=f"P59-foreign-{uuid.uuid4().hex[:6]}",
        )
        planted += [aq_iid, foreign_iid]

        r = http.get(f"{API}/items", headers=super_headers, timeout=30)
        assert r.status_code == 200, r.text
        rows = r.json()
        assert isinstance(rows, list)

        # Every returned row belongs to aquaterra.
        tenant_ids = {row.get("tenant_id") for row in rows}
        assert tenant_ids == {aq_tenant_id}, (
            f"P59 HIGH #1 LEAK — expected only {aq_tenant_id!r} in "
            f"the response, saw {tenant_ids!r}"
        )

        # aquaterra planted row is present; foreign planted row is NOT.
        returned_iids = {row.get("id") for row in rows}
        assert aq_iid in returned_iids
        assert foreign_iid not in returned_iids
    finally:
        _cleanup_planted(db, planted)


# ─────────────────────────────────────────────────────────────────
# Task G server-side filter parameter coverage
# ─────────────────────────────────────────────────────────────────

def test_search_matches_name_case_insensitive(
    db, super_headers, aq_tenant_id,
):
    """``search=CHLOR`` matches a row named ``Chlorine Tablets``
    (case-insensitive, substring on ``name``)."""
    planted: list[str] = []
    try:
        iid = _plant_item(
            db, tenant_id=aq_tenant_id,
            name=f"Chlorine Tablets ({uuid.uuid4().hex[:6]})",
        )
        planted.append(iid)

        r = http.get(
            f"{API}/items",
            headers=super_headers,
            params={"search": "CHLOR"},
            timeout=30,
        )
        assert r.status_code == 200, r.text
        rows = r.json()
        # The planted row must appear.
        assert any(row.get("id") == iid for row in rows)
    finally:
        _cleanup_planted(db, planted)


def test_search_matches_description_case_insensitive(
    db, super_headers, aq_tenant_id,
):
    """``search=`` also matches on ``description`` — needed by
    the K71 picker when users search on longer text."""
    planted: list[str] = []
    try:
        iid = _plant_item(
            db, tenant_id=aq_tenant_id,
            name=f"P59-desc-{uuid.uuid4().hex[:6]}",
            description="Weekly filter cartridge replacement",
        )
        planted.append(iid)

        r = http.get(
            f"{API}/items",
            headers=super_headers,
            params={"search": "cartridge"},
            timeout=30,
        )
        assert r.status_code == 200, r.text
        rows = r.json()
        assert any(row.get("id") == iid for row in rows), (
            "description substring match should surface the planted row"
        )
    finally:
        _cleanup_planted(db, planted)


@pytest.mark.parametrize(
    "hostile",
    ["foo.bar[baz]", "foo(bar)", "foo|bar", "foo+bar*", "foo\\qux"],
)
def test_search_regex_hostile_input_does_not_throw(
    db, super_headers, hostile,
):
    """Regex meta-chars in ``search=`` must be escaped so a hostile
    input can't crash the handler with a bad ``$regex`` compile.
    Returns 200 with an empty list (or whatever legitimately
    matches the literal substring)."""
    r = http.get(
        f"{API}/items",
        headers=super_headers,
        params={"search": hostile},
        timeout=30,
    )
    assert r.status_code == 200, (
        f"regex-hostile input {hostile!r} produced HTTP {r.status_code}: {r.text}"
    )
    assert isinstance(r.json(), list)


def test_active_false_includes_soft_deleted_rows(
    db, super_headers, aq_tenant_id,
):
    """``active=false`` bypasses ``tenant_scoped_filter`` so
    tombstoned rows appear in the response.  The default
    (``active=true``) MUST NOT surface them."""
    unique_tag = uuid.uuid4().hex[:8]
    planted: list[str] = []
    try:
        dead_iid = _plant_item(
            db, tenant_id=aq_tenant_id,
            name=f"P59-dead-{unique_tag}",
            deleted=True,
        )
        live_iid = _plant_item(
            db, tenant_id=aq_tenant_id,
            name=f"P59-live-{unique_tag}",
        )
        planted += [dead_iid, live_iid]

        # Default (active=true) — soft-deleted excluded.
        r_default = http.get(
            f"{API}/items",
            headers=super_headers,
            params={"search": unique_tag},
            timeout=30,
        )
        assert r_default.status_code == 200, r_default.text
        default_ids = {row.get("id") for row in r_default.json()}
        assert live_iid in default_ids
        assert dead_iid not in default_ids, (
            "active=true (default) must NOT include soft-deleted rows"
        )

        # active=false — soft-deleted included.
        r_all = http.get(
            f"{API}/items",
            headers=super_headers,
            params={"search": unique_tag, "active": "false"},
            timeout=30,
        )
        assert r_all.status_code == 200, r_all.text
        all_ids = {row.get("id") for row in r_all.json()}
        assert live_iid in all_ids
        assert dead_iid in all_ids, (
            "active=false must include tombstoned rows"
        )
    finally:
        _cleanup_planted(db, planted)


def test_limit_caps_response_length(db, super_headers):
    """``limit=N`` caps the response at N rows.  Default cap is
    1000; ``ge=1, le=1000`` is enforced by Pydantic."""
    r = http.get(
        f"{API}/items",
        headers=super_headers,
        params={"limit": 3},
        timeout=30,
    )
    assert r.status_code == 200, r.text
    rows = r.json()
    assert isinstance(rows, list)
    assert len(rows) <= 3


def test_limit_over_cap_returns_422(db, super_headers):
    """``limit>1000`` fails Pydantic validation."""
    r = http.get(
        f"{API}/items",
        headers=super_headers,
        params={"limit": 5000},
        timeout=30,
    )
    assert r.status_code == 422, r.text


def test_limit_zero_returns_422(db, super_headers):
    """``limit=0`` fails Pydantic validation (``ge=1``)."""
    r = http.get(
        f"{API}/items",
        headers=super_headers,
        params={"limit": 0},
        timeout=30,
    )
    assert r.status_code == 422, r.text


def test_empty_search_string_is_treated_as_no_filter(
    db, super_headers, aq_tenant_id,
):
    """``search=""`` (empty string) MUST behave like no ``search``
    param at all — otherwise a stray URL-encoded empty query
    would either match nothing OR match everything with a weird
    regex compile.  We confirm the empty-string case returns the
    full tenant-scoped default (>= 1 row on the preview seed)."""
    r = http.get(
        f"{API}/items",
        headers=super_headers,
        params={"search": ""},
        timeout=30,
    )
    assert r.status_code == 200, r.text
    rows = r.json()
    assert isinstance(rows, list)
    # Preview seed has 73+ aquaterra items; empty string must not
    # collapse the response to nothing.
    assert len(rows) > 0
    # Every returned row is tenant-scoped.
    tids = {row.get("tenant_id") for row in rows}
    assert tids == {aq_tenant_id}


def test_combined_search_active_limit_compose_correctly(
    db, super_headers, aq_tenant_id,
):
    """``search=`` + ``active=false`` + ``limit=`` compose in a
    single call.  Guards against parameter-precedence regressions
    (e.g. limit being applied before the search filter)."""
    unique_tag = uuid.uuid4().hex[:8]
    planted: list[str] = []
    try:
        for i in range(3):
            planted.append(_plant_item(
                db, tenant_id=aq_tenant_id,
                name=f"P59-combo-{unique_tag}-{i}",
                deleted=(i == 2),
            ))

        r = http.get(
            f"{API}/items",
            headers=super_headers,
            params={
                "search": unique_tag,
                "active": "false",
                "limit": 5,
            },
            timeout=30,
        )
        assert r.status_code == 200, r.text
        rows = r.json()
        # All 3 planted rows appear (limit=5 headroom, active=false
        # includes tombstoned, search=unique_tag isolates the set).
        found = {row.get("id") for row in rows}
        assert set(planted).issubset(found), (
            f"expected {planted} in {found}"
        )
    finally:
        _cleanup_planted(db, planted)


def test_default_no_params_returns_tenant_scoped_active_rows(
    db, super_headers, aq_tenant_id,
):
    """Backwards-compat check — a bare ``GET /items`` with no
    params returns tenant-scoped, active rows, name-sorted, up to
    1000. Pricebook page + JobNew rely on this default."""
    r = http.get(f"{API}/items", headers=super_headers, timeout=30)
    assert r.status_code == 200, r.text
    rows = r.json()
    assert isinstance(rows, list)
    assert 0 < len(rows) <= 1000

    # All rows belong to the caller's tenant.
    tids = {row.get("tenant_id") for row in rows}
    assert tids == {aq_tenant_id}

    # All rows are active (no soft-deleted).
    for row in rows:
        assert not row.get("deleted_at"), (
            f"row {row.get('id')} has deleted_at={row.get('deleted_at')!r}"
        )

    # Sort is by name ascending, matching MongoDB's byte-order
    # default (case-sensitive) — mirror that in the assertion.
    names = [row.get("name") or "" for row in rows]
    assert names == sorted(names), (
        "default sort should be name-ascending (byte-order)"
    )


# ─────────────────────────────────────────────────────────────────
# P57 guard — inline ValueError check on empty tenant_id
# ─────────────────────────────────────────────────────────────────

def test_empty_tenant_id_raises_value_error_via_helper():
    """Unit-level guard — the ``list_items`` handler mirrors P57
    behavior by raising ``ValueError`` before any query when
    ``user['tenant_id']`` is empty / whitespace.

    The handler strips whitespace before calling the helper, so
    the whitespace-only case is caught inline. The helper itself
    only trips on empty string (``if not tenant_id``) — that's
    what we exercise here to pin the guard is wired."""
    from services.query_scope import tenant_scoped_filter  # noqa: PLC0415
    with pytest.raises(ValueError):
        tenant_scoped_filter("")


def test_handler_strips_whitespace_before_helper_call():
    """The handler-level guard in ``list_items`` strips whitespace
    and then checks ``if not tenant_id`` — so whitespace-only
    ``tenant_id`` on the user row triggers a ``ValueError`` at
    the top of the function, BEFORE the helper is called. This
    complements ``tenant_scoped_filter``'s own empty-string guard
    (which does NOT strip). Regression guard against a future
    handler refactor that skips the strip step."""
    import inspect  # noqa: PLC0415
    from routers.items import list_items  # noqa: PLC0415
    src = inspect.getsource(list_items)
    # Two invariants:
    #   1. ``.strip()`` is applied before the guard.
    #   2. ValueError is raised on empty tenant_id.
    assert ".strip()" in src, (
        "list_items handler must strip whitespace on tenant_id"
    )
    assert "raise ValueError" in src, (
        "list_items handler must raise ValueError on empty tenant_id"
    )
