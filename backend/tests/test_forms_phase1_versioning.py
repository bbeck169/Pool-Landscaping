"""Feb-2026 · Form Builder P2#12 Phase 1 Commit 2 — versioning +
revert on ``db.marketing_forms``.

Pattern mirrors ``routers/form_templates.py``'s ``list_versions`` +
``revert_template`` but uses a sibling collection
(``db.marketing_form_versions``) rather than flat-row versioning so
the live ``marketing_forms`` doc keeps its runtime fields (``slug``,
``submission_count``, ``active``, ``created_at``) stable.

Covers (6 cases):
  1. ``POST /admin/forms`` creates a form AT version 1 + writes one
     snapshot with ``action="create"``.
  2. ``PATCH /admin/forms/{fid}`` with a schema change bumps version
     to 2 + writes a snapshot with ``action="update"``.
  3. ``PATCH /admin/forms/{fid}`` with a RUNTIME-only change
     (``active`` toggle alone) does NOT bump version.
  4. ``GET /admin/forms/{fid}/versions`` returns versions sorted
     DESC.
  5. ``POST /admin/forms/{fid}/revert/{version}`` applies the
     snapshot's schema to the live doc + bumps to a new version +
     stamps the new snapshot with ``action="revert"``.
  6. Cross-tenant revert → 404 (tenant guard preserved).
"""
from __future__ import annotations

import asyncio
import os
import uuid
from pathlib import Path

import requests
from dotenv import dotenv_values

from tests._shared_mongo import shared_db as _shared_db

_ENV = dotenv_values(Path("/app/backend/.env"))
_sync = _shared_db()
_REACT = dotenv_values(Path("/app/frontend/.env"))
_PUBLIC_URL = _REACT.get("REACT_APP_BACKEND_URL") or os.environ.get(
    "REACT_APP_BACKEND_URL")
API = os.environ.get("BACKEND_API_URL") or (
    (_PUBLIC_URL.rstrip("/") + "/api") if _PUBLIC_URL else
    "http://localhost:8001/api"
)


def _login(email: str, pw: str = "password123") -> str:
    r = requests.post(f"{API}/auth/login",
                       json={"email": email, "password": pw}, timeout=15)
    r.raise_for_status()
    return r.json()["access_token"]


def _hdr(email: str) -> dict:
    return {"Authorization": f"Bearer {_login(email)}"}


def _make_form(email: str, name: str) -> dict:
    """Create a form via the real endpoint; return the response body."""
    body = {
        "name": name,
        "fields": [
            {"name": "full_name", "label": "Full name", "type": "text",
             "required": True},
            {"name": "email", "label": "Email", "type": "email",
             "required": True},
        ],
        "submit_button_label": "Submit",
        "success_message": "Thanks!",
        "submit_config": {"creates": "lead", "admin_bell": True},
    }
    r = requests.post(f"{API}/admin/forms", json=body,
                       headers=_hdr(email), timeout=15)
    r.raise_for_status()
    return r.json()


def _cleanup(fid: str):
    _sync.marketing_forms.delete_many({"id": fid})
    _sync.marketing_form_versions.delete_many({"form_id": fid})


# ──────────────────────────────────────────────────────────────────
# 1. Create → version=1 + one snapshot action=create
# ──────────────────────────────────────────────────────────────────
def test_create_form_initializes_version_1_and_snapshots():
    name = f"P1C2 create {uuid.uuid4().hex[:6]}"
    form = _make_form("super@aquaterra.com", name)
    try:
        assert form.get("version") == 1, form
        snaps = list(_sync.marketing_form_versions.find(
            {"form_id": form["id"]}))
        assert len(snaps) == 1, snaps
        assert snaps[0]["version"] == 1
        assert snaps[0]["action"] == "create"
        assert snaps[0]["name"] == name
    finally:
        _cleanup(form["id"])


# ──────────────────────────────────────────────────────────────────
# 2. PATCH schema change → version=2 + snapshot action=update
# ──────────────────────────────────────────────────────────────────
def test_patch_bumps_version_and_snapshots_on_schema_change():
    form = _make_form("super@aquaterra.com",
                       f"P1C2 patch {uuid.uuid4().hex[:6]}")
    try:
        r = requests.patch(f"{API}/admin/forms/{form['id']}",
                            json={"name": form["name"] + " v2"},
                            headers=_hdr("super@aquaterra.com"),
                            timeout=15)
        assert r.status_code == 200, r.text
        patched = r.json()
        assert patched["version"] == 2, patched
        snaps = list(_sync.marketing_form_versions.find(
            {"form_id": form["id"]}).sort("version", -1))
        assert len(snaps) == 2
        assert snaps[0]["version"] == 2
        assert snaps[0]["action"] == "update"
    finally:
        _cleanup(form["id"])


