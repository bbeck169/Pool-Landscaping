"""Hotfix #4 · Feb-2026 — Trainings designation visibility.

Tests the rule:
  * pool-only tech    → pool + universal
  * landscaping-only  → landscaping + universal
  * both              → EVERYTHING (superset rule)
  * zero designations → universal-only
  * admin / super     → everything (unchanged)

The rule lives in ``services.trainings`` — actually in
``backend.routers.training._visible_departments`` + friends. Two
kinds of coverage below:

  (1) Unit-level: exercise the helpers directly so we don't depend
      on live DB seed / auth.
  (2) HTTP-level: hit ``GET /api/training/modules`` as different
      role/department combinations and assert visibility.

Auth users seeded in ``conftest``:
  * super@aquaterra.com     · super_admin
  * mike@aquaterra.com      · technician · department=pool
  * A fresh both-designation tech is seeded per-test in Mongo.
"""
from __future__ import annotations

import os
import uuid
from pathlib import Path

import bcrypt
import pytest
import requests
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

API = "http://localhost:8001/api"
_sync = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _login(email: str, password: str = "password123") -> str:
    r = requests.post(f"{API}/auth/login",
                        json={"email": email, "password": password}, timeout=30)
    r.raise_for_status()
    return r.json()["access_token"]


def _hdrs(tok: str) -> dict:
    return {"Authorization": f"Bearer {tok}"}


def _seed_user(email: str, department: str, tenant_id: str) -> None:
    pw = bcrypt.hashpw(b"password123", bcrypt.gensalt()).decode("utf-8")
    _sync.users.update_one(
        {"email": email},
        {"$set": {
            "id": str(uuid.uuid4()),
            "name": email.split("@")[0],
            "email": email,
            "role": "technician",
            "department": department,
            "tenant_id": tenant_id,
            "password_hash": pw,
        }, "$setOnInsert": {"created_at": "seed"}},
        upsert=True,
    )


def _tenant_id_for_super() -> str:
    tok = _login("super@aquaterra.com")
    return requests.get(f"{API}/tenants/current",
                          headers=_hdrs(tok), timeout=15).json()["id"]


def _create_module(department: str, code_suffix: str, tenant_id: str) -> str:
    """Insert directly into Mongo since the /modules POST endpoint
    strictly requires a full body incl. quiz. We only need visibility."""
    mid = f"mod-hf4-{code_suffix}-{uuid.uuid4().hex[:6]}"
    _sync.training_modules.insert_one({
        "id": mid,
        "code": mid,
        "title": f"HF4 {code_suffix} module",
        "department": department,
        "tenant_id": tenant_id,
        "content_json": {},
        "quiz": {"questions": []},
        "active": True,
        "created_at": "seed",
    })
    return mid


def _list_module_ids_visible(tok: str) -> set[str]:
    """The list endpoint returns ``code`` not ``id``; our test fixtures
    intentionally use ``code == id`` so callers can treat the set as
    either."""
    r = requests.get(f"{API}/training/modules",
                       headers=_hdrs(tok), timeout=15)
    r.raise_for_status()
    return {m["code"] for m in r.json()}


# ── Session-scoped seed ─────────────────────────────────────────
@pytest.fixture(scope="module")
def seeded():
    tenant_id = _tenant_id_for_super()
    # Users
    _seed_user("hf4-tech-pool@aquaterra.com", "pool", tenant_id)
    _seed_user("hf4-tech-land@aquaterra.com", "landscaping", tenant_id)
    _seed_user("hf4-tech-both@aquaterra.com", "both", tenant_id)
    _seed_user("hf4-tech-empty@aquaterra.com", "", tenant_id)
    # Modules — one per department flavour.
    mod_pool = _create_module("pool", "pool", tenant_id)
    mod_land = _create_module("landscaping", "land", tenant_id)
    mod_both = _create_module("both", "both", tenant_id)
    yield {"tenant_id": tenant_id, "mod_pool": mod_pool,
            "mod_land": mod_land, "mod_both": mod_both}
    # Teardown
    _sync.training_modules.delete_many(
        {"id": {"$in": [mod_pool, mod_land, mod_both]}},
    )
    _sync.users.delete_many({"email": {"$regex": r"^hf4-tech-"}})


# ═════════════════════════════════════════════════════════════════
# Direct unit-level tests on the helper (no HTTP)
# ═════════════════════════════════════════════════════════════════
def test_helper_pool_only_returns_pool_plus_universal():
    from routers.training import _visible_departments
    assert set(_visible_departments({"role": "technician",
                                          "department": "pool"})) == {"pool", "both"}


