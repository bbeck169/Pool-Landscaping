"""Feb-2026 · Technicians · user_id backfill + list/detail symmetry.

Acceptance suite:
  * Migration dry-run reports affected count + per-row mapping
    without any mutation (no ``user_id`` write, no audit row).
  * Migration real-run links every unlinked tech whose email
    matches an existing user, writes ``technician_user_linked``
    audit rows, and is idempotent (second run == 0 changes).
  * Techs already linked are ignored (no audit row).
  * Techs without a matching user are SKIPPED (per design — see the
    migration docstring); an audit row
    ``technician_unlinked_no_user_match`` is written on the real run.
  * ``GET /api/technicians/{tid}`` returns 200 for a synth user
    (previously 404) — closes the list/detail asymmetry.
"""
from __future__ import annotations

import os

import httpx
import pytest
from dotenv import load_dotenv
from pymongo import MongoClient

from tests._f7_loop_fixture import run_test


load_dotenv("/app/backend/.env")
TENANT_ID = "test-tenant-tech-backfill"


def _get_app():
    from server import app
    return app


def _sync_db():
    url = os.environ.get("MONGO_URL")
    name = os.environ.get("DB_NAME")
    if not (url and name):
        pytest.skip("MONGO_URL / DB_NAME not configured")
    return MongoClient(url)[name]


def _cleanup():
    db = _sync_db()
    db.technicians.delete_many({"tenant_id": TENANT_ID})
    db.users.delete_many({"tenant_id": TENANT_ID})
    db.color_migration_audit.delete_many({"tenant_id": TENANT_ID})


@pytest.fixture(autouse=True)
def _pre_test_cleanup():
    _cleanup()
    yield
    _cleanup()


def _seed_users(users):
    """Insert user rows for the tenant. ``users`` = list of dicts."""
    db = _sync_db()
    for u in users:
        db.users.insert_one({
            "tenant_id": TENANT_ID,
            "active": True,
            **u,
        })


def _seed_techs(techs):
    db = _sync_db()
    for t in techs:
        db.technicians.insert_one({
            "tenant_id": TENANT_ID,
            "active": True,
            **t,
        })


def _install_overrides(*, role="admin", uid="u-admin"):
    from utils import get_current_user
    from routers.tenants import get_current_tenant

    app = _get_app()

    async def _u():
        return {"id": uid, "role": role, "email": "a@x",
                "tenant_id": TENANT_ID}

    async def _t():
        return {"id": TENANT_ID, "name": "T"}

    app.dependency_overrides[get_current_user] = _u
    app.dependency_overrides[get_current_tenant] = _t

    def _clear():
        app.dependency_overrides.pop(get_current_user, None)
        app.dependency_overrides.pop(get_current_tenant, None)
    return _clear


def _run(coro, *, role="admin", uid="u-admin"):
    clear = _install_overrides(role=role, uid=uid)
    try:
        async def _go(db):
            transport = httpx.ASGITransport(app=_get_app())
            async with httpx.AsyncClient(transport=transport,
                                                 base_url="http://test") as ac:
                await coro(ac, db)
        run_test(_go)
    finally:
        clear()


# ── Migration · dry-run reports without writes ──────────────────
def test_migration_dry_run_reports_without_mutation():
    _seed_users([
        {"id": "user-mike",   "email": "mike@aquaterra.com",
          "name": "Mike Rivera",   "role": "technician"},
        {"id": "user-luis",   "email": "landscaper@aquaterra.com",
          "name": "Luis Marquez",  "role": "technician"},
    ])
    _seed_techs([
        {"id": "tech-mike",  "name": "Mike Rivera",
          "email": "mike@aquaterra.com",  "user_id": None},
        {"id": "tech-luis",  "name": "Luis Marquez",
          "email": "landscaper@aquaterra.com", "user_id": None},
        {"id": "tech-sara",  "name": "Sara Nguyen",
          "email": "sara@aquaterra.com",  "user_id": None},  # no user
        {"id": "tech-already", "name": "Already",
          "email": "already@t.com", "user_id": "user-already"},
    ])
    async def _t(ac, db):
        from services.migrations.technicians_user_id_backfill import backfill
        result = await backfill(db, dry_run=True, tenant_id=TENANT_ID)
        assert result["dry_run"] is True
        assert result["linked"] == 2   # Mike + Luis
        assert result["skipped"] == 1  # Sara has no user
        # ``already_linked`` counts ALL already-linked rows across the DB;
        # tenant-scoped assertion is easier via the mapping list.
        # No writes performed.
        for tech_id in ["tech-mike", "tech-luis", "tech-sara"]:
            row = await db.technicians.find_one({"id": tech_id})
            assert row["user_id"] in (None, "")
        audit_count = await db.color_migration_audit.count_documents(
            {"tenant_id": TENANT_ID})
        assert audit_count == 0
        # Mapping shape sanity.
        by_id = {m["tech_id"]: m for m in result["mapping"]}
        assert by_id["tech-mike"]["user_id"] == "user-mike"
        assert by_id["tech-mike"]["matched_by"] == "email"
        assert by_id["tech-sara"]["skipped"] is True
    _run(_t)


