"""Phase D4 · Feb 2026 — locale-aware GET endpoint + seeder idempotency.

Consolidates:
  * test_industry_endpoint_locale_query_param
  * test_industry_endpoint_locale_from_user
  * test_industry_endpoint_locale_from_accept_language
  * test_phase_d4_seeder_idempotent

into a single file to share the login fixtures + DB helper.
"""
from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest
from dotenv import dotenv_values
from pymongo import MongoClient

from tests._phase34_http_shim import http

_ENV = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
_sync = MongoClient(_ENV["MONGO_URL"])[_ENV["DB_NAME"]]


BASE_URL = (os.environ.get("REACT_APP_BACKEND_URL") or "http://localhost:8001").rstrip("/")
API = f"{BASE_URL}/api"


from tests._phase34_asyncio import batch_safe_run as _run


def _login(email: str, pw: str = "password123") -> str:
    r = http.post(f"{API}/auth/login",
                        json={"email": email, "password": pw}, timeout=30)
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def super_headers():
    return {"Authorization": f"Bearer {_login('super@aquaterra.com')}",
            "Content-Type": "application/json"}


@pytest.fixture(scope="module", autouse=True)
def ensure_phase_d4_seed_ran():
    """Run the D4 seeder once so the endpoint tests see translated
    rows. ``force=True`` re-writes rows without duplicating them."""
    from services.migrations.seed_phase_d4_checklist_row_translations import (
        run_phase_d4_row_translation_seed,
    )
    _run(run_phase_d4_row_translation_seed(force=True))
    yield


@pytest.fixture(scope="module", autouse=True)
def _sprint3a_snapshot_tenant_hvac_overrides():
    """Sprint 3a · Feb 2026 — snapshot + strip aquaterra's stale
    ``tenant_checklist_overrides`` for ``hvac`` so the endpoint
    resolver falls through to the DEFAULT template (which the D4
    seeder populated with ``label_i18n.{es,fr}``).

    Root cause: the endpoint checks ``tenant_checklist_overrides``
    BEFORE ``industry_checklist_templates``. A prior test run left
    an override row on aquaterra whose ``items`` lack any
    ``label_i18n`` field — so the endpoint returned English regardless
    of ``?locale=es``. This fixture snapshots the row, deletes it for
    the duration of the test module, and restores it at teardown so
    downstream tests aren't affected. Applies to every super-admin
    tenant slug the tests hit (currently aquaterra only)."""
    tenant = _sync.tenants.find_one({"slug": "aquaterra"}, {"_id": 0, "id": 1})
    if not tenant:
        yield
        return
    tid = tenant["id"]
    snapshots = list(_sync.tenant_checklist_overrides.find(
        {"tenant_id": tid, "industry": {"$in": ["hvac"]}},
        {"_id": 0},
    ))
    _sync.tenant_checklist_overrides.delete_many(
        {"tenant_id": tid, "industry": {"$in": ["hvac"]}},
    )
    try:
        yield
    finally:
        # Restore whatever we snapshotted so downstream tests / real
        # tenant state are untouched.
        for snap in snapshots:
            _sync.tenant_checklist_overrides.replace_one(
                {"tenant_id": snap["tenant_id"], "industry": snap["industry"]},
                snap, upsert=True,
            )


# ─────────────────────── endpoint · query param ─────────────────────
def test_endpoint_locale_query_param_returns_spanish(super_headers):
    r = http.get(f"{API}/checklists/industry/hvac?locale=es",
                     headers=super_headers, timeout=30)
    assert r.status_code == 200
    body = r.json()
    assert body["locale"] == "es"
    # First row is the required "Replaced air filter" — Spanish.
    row = next(i for i in body["items"] if i["key"] == "replaced_air_filter")
    assert row["label"] == "Filtro de aire reemplazado"
    assert row["label_en"] == "Replaced air filter"
    assert "es" in row["label_i18n_available"]
    assert "en" in row["label_i18n_available"]


def test_endpoint_locale_query_param_returns_french(super_headers):
    r = http.get(f"{API}/checklists/industry/hvac?locale=fr",
                     headers=super_headers, timeout=30)
    assert r.status_code == 200
    body = r.json()
    assert body["locale"] == "fr"
    row = next(i for i in body["items"] if i["key"] == "replaced_air_filter")
    assert row["label"] == "Filtre à air remplacé"


def test_endpoint_default_locale_returns_english(super_headers):
    r = http.get(f"{API}/checklists/industry/hvac",
                     headers=super_headers, timeout=30)
    body = r.json()
    row = next(i for i in body["items"] if i["key"] == "replaced_air_filter")
    assert row["label"] == "Replaced air filter"
    assert row["label_en"] == "Replaced air filter"


def test_endpoint_unknown_locale_falls_through_to_en(super_headers):
    r = http.get(f"{API}/checklists/industry/hvac?locale=de",
                     headers=super_headers, timeout=30)
    assert r.status_code == 200
    body = r.json()
    # Unknown ``de`` → validates against pattern still (regex allows
    # 2-10 letters/hyphens), then collapses to ``en`` in the resolver.
    assert body["locale"] == "en"


