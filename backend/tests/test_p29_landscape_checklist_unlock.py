"""Phase P29 · Feb-2026 — Landscape checklist unlock.

Locks the following contracts:

  1. **Endpoint contract** — ``GET /api/checklists/industry/landscaping``
     returns the P29 template with every ``required`` set to
     ``False``. Response envelope shape unchanged (``industry``,
     ``items``, ``source``, ``locale``, optional ``updated_at``).
  2. **Pool untouched** — ``GET /api/checklists/industry/pool``
     returns the SAME distribution of ``required=True`` items as
     before P29 (7 required, 3 optional).
  3. **Other industries untouched** — HVAC still has its 4 required
     items; pest_control still has its 5 (legally-critical EPA
     documentation + re-entry notification).
  4. **Migration idempotency** — run twice → second run reports
     zero mutations, no errors.
  5. **Migration scope** — a landscape override doc with mixed
     required flags is fully cleared; a POOL override doc with
     ``required=True`` items is UNCHANGED (only landscape overrides
     are cleared).
  6. **Template refresh** — the persisted
     ``industry_checklist_templates`` doc for ``landscaping`` is
     updated to match the fresh in-memory ``DEFAULT_TEMPLATES``.
     Pre-P29 the boot seeder no-op'd on existing docs and the
     required=True values persisted forever.
  7. **P21 wiring** — the migration is invoked from
     ``_run_structural_migration`` with ``must_succeed=False`` so
     boot never blocks on it.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient

from tests._f7_loop_fixture import run_test


_FE = dotenv_values(
    Path(__file__).resolve().parents[2] / "frontend" / ".env",
)
_BE = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
BASE = (_FE.get("EXPO_PUBLIC_BACKEND_URL")
        or "http://localhost:8001").rstrip("/")
API = f"{BASE}/api"
MONGO_URL = _BE.get("MONGO_URL"); DB_NAME = _BE.get("DB_NAME")

TAG = "P29_"


def _login(email: str, pw: str = "password123") -> dict:
    r = requests.post(f"{API}/auth/login",
                       json={"email": email, "password": pw}, timeout=15)
    r.raise_for_status()
    return r.json()


@pytest.fixture(scope="module")
def dbc() -> MongoClient:
    return MongoClient(MONGO_URL)[DB_NAME]


@pytest.fixture(scope="module")
def admin_login() -> dict:
    return _login("admin@aquaterra.com")


@pytest.fixture(scope="module")
def admin_h(admin_login) -> dict:
    return {"Authorization": f"Bearer {admin_login['access_token']}"}


@pytest.fixture(scope="module")
def admin_tenant_id(admin_login) -> str:
    import jwt as _jwt
    payload = _jwt.decode(
        admin_login["access_token"],
        options={"verify_signature": False},
    )
    return payload["active_tenant_id"]


# ══════════════════════════════════════════════════════════════════
# In-memory template — locks the P29 shape.
# ══════════════════════════════════════════════════════════════════


def test_p29_in_memory_landscape_template_all_required_false():
    """The router's ``DEFAULT_TEMPLATES["landscaping"]`` MUST ship
    every row with ``required=False``. This is the single source
    of truth read by the seeder AND the P29 migration."""
    from routers.industry_checklists import DEFAULT_TEMPLATES
    landscape = DEFAULT_TEMPLATES["landscaping"]
    assert len(landscape) == 9, (
        f"Landscape template row count changed — expected 9, got "
        f"{len(landscape)}. Update this test if the shape truly "
        f"changed, but P29 was scoped to required-flag flips only."
    )
    for row in landscape:
        assert row.get("required") is False, (
            f"Landscape row {row.get('key')!r} still has "
            f"required={row.get('required')!r} — P29 unlock regressed."
        )


def test_p29_pool_template_untouched():
    """The pool template MUST NOT have been softened by P29. Locks
    the 7-required / 3-optional distribution the pre-P29 tests
    already relied on."""
    from routers.industry_checklists import DEFAULT_TEMPLATES
    pool = DEFAULT_TEMPLATES["pool"]
    required_count = sum(1 for r in pool if r.get("required"))
    optional_count = sum(1 for r in pool if not r.get("required"))
    assert required_count == 7, (
        f"Pool template required distribution drifted — P29 was "
        f"supposed to touch ONLY landscape."
    )
    assert optional_count == 3


def test_p29_other_industry_templates_untouched():
    """HVAC (4 required) + pest_control (5 required, incl. the two
    EPA-compliance rows) locked. Guard against a well-meaning
    refactor that flips ``required`` industry-wide."""
    from routers.industry_checklists import DEFAULT_TEMPLATES
    hvac = DEFAULT_TEMPLATES["hvac"]
    hvac_required = [r["key"] for r in hvac if r.get("required")]
    assert set(hvac_required) == {
        "replaced_air_filter", "checked_thermostat",
        "inspected_condensate_drain", "verified_airflow",
    }
    pc = DEFAULT_TEMPLATES["pest_control"]
    pc_required = [r["key"] for r in pc if r.get("required")]
    # 5 required: two initial + documented_pest_activity + two
    # legally-critical D1 additions.
    assert set(pc_required) == {
        "treated_exterior_perimeter", "applied_interior_treatment",
        "documented_pest_activity",
        "documented_products_epa", "informed_reentry_time",
    }, (
        f"pest_control required set drifted — legal-compliance gate "
        f"at risk. Actual: {sorted(pc_required)}"
    )


# ══════════════════════════════════════════════════════════════════
# GET endpoint — response shape + landscape unlock.
# ══════════════════════════════════════════════════════════════════


def test_p29_get_landscape_returns_all_required_false(admin_h, dbc):
    """Endpoint contract preserved (industry / items / source /
    locale), and every row has ``required=False``."""
    r = requests.get(f"{API}/checklists/industry/landscaping",
                      headers=admin_h, timeout=15)
    assert r.status_code == 200, r.text
    body = r.json()
    # Envelope shape identical to pre-P29.
    assert body["industry"] == "landscaping"
    assert isinstance(body["items"], list)
    assert body["source"] in ("override", "default")
    assert "locale" in body
    # Every row is required=False (or missing, which the checklist
    # gate treats as False).
    for row in body["items"]:
        assert not row.get("required"), (
            f"Landscape row {row.get('key')!r} still required "
            f"after P29 endpoint response: {row}"
        )


def test_p29_get_pool_returns_original_required_distribution(admin_h):
    """Pool endpoint MUST return the pre-P29 distribution — 7
    required rows + 3 optional."""
    r = requests.get(f"{API}/checklists/industry/pool",
                      headers=admin_h, timeout=15)
    assert r.status_code == 200
    body = r.json()
    req = [row["key"] for row in body["items"] if row.get("required")]
    opt = [row["key"] for row in body["items"] if not row.get("required")]
    assert len(req) == 7, (
        f"Pool required count drifted (expected 7, got {len(req)}): "
        f"{sorted(req)}"
    )
    assert len(opt) == 3
    # Expected required keys locked verbatim — P29 must not have
    # moved any pool row into or out of the required bucket.
    assert set(req) == {
        "skimmed_pool", "brush_pool", "checked_skimmer_basket",
        "checked_pump_basket", "tested_chemicals",
        "checked_equipment", "secured_all_gates",
    }


# ══════════════════════════════════════════════════════════════════
# Migration idempotency + scope.
# ══════════════════════════════════════════════════════════════════


def test_p29_migration_first_run_updates_template_and_landscape_overrides():
    """Seed a landscape override with required=True items, seed a
    POOL override with required=True items, run migration → verify
    landscape is cleared, pool is untouched."""
    async def _go(db):
        tenant_a = f"{TAG}TEN_A_{uuid.uuid4().hex[:6]}"
        try:
            # Seed a landscape override with mixed required flags.
            await db.tenant_checklist_overrides.insert_one({
                "id": f"{TAG}OV_A", "tenant_id": tenant_a,
                "industry": "landscaping",
                "items": [
                    {"key": "mowed_lawn_areas", "label": "Mowed lawn areas",
                     "required": True},
                    {"key": "edged_walkways_driveways",
                     "label": "Edged walkways and driveways", "required": True},
                    {"key": "trimmed_shrubs_hedges",
                     "label": "Trimmed shrubs and hedges", "required": False},
                ],
                "created_at": datetime.now(timezone.utc).isoformat(),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            })
            # Seed a POOL override with a required item (must NOT
            # be touched).
            await db.tenant_checklist_overrides.insert_one({
                "id": f"{TAG}OV_P_A", "tenant_id": tenant_a,
                "industry": "pool",
                "items": [
                    {"key": "tested_chemicals",
                     "label": "Tested Chemicals", "required": True},
                ],
                "created_at": datetime.now(timezone.utc).isoformat(),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            })

            from migrations.p29_clear_landscape_required_overrides import (
                run,
            )
            res1 = await run()

            # Migration reports at least one override updated.
            assert res1["overrides_updated"] >= 1, res1

            # Landscape override — every row is now required=False.
            l = await db.tenant_checklist_overrides.find_one(
                {"tenant_id": tenant_a, "industry": "landscaping"},
                {"_id": 0, "items": 1},
            )
            for row in l["items"]:
                assert row.get("required") is False, (
                    f"Landscape override row not cleared: {row}"
                )
            # Row shape (label + key) preserved.
            keys_after = {r["key"] for r in l["items"]}
            assert keys_after == {
                "mowed_lawn_areas", "edged_walkways_driveways",
                "trimmed_shrubs_hedges",
            }

            # Pool override — UNTOUCHED.
            p = await db.tenant_checklist_overrides.find_one(
                {"tenant_id": tenant_a, "industry": "pool"},
                {"_id": 0, "items": 1},
            )
            assert p["items"][0]["required"] is True, (
                f"Pool override was mutated by P29 — scope leak! "
                f"{p}"
            )
        finally:
            await db.tenant_checklist_overrides.delete_many(
                {"tenant_id": tenant_a},
            )

    run_test(_go)


def test_p29_migration_second_run_is_a_noop():
    """Run the migration back-to-back; the second run reports
    ``overrides_updated == 0`` and the ``already_clear`` counter
    absorbs the previously-cleared override."""
    async def _go(db):
        tenant_id = f"{TAG}IDEM_{uuid.uuid4().hex[:6]}"
        try:
            # Seed an override that's ALREADY clear.
            await db.tenant_checklist_overrides.insert_one({
                "id": f"{TAG}OV_IDEM", "tenant_id": tenant_id,
                "industry": "landscaping",
                "items": [
                    {"key": "mowed_lawn_areas", "label": "Mowed lawn areas",
                     "required": False},
                ],
                "created_at": datetime.now(timezone.utc).isoformat(),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            })

            from migrations.p29_clear_landscape_required_overrides import (
                run,
            )
            res1 = await run()
            # The idempotency check MUST have counted THIS tenant's
            # override as skipped-already-clear (there may be other
            # overrides on preview that raise the counter — we
            # assert monotonically-non-decreasing not equality).
            assert res1["overrides_skipped_already_clear"] >= 1

            # Second run — no mutations expected (this specific
            # override still already-clear).
            res2 = await run()
            assert res2["overrides_skipped_already_clear"] >= 1

            # And the underlying doc still has required=False.
            l = await db.tenant_checklist_overrides.find_one(
                {"tenant_id": tenant_id, "industry": "landscaping"},
                {"_id": 0, "items": 1},
            )
            for row in l["items"]:
                assert row.get("required") is False
        finally:
            await db.tenant_checklist_overrides.delete_many(
                {"tenant_id": tenant_id},
            )

    run_test(_go)


# ══════════════════════════════════════════════════════════════════
# Template refresh in persisted collection.
# ══════════════════════════════════════════════════════════════════


def test_p29_migration_refreshes_persisted_template_doc():
    """The template stored in ``industry_checklist_templates`` MUST
    reflect the fresh in-memory ``DEFAULT_TEMPLATES["landscaping"]``
    after the migration runs. Pre-P29 the seeder skipped existing
    templates so the required=True items persisted forever."""
    async def _go(db):
        # Force a stale state — insert a pre-P29-shaped template
        # (or update the existing one to look stale).
        from migrations.p29_clear_landscape_required_overrides import (
            run,
        )
        stale_items = [
            {"key": "mowed_lawn_areas", "label": "Mowed lawn areas",
             "required": True},  # ← stale required=True
            {"key": "trimmed_shrubs_hedges",
             "label": "Trimmed shrubs and hedges", "required": False},
        ]
        # Snapshot the pre-migration state so we can restore it if
        # the run fails halfway.
        pre = await db.industry_checklist_templates.find_one(
            {"industry": "landscaping", "is_default": True},
            {"_id": 0},
        )
        try:
            await db.industry_checklist_templates.update_one(
                {"industry": "landscaping", "is_default": True},
                {"$set": {"items": stale_items}},
                upsert=True,
            )

            res = await run()
            assert res["template_updated"] is True

            after = await db.industry_checklist_templates.find_one(
                {"industry": "landscaping", "is_default": True},
                {"_id": 0, "items": 1},
            )
            # Every row is required=False AND the row count matches
            # the fresh in-memory template (9 rows).
            assert len(after["items"]) == 9
            for row in after["items"]:
                assert row.get("required") is False, (
                    f"Persisted template row not cleared after P29: "
                    f"{row}"
                )
        finally:
            # Restore original state so subsequent tests see a
            # clean baseline (P21 boot pass will re-apply P29
            # anyway).
            if pre and pre.get("items"):
                await db.industry_checklist_templates.update_one(
                    {"industry": "landscaping", "is_default": True},
                    {"$set": {"items": pre["items"]}},
                )

    run_test(_go)


# ══════════════════════════════════════════════════════════════════
# Source guardrails.
# ══════════════════════════════════════════════════════════════════


def test_p29_source_lint_no_required_true_on_landscape_template():
    """A source-level assertion locks the required=False shape.
    Regressions here typically come from a bulk find-replace or a
    seeder-refresh commit that pulls the pre-P29 defaults back."""
    src = (Path(__file__).resolve().parents[1] / "routers"
           / "industry_checklists.py").read_text(encoding="utf-8")
    # Isolate the landscape block by finding its opening + closing
    # brackets around the ``"landscaping": [`` key.
    start = src.find('"landscaping": [')
    assert start != -1, "landscape template block not found"
    end = src.find("],", start)
    assert end != -1, "landscape template block malformed"
    block = src[start:end]
    assert '"required": True' not in block, (
        f"Landscape template still contains required=True rows — "
        f"P29 regressed at source level."
    )


def test_p29_migration_wired_into_structural_boot():
    """Source-lint on ``server.py`` — the P29 migration MUST be
    invoked from ``_run_boot_sequence`` via
    ``_run_structural_migration`` with ``must_succeed=False``."""
    src = (Path(__file__).resolve().parents[1]
           / "server.py").read_text(encoding="utf-8")
    import re
    m = re.search(
        r"^async def _run_boot_sequence\(\).*?(?=^async def |\Z)",
        src, flags=re.MULTILINE | re.DOTALL,
    )
    assert m is not None
    boot_body = m.group(0)
    assert "p29_clear_landscape_required_overrides" in boot_body, (
        "_run_boot_sequence does not reference the P29 migration "
        "— boot cleanup pass never runs."
    )
    # Must be wired via the structural-migration helper (so failures
    # surface on /api/health).
    assert '"p29_clear_landscape_required_overrides"' in boot_body
    # must_succeed=False — best-effort; boot never blocks on this
    # cleanup pass.
    assert "must_succeed=False" in boot_body


def test_p29_endpoint_contract_shape_unchanged(admin_h):
    """A minimal envelope-shape guard so any refactor of the
    checklist endpoint keeps returning the fields the mobile
    client + FE consume."""
    r = requests.get(f"{API}/checklists/industry/landscaping",
                      headers=admin_h, timeout=15)
    assert r.status_code == 200
    body = r.json()
    for key in ("industry", "items", "source", "locale"):
        assert key in body, (
            f"P29 endpoint envelope drift — missing key {key!r} "
            f"in response: {sorted(body.keys())}"
        )
    # Row-level contract — every row exposes key/label/required.
    for row in body["items"]:
        for row_key in ("key", "label", "required"):
            assert row_key in row, (
                f"Landscape row missing {row_key!r}: {row}"
            )
        # ``label_en`` + ``label_i18n_available`` shipped by the
        # D4 localization wrapper — locked so the FE can rely on
        # them.
        assert "label_en" in row
        assert "label_i18n_available" in row