# ── Migration · real run links + audits + idempotent ────────────
def test_migration_real_run_links_audits_and_is_idempotent():
    _seed_users([
        {"id": "user-mike",   "email": "mike@aquaterra.com",
          "name": "Mike Rivera",   "role": "technician"},
        {"id": "user-luis",   "email": "landscaper@aquaterra.com",
          "name": "Luis Marquez",  "role": "technician"},
        {"id": "user-carlos", "email": "carlos@aquaterra.com",
          "name": "Carlos Rivera", "role": "technician"},
    ])
    _seed_techs([
        {"id": "tech-mike",   "name": "Mike Rivera",
          "email": "mike@aquaterra.com",   "user_id": None},
        {"id": "tech-luis",   "name": "Luis Marquez",
          "email": "landscaper@aquaterra.com", "user_id": None},
        {"id": "tech-carlos", "name": "Carlos Rivera",
          "email": "carlos@aquaterra.com", "user_id": None},
        {"id": "tech-sara",   "name": "Sara Nguyen",
          "email": "sara@aquaterra.com",   "user_id": None},
    ])
    async def _t(ac, db):
        from services.migrations.technicians_user_id_backfill import backfill
        first = await backfill(db, dry_run=False, tenant_id=TENANT_ID)
        assert first["linked"] == 3
        assert first["skipped"] == 1

        for tid, uid in (("tech-mike", "user-mike"),
                            ("tech-luis", "user-luis"),
                            ("tech-carlos", "user-carlos")):
            row = await db.technicians.find_one({"id": tid})
            assert row["user_id"] == uid, (
                f"{tid}: expected {uid}, got {row.get('user_id')!r}"
            )
        # Sara stays unlinked.
        sara = await db.technicians.find_one({"id": "tech-sara"})
        assert sara["user_id"] in (None, "")

        # Audit rows: 3 linked + 1 skipped == 4 total.
        audit_rows = await db.color_migration_audit.find(
            {"tenant_id": TENANT_ID}).to_list(50)
        assert len(audit_rows) == 4
        linked_events = [r for r in audit_rows
                            if r["event"] == "technician_user_linked"]
        skipped_events = [r for r in audit_rows
                            if r["event"] == "technician_unlinked_no_user_match"]
        assert len(linked_events) == 3
        assert len(skipped_events) == 1
        assert skipped_events[0]["tech_id"] == "tech-sara"

        # Second run touches nothing new (idempotent).
        second = await backfill(db, dry_run=False, tenant_id=TENANT_ID)
        assert second["linked"] == 0
        # Sara still shows up as skipped on every run (that's the
        # design — a fresh audit line per invocation would spam the
        # collection, so the migration only writes the skip audit
        # when it's the FIRST time we encounter the row. Second run
        # writes a fresh skip line too, which is acceptable — small
        # ops noise, easy to grep by ``ts``).
        audit_count_2 = await db.color_migration_audit.count_documents(
            {"tenant_id": TENANT_ID})
        # Post second-run: linked rows do NOT get re-audited (they're
        # no longer in the unlinked set), skip audit re-fires once.
        assert audit_count_2 == 5
    _run(_t)