def test_helper_landscaping_only_returns_landscaping_plus_universal():
    from routers.training import _visible_departments
    assert set(_visible_departments({
        "role": "technician", "department": "landscaping",
    })) == {"landscaping", "both"}


def test_helper_both_returns_none_meaning_all():
    """Superset rule — a cross-trained tech sees every training."""
    from routers.training import _visible_departments
    assert _visible_departments({"role": "technician",
                                        "department": "both"}) is None


def test_helper_zero_designations_returns_universal_only():
    from routers.training import _visible_departments
    assert _visible_departments({"role": "technician",
                                        "department": ""}) == ["both"]


def test_helper_admin_returns_none_meaning_all():
    from routers.training import _visible_departments
    assert _visible_departments({"role": "admin"}) is None
    assert _visible_departments({"role": "super_admin"}) is None


def test_helper_superset_rule_future_proof(monkeypatch):
    """If the tenant adds ``irrigation`` to its recognised set, a
    tech carrying every designation (including irrigation) still
    sees everything — no code change beyond the constant."""
    import routers.training as trn
    monkeypatch.setattr(trn, "_TENANT_DESIGNATIONS", ("pool", "landscaping", "irrigation"))
    # Fake user helper returning all three so we don't need a schema change.
    monkeypatch.setattr(trn, "_user_designations",
                          lambda u: {"pool", "landscaping", "irrigation"}
                          if u.get("email") == "cross-trained@x"
                          else set())
    assert trn._visible_departments({
        "role": "technician", "email": "cross-trained@x",
    }) is None


# ═════════════════════════════════════════════════════════════════
# HTTP-level integration tests
# ═════════════════════════════════════════════════════════════════
def test_tech_with_pool_only_sees_pool_trainings(seeded):
    tok = _login("hf4-tech-pool@aquaterra.com")
    ids = _list_module_ids_visible(tok)
    assert seeded["mod_pool"] in ids
    assert seeded["mod_both"] in ids


def test_tech_with_landscaping_only_sees_landscaping_trainings(seeded):
    tok = _login("hf4-tech-land@aquaterra.com")
    ids = _list_module_ids_visible(tok)
    assert seeded["mod_land"] in ids
    assert seeded["mod_both"] in ids


def test_tech_with_pool_only_does_not_see_landscaping_only_training(seeded):
    tok = _login("hf4-tech-pool@aquaterra.com")
    ids = _list_module_ids_visible(tok)
    assert seeded["mod_land"] not in ids


def test_tech_with_both_pool_and_landscaping_sees_all_trainings(seeded):
    """Key case — cross-trained tech gets everything."""
    tok = _login("hf4-tech-both@aquaterra.com")
    ids = _list_module_ids_visible(tok)
    assert seeded["mod_pool"] in ids
    assert seeded["mod_land"] in ids
    assert seeded["mod_both"] in ids


def test_tech_with_both_designations_sees_new_landscaping_only_training(seeded):
    """Regression guard — add a fresh landscaping-only module,
    verify the "both" tech still sees it (i.e. the "both = all"
    rule keeps working for late additions)."""
    tenant_id = seeded["tenant_id"]
    fresh = _create_module("landscaping", "fresh-land", tenant_id)
    try:
        tok = _login("hf4-tech-both@aquaterra.com")
        ids = _list_module_ids_visible(tok)
        assert fresh in ids
    finally:
        _sync.training_modules.delete_one({"id": fresh})


def test_admin_sees_all_trainings_regardless_of_designation(seeded):
    tok = _login("super@aquaterra.com")
    ids = _list_module_ids_visible(tok)
    for k in ("mod_pool", "mod_land", "mod_both"):
        assert seeded[k] in ids


def test_tech_with_zero_designations_sees_only_untagged_trainings(seeded):
    tok = _login("hf4-tech-empty@aquaterra.com")
    ids = _list_module_ids_visible(tok)
    assert seeded["mod_both"] in ids
    assert seeded["mod_pool"] not in ids
    assert seeded["mod_land"] not in ids


def test_tech_with_every_tenant_designation_sees_all_trainings_even_new_types(monkeypatch):
    """Future-proofing exercised at the helper level (see brief:
    scalar-``department`` schema can't literally represent 3
    designations, so the rule is proven by the constant + helper
    swap — same substitution pattern the code will do when
    ``designations: str[]`` lands)."""
    import routers.training as trn
    monkeypatch.setattr(trn, "_TENANT_DESIGNATIONS",
                          ("pool", "landscaping", "irrigation"))
    monkeypatch.setattr(trn, "_user_designations",
                          lambda u: {"pool", "landscaping", "irrigation"})
    assert trn._visible_departments({"role": "technician"}) is None
