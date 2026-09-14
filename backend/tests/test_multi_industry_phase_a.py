"""Phase Feb-2026 · Multi-industry Phase A — enum, tenant field,
migration, and endpoint contract tests.
"""
from __future__ import annotations

import os
import re
import uuid
from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient

from services.industries import (
    DEFAULT_INDUSTRY,
    INDUSTRIES,
    INDUSTRY_LABELS,
    is_valid_industry,
    normalize_industries,
    tenant_has_industry,
)
from services.migrations.tenant_industries_backfill import (
    backfill_tenant_industries,
)


_ENV = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
_sync = MongoClient(_ENV["MONGO_URL"])[_ENV["DB_NAME"]]

_FE_ENV = dotenv_values(Path(__file__).resolve().parents[2] / "frontend" / ".env")
BASE = (_FE_ENV.get("REACT_APP_BACKEND_URL")
        or os.environ.get("REACT_APP_BACKEND_URL", "")).rstrip("/")
assert BASE
API = f"{BASE}/api"


def _login(email, password="password123"):
    r = requests.post(f"{API}/auth/login",
                       json={"email": email, "password": password},
                       timeout=15)
    r.raise_for_status()
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture(scope="module")
def h_admin():
    return _login("admin@aquaterra.com")


@pytest.fixture(scope="module")
def h_customer():
    return _login("customer@aquaterra.com")


@pytest.fixture(scope="module")
def anyio_backend() -> str:
    return "asyncio"


# ═══════════════════════ enum contract ═══════════════════════════════
class TestEnumContract:
    def test_expected_25_industries(self):
        assert len(INDUSTRIES) == 25

    def test_first_industry_is_pools(self):
        # Historical single-industry default → seed target for the
        # boot migration.  If this changes, update DEFAULT_INDUSTRY
        # AND memory/FEATURE_MULTI_INDUSTRY_PHASE_A.md.
        assert INDUSTRIES[0] == "pools"
        assert DEFAULT_INDUSTRY == "pools"

    def test_every_slug_has_a_label(self):
        assert set(INDUSTRY_LABELS.keys()) == set(INDUSTRIES)

    def test_slug_shape_lowercase_underscore(self):
        for slug in INDUSTRIES:
            assert re.fullmatch(r"[a-z0-9_]+", slug), slug

    def test_no_duplicates(self):
        assert len(set(INDUSTRIES)) == len(INDUSTRIES)

    def test_frontend_module_parity(self):
        """Backend + frontend enums MUST stay byte-parallel. This
        parses the JS module and diff-checks the slug list."""
        js_path = Path(__file__).resolve().parents[2] / \
            "frontend" / "src" / "config" / "industries.js"
        text = js_path.read_text()
        m = re.search(r"export const INDUSTRIES\s*=\s*Object\.freeze\(\[(.*?)\]\)",
                      text, flags=re.DOTALL)
        assert m, "Could not parse INDUSTRIES from JS module"
        slugs = re.findall(r'"([a-z0-9_]+)"', m.group(1))
        assert slugs == list(INDUSTRIES)


class TestHelpers:
    def test_is_valid_industry(self):
        assert is_valid_industry("pools")
        assert not is_valid_industry("unknown")
        assert not is_valid_industry("")
        assert not is_valid_industry(None)

    def test_normalize_industries_splits_valid_invalid(self):
        valid, invalid = normalize_industries(
            ["pools", "  landscaping ", "bogus", "pools", "", None, "hvac"],
        )
        # Duplicates + falsy stripped, invalid isolated, valid preserved
        # in input order.
        assert valid == ["pools", "landscaping", "hvac"]
        assert invalid == ["bogus"]

    def test_tenant_has_industry(self):
        assert tenant_has_industry({"industries": ["pools", "hvac"]}, "pools")
        assert not tenant_has_industry({"industries": ["pools"]}, "hvac")
        assert not tenant_has_industry({}, "pools")
        assert not tenant_has_industry(None, "pools")
        assert not tenant_has_industry({"industries": "not-a-list"}, "pools")