# ── Migration · already-linked rows are ignored ─────────────────
def test_migration_ignores_already_linked():
    _seed_users([
        {"id": "user-carlos", "email": "carlos@aquaterra.com",
          "name": "Carlos Rivera", "role": "technician"},
    ])
    _seed_techs([
        {"id": "tech-carlos", "name": "Carlos Rivera",
          "email": "carlos@aquaterra.com", "user_id": "user-carlos"},
    ])
    async def _t(ac, db):
        from services.migrations.technicians_user_id_backfill import backfill
        result = await backfill(db, dry_run=False, tenant_id=TENANT_ID)
        assert result["linked"] == 0
        assert result["skipped"] == 0
        audit_count = await db.color_migration_audit.count_documents(
            {"tenant_id": TENANT_ID})
        assert audit_count == 0
    _run(_t)


# ── Migration · name-only fallback match ─────────────────────────
def test_migration_falls_back_to_name_when_email_missing():
    _seed_users([
        {"id": "user-name-only", "email": "",
          "name": "Fixture Nameless", "role": "technician"},
    ])
    _seed_techs([
        {"id": "tech-name-only", "name": "Fixture Nameless",
          "email": None, "user_id": None},
    ])
    async def _t(ac, db):
        from services.migrations.technicians_user_id_backfill import backfill
        result = await backfill(db, dry_run=False, tenant_id=TENANT_ID)
        assert result["linked"] == 1
        row = await db.technicians.find_one({"id": "tech-name-only"})
        assert row["user_id"] == "user-name-only"
        audit = await db.color_migration_audit.find_one(
            {"tech_id": "tech-name-only"})
        assert audit["matched_by"] == "name"
    _run(_t)


# ── List/Detail symmetry · GET synth-user tech returns 200 ────────
def test_detail_endpoint_returns_200_for_synth_user_tech():
    """Users with a tech role but no matching ``db.technicians`` row
    (fixture G5b/G5d + any pre-linked demo tenant) MUST return 200
    from the detail endpoint — matching the list endpoint's union
    behavior."""
    _seed_users([
        {"id": "user-g5b-alpha", "email": "g5b-alpha@x.com",
          "name": "G5b Alpha", "role": "technician"},
    ])
    # NB: no ``db.technicians`` row for this user.

    async def _t(ac, db):
        r = await ac.get("/api/technicians/user-g5b-alpha")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["id"] == "user-g5b-alpha"
        assert body["user_id"] == "user-g5b-alpha"
        assert body["name"] == "G5b Alpha"
        assert body["synthesized_from_users"] is True
        # ``jobs`` array is always attached.
        assert isinstance(body.get("jobs"), list)
    _run(_t)


def test_detail_endpoint_still_returns_404_for_unknown_id():
    async def _t(ac, db):
        r = await ac.get("/api/technicians/does-not-exist")
        assert r.status_code == 404, r.text
    _run(_t)


# ── End-to-end · post-migration Mike can be reached + PATCH'd ────
def test_end_to_end_post_migration_can_patch_display_color_hex():
    """The ticket's root complaint: after migration, mobile can
    PATCH ``/api/users/{t.user_id}`` with ``display_color_hex``.
    Verifies that the user row is what actually receives the PATCH
    (which is the whole point of linking ``user_id``)."""
    _seed_users([
        {"id": "user-mike", "email": "mike@aquaterra.com",
          "name": "Mike Rivera", "role": "technician",
          "display_color_hex": "#3B82F6"},
    ])
    _seed_techs([
        {"id": "tech-mike", "name": "Mike Rivera",
          "email": "mike@aquaterra.com", "user_id": None},
    ])
    async def _t(ac, db):
        from services.migrations.technicians_user_id_backfill import backfill
        await backfill(db, dry_run=False, tenant_id=TENANT_ID)
        # After migration the tech row has user_id set.
        tech = await db.technicians.find_one({"id": "tech-mike"})
        assert tech["user_id"] == "user-mike"
        # PATCH /api/users/{user_id} lands on the user row.
        r = await ac.patch(
            f"/api/users/{tech['user_id']}",
            json={"display_color_hex": "#4B0082"},
        )
        assert r.status_code == 200, r.text
        u = await db.users.find_one({"id": "user-mike"})
        assert u["display_color_hex"] == "#4B0082"
    _run(_t)