# ─────────────────────── endpoint · user record ─────────────────────
def test_endpoint_locale_from_user_record():
    """User with ``locale=fr`` in DB gets French rows without a
    ``?locale`` query param."""
    email = "d4-fr-user@example.com"
    pw = "password123"
    tenant = _sync.tenants.find_one({"slug": "aquaterra"}, {"_id": 0, "id": 1})
    _sync.users.delete_many({"email": email})
    import bcrypt
    hashed = bcrypt.hashpw(pw.encode(), bcrypt.gensalt()).decode()
    _sync.users.insert_one({
        "id": "d4-fr-uid", "tenant_id": tenant["id"], "email": email,
        "role": "admin", "locale": "fr",
        "password_hash": hashed,
    })
    try:
        token = _login(email, pw)
        headers = {"Authorization": f"Bearer {token}",
                    "Content-Type": "application/json"}
        r = http.get(f"{API}/checklists/industry/hvac", headers=headers,
                          timeout=30)
        assert r.status_code == 200
        body = r.json()
        assert body["locale"] == "fr"
        row = next(i for i in body["items"] if i["key"] == "replaced_air_filter")
        assert row["label"] == "Filtre à air remplacé"
    finally:
        _sync.users.delete_many({"email": email})


# ─────────────────── endpoint · Accept-Language header ──────────────
def test_endpoint_locale_from_accept_language_header(super_headers):
    hdr = dict(super_headers)
    hdr["Accept-Language"] = "es-419,es;q=0.9,en;q=0.5"
    r = http.get(f"{API}/checklists/industry/hvac", headers=hdr,
                     timeout=30)
    body = r.json()
    # No ``?locale`` + super user has no ``locale`` field set →
    # Accept-Language kicks in.
    assert body["locale"] == "es"
    row = next(i for i in body["items"] if i["key"] == "replaced_air_filter")
    assert row["label"] == "Filtro de aire reemplazado"


def test_endpoint_query_param_beats_accept_language(super_headers):
    hdr = dict(super_headers)
    hdr["Accept-Language"] = "es-419"
    r = http.get(f"{API}/checklists/industry/hvac?locale=fr",
                     headers=hdr, timeout=30)
    assert r.json()["locale"] == "fr"


# ────────────────────────── seeder · idempotency ────────────────────
def test_seeder_is_idempotent_and_populates_every_row():
    """Second run must not write; every seeded row across all 23
    industries has non-empty ``label_i18n.es`` AND ``label_i18n.fr``."""
    from services.migrations.seed_phase_d4_checklist_row_translations import (
        run_phase_d4_row_translation_seed,
    )
    # Fresh run after the autouse fixture already primed things.
    second = _run(run_phase_d4_row_translation_seed(force=True))
    # ``force=True`` re-visits every doc; ``rows_updated`` counts only
    # rows where an actual write happened (empty target). Since the
    # autouse fixture already populated everything, this run should
    # write ZERO rows.
    assert second["rows_updated"] == 0, (
        f"idempotency broken — second run wrote {second['rows_updated']} rows"
    )
    # Assert every default row across every industry has both.
    docs = _run(_sync_find_all_defaults())
    for doc in docs:
        industry = doc["industry"]
        for row in doc["items"]:
            i18n = row.get("label_i18n") or {}
            key = row["key"]
            assert isinstance(i18n.get("es"), str) and i18n["es"].strip(), (
                f"{industry}.{key} missing es translation"
            )
            assert isinstance(i18n.get("fr"), str) and i18n["fr"].strip(), (
                f"{industry}.{key} missing fr translation"
            )


def test_seeder_does_not_overwrite_translator_edits():
    """If a translator has already edited a row (non-empty value),
    the seeder MUST leave that value alone."""
    from services.migrations.seed_phase_d4_checklist_row_translations import (
        run_phase_d4_row_translation_seed,
    )
    industry = "hvac"
    key = "replaced_air_filter"
    edited = "TRANSLATOR-EDITED-STRING"
    # Poke a fake translator-edited value.
    _sync.industry_checklist_templates.update_one(
        {"industry": industry, "is_default": True, "items.key": key},
        {"$set": {"items.$.label_i18n": {"es": edited, "fr": edited}}},
    )
    _run(run_phase_d4_row_translation_seed(force=True))
    doc = _sync.industry_checklist_templates.find_one(
        {"industry": industry, "is_default": True}, {"_id": 0, "items": 1},
    )
    row = next(i for i in doc["items"] if i["key"] == key)
    assert row["label_i18n"]["es"] == edited
    assert row["label_i18n"]["fr"] == edited
    # Restore the canonical value for downstream tests.
    from services.checklist_row_translations import ROW_TRANSLATIONS
    canonical = ROW_TRANSLATIONS[(industry, key)]
    _sync.industry_checklist_templates.update_one(
        {"industry": industry, "is_default": True, "items.key": key},
        {"$set": {"items.$.label_i18n": canonical}},
    )


async def _sync_find_all_defaults():
    from config import db as _db
    return await _db.industry_checklist_templates.find(
        {"is_default": True}, {"_id": 0, "industry": 1, "items": 1},
    ).to_list(200)