# ═══════════════════════ migration ═══════════════════════════════════
class TestMigration:
    @pytest.mark.anyio
    async def test_seeds_missing_and_is_idempotent(self):
        # Fresh motor client bound to the test loop.
        from motor.motor_asyncio import AsyncIOMotorClient
        cli = AsyncIOMotorClient(_ENV["MONGO_URL"])
        d = cli[_ENV["DB_NAME"]]
        try:
            tid1 = f"TEST_mi-a-{uuid.uuid4().hex[:8]}"
            tid2 = f"TEST_mi-b-{uuid.uuid4().hex[:8]}"
            await d.tenants.insert_many([
                {"id": tid1, "name": f"TEST_mi_a_{tid1[-6:]}",
                 "slug": tid1},
                {"id": tid2, "name": f"TEST_mi_b_{tid2[-6:]}",
                 "slug": tid2,
                 # Legacy hint that maps to the enum → should win
                 # over the default.
                 "industry": "hvac"},
            ])
            try:
                # First pass — both rows are backfilled.
                # Reach into the migration through the app's motor
                # handle (config.db is the process-wide client).
                res1 = await backfill_tenant_industries()
                assert res1["backfilled"] >= 2
                assert res1["inferred_from_legacy"] >= 1

                row_a = await d.tenants.find_one({"id": tid1}, {"_id": 0})
                row_b = await d.tenants.find_one({"id": tid2}, {"_id": 0})
                assert row_a["industries"] == ["pools"]
                assert row_b["industries"] == ["hvac"]

                # Second pass — should touch nothing.
                res2 = await backfill_tenant_industries()
                assert res2["backfilled"] == 0
            finally:
                await d.tenants.delete_many({"id": {"$in": [tid1, tid2]}})
        finally:
            cli.close()


# ═══════════════════════ endpoint contract ═══════════════════════════
class TestEndpointContract:
    def test_current_returns_industries(self, h_admin):
        r = requests.get(f"{API}/tenants/current", headers=h_admin, timeout=15)
        assert r.status_code == 200
        body = r.json()
        assert "industries" in body
        assert isinstance(body["industries"], list)
        assert "pools" in body["industries"]  # seeded by boot migration

    def test_settings_read_includes_industries(self, h_admin):
        r = requests.get(f"{API}/tenants/mine/settings",
                          headers=h_admin, timeout=15)
        assert r.status_code == 200
        body = r.json()
        assert isinstance(body.get("industries"), list)

    def test_patch_accepts_and_persists_industries(self, h_admin):
        # Save + restore the current value so this test doesn't
        # affect siblings.
        r0 = requests.get(f"{API}/tenants/current", headers=h_admin, timeout=15)
        original = r0.json().get("industries") or ["pools"]
        try:
            p = requests.patch(
                f"{API}/tenants/mine/settings",
                headers=h_admin,
                json={"industries": ["pools", "landscaping", "hvac"]},
                timeout=15,
            )
            assert p.status_code == 200, p.text
            r1 = requests.get(f"{API}/tenants/current",
                                headers=h_admin, timeout=15)
            assert r1.json()["industries"] == ["pools", "landscaping", "hvac"]
        finally:
            requests.patch(
                f"{API}/tenants/mine/settings",
                headers=h_admin,
                json={"industries": original}, timeout=15,
            )

    def test_patch_rejects_invalid_slug_422(self, h_admin):
        r = requests.patch(
            f"{API}/tenants/mine/settings",
            headers=h_admin,
            json={"industries": ["pools", "bogus_industry"]},
            timeout=15,
        )
        assert r.status_code == 422, r.text
        assert "invalid_industry" in r.text
        assert "bogus_industry" in r.text

    def test_patch_rejects_non_list_422(self, h_admin):
        r = requests.patch(
            f"{API}/tenants/mine/settings",
            headers=h_admin,
            json={"industries": "pools"},   # string, not list
            timeout=15,
        )
        # Pydantic type coercion → 422 unprocessable.
        assert r.status_code == 422

    def test_non_admin_cannot_patch(self, h_customer):
        r = requests.patch(
            f"{API}/tenants/mine/settings",
            headers=h_customer,
            json={"industries": ["pools"]},
            timeout=15,
        )
        assert r.status_code == 403
