"""Feb-2026 · Normalize legacy ``users.department`` tokens — tests.

Ships with ``backend/migrations/normalize_user_department_tokens.py``.

Coverage:
1.  Legacy ``"pool"`` + ``"landscape_tech"`` rows are remapped to the
    modern enum tokens.
2.  Rows already in the modern enum (``"pool_tech"``, ``"landscaping"``,
    ``"both"``) are NOT touched.
3.  Rows with ``department: null`` / missing field are NOT touched.
4.  Uppercase / mixed-case drift (``"POOL"``, ``"Landscape_Tech"``)
    also gets normalized.
5.  Idempotency — running the migration twice on the same DB
    reports ``updated == 0`` on the second run.
6.  Companion ``technicians`` collection is mirrored (same enum
    invariant applies there for the ``jobs.py`` checklist-kind
    derivation).
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from uuid import uuid4

import pytest
from dotenv import dotenv_values
from motor.motor_asyncio import AsyncIOMotorClient

_ENV = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
_LOOP = asyncio.new_event_loop()
asyncio.set_event_loop(_LOOP)
_MC = AsyncIOMotorClient(_ENV["MONGO_URL"], io_loop=_LOOP)
_DB = _MC[_ENV["DB_NAME"]]


def _run(coro):
    asyncio.set_event_loop(_LOOP)
    return _LOOP.run_until_complete(coro)


# Isolate every test fixture behind a distinct email prefix so we
# never clobber a real seeded user row.
PREFIX = f"testnormdept-{uuid4().hex[:8]}"


async def _seed_users(cases: dict[str, str | None]) -> None:
    """Insert one user per (email_local_part, department) case."""
    for local, dept in cases.items():
        doc = {
            "id": f"{PREFIX}-{local}",
            "email": f"{PREFIX}-{local}@example.com",
            "name": f"{PREFIX} {local}",
            "role": "technician",
        }
        if dept is None:
            doc["department"] = None
        elif dept != "__MISSING__":
            doc["department"] = dept
        # else: don't set the key at all
        await _DB.users.insert_one(doc)


async def _seed_technicians(cases: dict[str, str]) -> None:
    for local, dept in cases.items():
        await _DB.technicians.insert_one({
            "id": f"{PREFIX}-tech-{local}",
            "email": f"{PREFIX}-{local}@example.com",
            "name": f"{PREFIX} {local}",
            "department": dept,
        })


async def _cleanup() -> None:
    await _DB.users.delete_many({"id": {"$regex": f"^{PREFIX}"}})
    await _DB.technicians.delete_many({"id": {"$regex": f"^{PREFIX}"}})


async def _dept_of(local: str) -> str | None:
    row = await _DB.users.find_one(
        {"id": f"{PREFIX}-{local}"}, {"_id": 0, "department": 1},
    )
    return None if row is None else row.get("department")


@pytest.fixture(autouse=True)
def _clean():
    _run(_cleanup())
    yield
    _run(_cleanup())


# ═══════════════════════════════════════════════════════════════════
# 1 · legacy → modern remap
# ═══════════════════════════════════════════════════════════════════
def test_migrates_pool_and_landscaping_users():
    _run(_seed_users({
        "mike":   "pool",
        "carlos": "landscape_tech",      # flipped 2026-10-02 — now the LEGACY key
        "luis":   "landscape",           # defensive alias (unchanged scope)
    }))
    from migrations.normalize_user_department_tokens import run
    result = _run(run(_DB))
    assert result["ok"] is True
    assert result["users"]["matched"] == 3
    assert result["users"]["updated"] == 3
    assert _run(_dept_of("mike"))   == "pool_tech"
    assert _run(_dept_of("carlos")) == "landscaping"
    assert _run(_dept_of("luis"))   == "landscape_tech"


# ═══════════════════════════════════════════════════════════════════
# 2 · modern-enum rows are NEVER touched
# ═══════════════════════════════════════════════════════════════════
def test_leaves_modern_enum_alone():
    _run(_seed_users({
        "mod-pool":  "pool_tech",
        "mod-land":  "landscaping",      # flipped 2026-10-02 — new canonical value
        "mod-both":  "both",
    }))
    from migrations.normalize_user_department_tokens import run
    result = _run(run(_DB))
    # No matches — modern tokens are not in LEGACY_MAP.
    assert result["users"]["matched"] == 0
    assert result["users"]["updated"] == 0
    assert _run(_dept_of("mod-pool"))  == "pool_tech"
    assert _run(_dept_of("mod-land"))  == "landscaping"
    assert _run(_dept_of("mod-both"))  == "both"


# ═══════════════════════════════════════════════════════════════════
# 3 · null / missing rows are NEVER touched
# ═══════════════════════════════════════════════════════════════════
def test_leaves_null_and_missing_alone():
    _run(_seed_users({
        "nulldept": None,
        "nofield":  "__MISSING__",
    }))
    from migrations.normalize_user_department_tokens import run
    result = _run(run(_DB))
    assert result["users"]["matched"] == 0
    assert result["users"]["updated"] == 0
    # null stays null; missing field stays missing.
    assert _run(_dept_of("nulldept")) is None
    row = _run(_DB.users.find_one({"id": f"{PREFIX}-nofield"}, {"_id": 0}))
    assert "department" not in row


# ═══════════════════════════════════════════════════════════════════
# 4 · case-insensitive normalization
# ═══════════════════════════════════════════════════════════════════
def test_normalizes_case_drift():
    _run(_seed_users({
        "shout":   "POOL",
        "title":   "Landscape_Tech",     # flipped 2026-10-02 — now the LEGACY key
        "spaces":  "  pool  ",
    }))
    from migrations.normalize_user_department_tokens import run
    result = _run(run(_DB))
    assert result["users"]["matched"] == 3
    assert result["users"]["updated"] == 3
    assert _run(_dept_of("shout"))  == "pool_tech"
    assert _run(_dept_of("title"))  == "landscaping"
    assert _run(_dept_of("spaces")) == "pool_tech"


# ═══════════════════════════════════════════════════════════════════
# 5 · idempotency — second run reports 0 updates
# ═══════════════════════════════════════════════════════════════════
def test_idempotent():
    _run(_seed_users({"mike": "pool", "carlos": "landscape_tech"}))
    from migrations.normalize_user_department_tokens import run
    first = _run(run(_DB))
    assert first["users"]["updated"] == 2
    second = _run(run(_DB))
    assert second["users"]["matched"] == 0
    assert second["users"]["updated"] == 0
    # Values still correct after two passes.
    assert _run(_dept_of("mike"))   == "pool_tech"
    assert _run(_dept_of("carlos")) == "landscaping"


# ═══════════════════════════════════════════════════════════════════
# 6 · technicians collection is mirrored
# ═══════════════════════════════════════════════════════════════════
def test_mirrors_technicians_collection():
    _run(_seed_technicians({"mike": "pool", "luis": "landscape_tech"}))
    from migrations.normalize_user_department_tokens import run
    result = _run(run(_DB))
    assert result["technicians"]["matched"] == 2
    assert result["technicians"]["updated"] == 2
    for local, expected in [("mike", "pool_tech"), ("luis", "landscaping")]:
        row = _run(_DB.technicians.find_one(
            {"id": f"{PREFIX}-tech-{local}"}, {"_id": 0, "department": 1},
        ))
        assert row["department"] == expected
