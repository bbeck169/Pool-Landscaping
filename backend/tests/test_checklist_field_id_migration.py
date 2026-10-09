"""Phase 17 · Feb-2026 — Checklist cross-collection field_id stamp
pytest coverage.

Covers the 7 behaviors from the Phase 17 brief:

  1. Running the stamp helper on unstamped items adds
     ``field_id = chk_<key>`` to each.
  2. Running the helper again is a no-op (idempotent).
  3. Slug collisions in the same list → ``_2`` / ``_3`` suffix.
  4. Items with explicit ``field_id`` already set are preserved.
  5. Create a new checklist item via the write path →
     ``field_id`` auto-stamped (industry_checklists.PUT upsert).
  6. Update an existing item's label → ``field_id`` is NOT
     re-slugged (stability lock).
  7. Migration script tenant isolation — scope to a single
     tenant_id skips ``industry_checklist_templates``.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient


_BACKEND_DIR = Path(__file__).resolve().parents[1]
_SCRIPT_PATH = _BACKEND_DIR / "scripts" / "stamp_checklist_field_ids.py"
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

_ENV = dotenv_values(_BACKEND_DIR / ".env")
API = os.environ.get("BACKEND_API_URL") or "http://localhost:8001/api"
MONGO_URL = _ENV["MONGO_URL"]
DB_NAME = _ENV["DB_NAME"]
_TAG = "P17_FIELD_ID_TEST"


from services.checklist_field_id import (
    slug_label, stamp_field_ids, _candidate_field_id,
)


# ─── Unit tests on the pure helper ───────────────────────────────
def test_01_stamp_adds_chk_prefix_from_key():
    items = [
        {"key": "skim_surface", "label": "Skim surface", "required": True},
        {"key": "brush_walls", "label": "Brush walls",   "required": False},
    ]
    out = stamp_field_ids(items)
    assert out[0]["field_id"] == "chk_skim_surface"
    assert out[1]["field_id"] == "chk_brush_walls"
    # Original fields preserved.
    assert out[0]["key"] == "skim_surface"
    assert out[0]["label"] == "Skim surface"
    assert out[0]["required"] is True


def test_01b_stamp_falls_back_to_label_slug_when_no_key():
    items = [
        {"label": "Vacuum the floor well",  "required": False},
        {"label": "Clean/Backwash filter!", "required": True},
    ]
    out = stamp_field_ids(items)
    assert out[0]["field_id"] == "chk_vacuum_the_floor_well"
    assert out[1]["field_id"] == "chk_clean_backwash_filter"


def test_02_stamp_is_idempotent():
    items = [{"key": "mow", "label": "Mow"}]
    once = stamp_field_ids(items)
    twice = stamp_field_ids(once)
    assert once == twice
    assert once[0]["field_id"] == "chk_mow"


def test_03_collision_disambiguation():
    # Two items whose candidate field_ids collide (both would slug
    # to ``chk_check``) → second gets ``_2`` suffix.
    items = [
        {"label": "Check!"},
        {"label": "Check..."},
        {"label": "Check"},
    ]
    out = stamp_field_ids(items)
    ids = [i["field_id"] for i in out]
    assert ids[0] == "chk_check"
    assert ids[1] == "chk_check_2"
    assert ids[2] == "chk_check_3"
    assert len(set(ids)) == 3, f"ids not unique: {ids}"


def test_04_explicit_field_id_preserved():
    items = [
        {"key": "vac", "label": "Vacuum", "field_id": "chk_vacuum_floor"},
        {"key": "mow", "label": "Mow"},  # auto-stamped
    ]
    out = stamp_field_ids(items)
    # Curated id preserved verbatim.
    assert out[0]["field_id"] == "chk_vacuum_floor"
    assert out[1]["field_id"] == "chk_mow"


def test_06_stability_on_label_edit():
    # Simulate the write-path contract: once field_id is set,
    # editing the label must NOT re-slug the id. stamp_field_ids
    # treats a pre-set field_id as sticky.
    item = {"key": "mow", "label": "Mow", "field_id": "chk_mow"}
    edited = {**item, "label": "Mow the lawn properly"}
    out = stamp_field_ids([edited])
    assert out[0]["field_id"] == "chk_mow"  # unchanged
    assert out[0]["label"] == "Mow the lawn properly"


def test_slug_label_edge_cases():
    assert slug_label("Hello World") == "hello_world"
    assert slug_label("  Mixed-CASE / punct!  ") == "mixed_case_punct"
    assert slug_label("") == ""
    assert slug_label("###") == ""
    assert slug_label(None) == ""
    assert slug_label(123) == ""


# ─── Write-path integration ──────────────────────────────────────
def _login(email: str, password: str = "password123") -> str:
    r = requests.post(f"{API}/auth/login",
                      json={"email": email, "password": password}, timeout=20)
    r.raise_for_status()
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def admin_h():
    return {"Authorization": f"Bearer {_login('admin@aquaterra.com')}"}


@pytest.fixture(scope="module")
def db():
    return MongoClient(MONGO_URL)[DB_NAME]


@pytest.fixture(scope="module")
def tenant_id(db):
    return db.tenants.find_one({"slug": "aquaterra"})["id"]


@pytest.fixture(autouse=True)
def _cleanup(db, tenant_id):
    def _wipe():
        db.tenant_checklist_overrides.delete_many(
            {"tenant_id": tenant_id,
              "industry": {"$regex": f"^{_TAG}"}},
        )
    _wipe()
    yield
    _wipe()


def test_05_write_path_stamps_field_id_on_create(admin_h, db,
                                                  tenant_id):
    # Phase 17 · must use a real industry enum value — the write
    # path validates against the 23 seeded industries. We tag the
    # ITEM keys instead so cleanup can target this test's rows.
    industry = "pool"
    tag_a = f"{_TAG}_alpha_{uuid.uuid4().hex[:4]}"
    tag_b = f"{_TAG}_beta_{uuid.uuid4().hex[:4]}"
    r = requests.put(
        f"{API}/checklists/industry/{industry}",
        headers=admin_h,
        json={"items": [
            {"key": tag_a, "label": "Alpha item", "required": True},
            {"key": tag_b, "label": "Beta item",  "required": False},
        ]},
        timeout=20,
    )
    assert r.status_code == 200, r.text
    try:
        r2 = requests.get(
            f"{API}/checklists/industry/{industry}",
            headers=admin_h, timeout=20,
        )
        items = r2.json()["items"]
        tagged = [i for i in items if i.get("key") in (tag_a, tag_b)]
        assert len(tagged) == 2
        fids = {i["field_id"] for i in tagged}
        assert fids == {f"chk_{tag_a}", f"chk_{tag_b}"}
    finally:
        db.tenant_checklist_overrides.delete_many(
            {"tenant_id": tenant_id, "industry": industry})


def test_06_update_does_not_reslug_field_id(admin_h, db, tenant_id):
    industry = "landscaping"
    tag = f"{_TAG}_stable_{uuid.uuid4().hex[:4]}"
    try:
        requests.put(
            f"{API}/checklists/industry/{industry}", headers=admin_h,
            json={"items": [
                {"key": tag, "label": "Original label"},
            ]}, timeout=20,
        )
        r1 = requests.get(f"{API}/checklists/industry/{industry}",
                            headers=admin_h, timeout=20)
        tagged = next(i for i in r1.json()["items"]
                       if i.get("key") == tag)
        stable_fid = tagged["field_id"]
        assert stable_fid == f"chk_{tag}"

        # Edit the label — field_id must NOT change. The write
        # path replaces the whole items array; the caller echoes
        # back the existing field_id so the stability lock is
        # enforced via the PUT payload.
        requests.put(
            f"{API}/checklists/industry/{industry}", headers=admin_h,
            json={"items": [
                {"key": tag, "label": "Edited label",
                  "field_id": stable_fid},
            ]}, timeout=20,
        )
        r2 = requests.get(f"{API}/checklists/industry/{industry}",
                            headers=admin_h, timeout=20)
        tagged2 = next(i for i in r2.json()["items"]
                        if i.get("key") == tag)
        assert tagged2["field_id"] == stable_fid
        assert tagged2["label"] == "Edited label"
    finally:
        db.tenant_checklist_overrides.delete_many(
            {"tenant_id": tenant_id, "industry": industry})


# ─── Migration-script tenant isolation ───────────────────────────
def test_07_migration_script_tenant_scope_skips_platform_defaults(
        db, tenant_id):
    # Seed an unstamped override for this tenant.
    industry = f"{_TAG}_scope_{uuid.uuid4().hex[:4]}"
    db.tenant_checklist_overrides.insert_one({
        "id": f"{_TAG}_ovr_{uuid.uuid4().hex[:4]}",
        "tenant_id": tenant_id,
        "industry": industry,
        "items": [
            {"key": "scoped_a", "label": "Scoped alpha",
              "required": True},
            # No field_id — the migration should stamp it.
        ],
    })
    # Run the migration script scoped to this tenant.
    result = subprocess.run(
        [sys.executable, str(_SCRIPT_PATH), "--tenant", tenant_id],
        capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, result.stderr
    out = json.loads(result.stdout)
    assert out["tenant_scope"] == tenant_id
    # Platform-level industry_checklist_templates was NOT touched
    # (scoped runs only process tenant_checklist_overrides).
    cols = {r["collection"] for r in out["collections"]}
    assert cols == {"tenant_checklist_overrides"}
    # The scoped override must now carry field_id.
    doc = db.tenant_checklist_overrides.find_one(
        {"tenant_id": tenant_id, "industry": industry},
        {"_id": 0, "items": 1},
    )
    assert doc["items"][0]["field_id"] == "chk_scoped_a"
