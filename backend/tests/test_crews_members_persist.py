"""Feb-2026 · P0 · Crew members persistence regression.

Root cause captured in the failing legacy repro:
``frontend/src/pages/ops/OpsHub.jsx::save`` used a raw ``fetch(PATCH)``
that doesn't throw on 4xx/5xx, so any server-side rejection produced
a false "Saved" toast while ``tech_ids`` never landed. Backend was
already correct (routers/ops.py PATCH ``/crews/{cid}`` writes the
whole body under ``$set``). This suite is a backend-only regression
guard against a future backend drift removing members on write.
"""
from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4

import pytest
import requests
from pymongo import MongoClient


BASE_URL = ""
for ln in Path("/app/frontend/.env").read_text().splitlines():
    if ln.startswith("REACT_APP_BACKEND_URL="):
        BASE_URL = ln.split("=", 1)[1].strip().strip('"').rstrip("/")
        break
API = f"{BASE_URL}/api"

SUPER = {"email": "super@aquaterra.com", "password": "password123"}
AQUATERRA_TID = "3814833a-dd0d-4bd9-90ea-351c24924649"

TECH1 = "0886e77c-11ca-43bb-9577-dd6edab44bcd"   # Mike Rivera
TECH2 = "af475a29-32c1-4871-860c-065422144a00"   # Sara Nguyen


def _read_env(k: str) -> str:
    for ln in Path("/app/backend/.env").read_text().splitlines():
        if ln.startswith(f"{k}="):
            return ln.split("=", 1)[1].strip().strip('"')
    return ""


@pytest.fixture(scope="module")
def sync_db():
    cli = MongoClient(_read_env("MONGO_URL"), serverSelectionTimeoutMS=5000)
    try:
        yield cli[_read_env("DB_NAME") or "aquaterra"]
    finally:
        cli.close()


@pytest.fixture(scope="module")
def tok() -> str:
    r = requests.post(f"{API}/auth/login", json=SUPER, timeout=30)
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _h(t: str) -> dict:
    return {"Authorization": f"Bearer {t}", "Content-Type": "application/json"}


def test_create_crew_with_members_round_trips(tok, sync_db):
    r = requests.post(
        f"{API}/crews",
        headers=_h(tok),
        json={"name": f"regr-{uuid4().hex[:6]}", "color": "#DB2777",
                "tech_ids": [TECH1]},
        timeout=30,
    )
    assert r.status_code == 200, r.text
    cid = r.json()["id"]
    try:
        # tenant_id written on insert (prior P0 fix)
        row = sync_db.crews.find_one({"id": cid})
        assert row is not None
        assert row.get("tenant_id") == AQUATERRA_TID
        assert row.get("tech_ids") == [TECH1]

        listed = requests.get(f"{API}/crews", headers=_h(tok), timeout=30).json()
        me = next(c for c in listed if c["id"] == cid)
        assert me.get("tech_ids") == [TECH1]
        # ops.list_crews resolves ``members[]`` from ``users`` — we
        # verify the join succeeded end-to-end, not just the id storage.
        assert any(m.get("name") == "Mike Rivera" for m in me.get("members", []))
    finally:
        requests.delete(f"{API}/crews/{cid}", headers=_h(tok), timeout=30)


def test_patch_updates_members_set(tok, sync_db):
    r = requests.post(
        f"{API}/crews", headers=_h(tok),
        json={"name": f"regr-{uuid4().hex[:6]}", "color": "#0284C7",
                "tech_ids": [TECH1]}, timeout=30,
    )
    cid = r.json()["id"]
    try:
        r = requests.patch(
            f"{API}/crews/{cid}", headers=_h(tok),
            json={"name": r.json()["name"], "color": "#0284C7",
                    "tech_ids": [TECH1, TECH2]}, timeout=30,
        )
        assert r.status_code == 200, r.text
        assert set(r.json()["tech_ids"]) == {TECH1, TECH2}
        row = sync_db.crews.find_one({"id": cid})
        assert set(row.get("tech_ids") or []) == {TECH1, TECH2}
    finally:
        requests.delete(f"{API}/crews/{cid}", headers=_h(tok), timeout=30)


def test_patch_empty_array_clears_members(tok, sync_db):
    r = requests.post(
        f"{API}/crews", headers=_h(tok),
        json={"name": f"regr-{uuid4().hex[:6]}", "color": "#059669",
                "tech_ids": [TECH1, TECH2]}, timeout=30,
    )
    cid = r.json()["id"]
    try:
        r = requests.patch(
            f"{API}/crews/{cid}", headers=_h(tok),
            json={"tech_ids": []}, timeout=30,
        )
        assert r.status_code == 200, r.text
        assert r.json().get("tech_ids") == []
        row = sync_db.crews.find_one({"id": cid})
        assert row.get("tech_ids") == []
    finally:
        requests.delete(f"{API}/crews/{cid}", headers=_h(tok), timeout=30)


def test_color_field_round_trips(tok, sync_db):
    """The color-picker enhancement rides on the existing ``color``
    field in ``CrewIn``. Regression guard that the field persists
    end-to-end (create + patch)."""
    r = requests.post(
        f"{API}/crews", headers=_h(tok),
        json={"name": f"regr-{uuid4().hex[:6]}", "color": "#7C3AED",
                "tech_ids": []}, timeout=30,
    )
    cid = r.json()["id"]
    try:
        assert r.json().get("color") == "#7C3AED"
        r = requests.patch(f"{API}/crews/{cid}", headers=_h(tok),
                            json={"color": "#16A34A"}, timeout=30)
        assert r.json().get("color") == "#16A34A"
        row = sync_db.crews.find_one({"id": cid})
        assert row.get("color") == "#16A34A"
    finally:
        requests.delete(f"{API}/crews/{cid}", headers=_h(tok), timeout=30)