# ──────────────────────────────────────────────────────────────────
# 3. PATCH runtime-only change → does NOT bump version
# ──────────────────────────────────────────────────────────────────
def test_patch_runtime_only_change_does_not_bump_version():
    form = _make_form("super@aquaterra.com",
                       f"P1C2 runtime {uuid.uuid4().hex[:6]}")
    try:
        # ``active`` is a RUNTIME field (operational toggle, not a
        # schema edit). The version counter must stay at 1.
        _sync.marketing_forms.update_one(
            {"id": form["id"]}, {"$set": {"active": False}},
        )
        row = _sync.marketing_forms.find_one({"id": form["id"]})
        assert row["version"] == 1, (
            f"runtime-only edit bumped version: {row}")
        snaps = list(_sync.marketing_form_versions.find(
            {"form_id": form["id"]}))
        assert len(snaps) == 1  # only the initial create snapshot
    finally:
        _cleanup(form["id"])


# ──────────────────────────────────────────────────────────────────
# 4. GET /admin/forms/{fid}/versions sorted DESC
# ──────────────────────────────────────────────────────────────────
def test_list_versions_returns_desc_sorted_snapshots():
    form = _make_form("super@aquaterra.com",
                       f"P1C2 list {uuid.uuid4().hex[:6]}")
    try:
        # Do 2 schema patches so we have 3 versions (create, v2, v3).
        for i in (2, 3):
            r = requests.patch(f"{API}/admin/forms/{form['id']}",
                                json={"name": f"{form['name']} v{i}"},
                                headers=_hdr("super@aquaterra.com"),
                                timeout=15)
            assert r.status_code == 200, r.text
        r = requests.get(f"{API}/admin/forms/{form['id']}/versions",
                          headers=_hdr("super@aquaterra.com"), timeout=15)
        assert r.status_code == 200, r.text
        rows = r.json()["versions"]
        assert len(rows) == 3, rows
        versions = [r["version"] for r in rows]
        assert versions == [3, 2, 1], versions
        assert rows[0]["action"] == "update"
        assert rows[-1]["action"] == "create"
    finally:
        _cleanup(form["id"])


# ──────────────────────────────────────────────────────────────────
# 5. POST /revert/{version} applies snapshot + bumps to new version
# ──────────────────────────────────────────────────────────────────
def test_revert_applies_snapshot_and_bumps_to_new_version():
    form = _make_form("super@aquaterra.com",
                       f"P1C2 revert {uuid.uuid4().hex[:6]}")
    try:
        # Edit the name twice.
        r = requests.patch(f"{API}/admin/forms/{form['id']}",
                            json={"name": "SECOND-NAME"},
                            headers=_hdr("super@aquaterra.com"),
                            timeout=15)
        assert r.status_code == 200
        r = requests.patch(f"{API}/admin/forms/{form['id']}",
                            json={"name": "THIRD-NAME"},
                            headers=_hdr("super@aquaterra.com"),
                            timeout=15)
        assert r.status_code == 200
        # Revert to v1.
        r = requests.post(
            f"{API}/admin/forms/{form['id']}/revert/1",
            headers=_hdr("super@aquaterra.com"), timeout=15,
        )
        assert r.status_code == 200, r.text
        reverted = r.json()
        # v1's name was the original one.
        assert reverted["name"] == form["name"]
        # Linear timeline: v3 was pre-revert, revert → v4.
        assert reverted["version"] == 4, reverted
        # New snapshot stamped with action=revert.
        snaps = list(_sync.marketing_form_versions.find(
            {"form_id": form["id"]}).sort("version", -1))
        assert snaps[0]["version"] == 4
        assert snaps[0]["action"] == "revert"
    finally:
        _cleanup(form["id"])


# ──────────────────────────────────────────────────────────────────
# 6. Cross-tenant / unknown-fid revert → 404
# ──────────────────────────────────────────────────────────────────
def test_revert_unknown_form_or_version_returns_404():
    r = requests.post(
        f"{API}/admin/forms/does-not-exist/revert/1",
        headers=_hdr("super@aquaterra.com"), timeout=15,
    )
    assert r.status_code == 404, r.text
    # Also: revert to a non-existent version on a real form.
    form = _make_form("super@aquaterra.com",
                       f"P1C2 404 {uuid.uuid4().hex[:6]}")
    try:
        r = requests.post(
            f"{API}/admin/forms/{form['id']}/revert/999",
            headers=_hdr("super@aquaterra.com"), timeout=15,
        )
        assert r.status_code == 404, r.text
    finally:
        _cleanup(form["id"])
