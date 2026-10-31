"""Feb-2026 · Ticket γ · BE pytest for the per-property service-
category write path reused by the identity-header popover.

Locks the server-side invariants the Ticket γ popover depends on
(the operator-locked guardrails from the brief):

  1. ``PATCH /properties/{pid}`` service_category write is gated
     by ``require_admin`` — admin / super_admin / owner only; any
     other role gets HTTP 403.
  2. Tenant scoping holds — a tenant-A admin's PATCH against a
     tenant-B property returns 404 (``update_one`` filter requires
     ``tenant_id`` match; the row is invisible across tenants).
  3. Value canonicalization is byte-identical to the Properties-
     tab path:
       - ``"pool"`` / ``"Pool"`` / ``"POOL"``   → stored as ``"pool"``
       - ``"landscaping"`` → ``"landscaping"``
       - ``"both"``        → ``"both"``
       - ``None`` / ``""`` / ``"unset"``        → stored as ``None`` +
         ``service_category_source = "admin_cleared"``
       - any out-of-enum string (e.g. ``"HVAC"``) → silently
         dropped from the update
     Non-null writes stamp ``service_category_source = "admin_override"``
     and ``service_category_set_at`` ISO timestamp.
  4. Badge-derivation parity — mirror the FE
     ``_computeCombinedCategory`` rule end-to-end from a seed:
       - all-Pool properties                       → "Pool"
       - all-Landscaping                           → "Landscaping"
       - all-Both                                  → "Both"
       - mixed Pool + Landscaping                  → "Pool + Landscaping"
       - zero properties / all null service_category → "—" muted
     The BE itself does NOT compute the label; this test pins the
     *inputs* the FE reducer sees (what service_category values
     the shipped PATCH persists for each raw input) so a future BE
     refactor can't silently drift the badge display.
"""
from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

import pytest
from dotenv import dotenv_values
from fastapi import HTTPException
from motor.motor_asyncio import AsyncIOMotorClient


_ENV = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
_ENV = {k: (v.strip().strip('"').strip("'") if isinstance(v, str) else v)
        for k, v in _ENV.items()}

_LOOP = asyncio.new_event_loop()
asyncio.set_event_loop(_LOOP)
_MC = AsyncIOMotorClient(_ENV["MONGO_URL"], io_loop=_LOOP)
_DB = _MC[_ENV["DB_NAME"]]


def _run(coro):
    asyncio.set_event_loop(_LOOP)
    return _LOOP.run_until_complete(coro)


def _patch_db_everywhere():
    import config
    config.db = _DB
    for mod in ("routers.properties",):
        __import__(mod)
        import sys as _sys
        _sys.modules[mod].db = _DB


PREFIX = f"tgamma-{uuid.uuid4().hex[:8]}"
TENANT_A = f"{PREFIX}-tenant-a"
TENANT_B = f"{PREFIX}-tenant-b"
CUST_A = f"{PREFIX}-cust-a"
PROP_A = f"{PREFIX}-prop-a"
PROP_B = f"{PREFIX}-prop-b"


async def _seed_tenant(tid):
    await _DB.tenants.insert_one({"id": tid, "name": "T"})


async def _seed_customer(cid, tid):
    await _DB.customers.insert_one({
        "id": cid, "tenant_id": tid, "name": "C",
    })


async def _seed_property(pid, tid, cid, service_category=None):
    doc = {
        "id": pid, "tenant_id": tid, "customer_id": cid,
        "label": "Primary", "sort_order": 0, "active": True,
    }
    if service_category is not None:
        doc["service_category"] = service_category
    await _DB.properties.insert_one(doc)


async def _cleanup():
    rx = {"$regex": f"^{PREFIX}"}
    for coll in ("properties", "customers", "tenants"):
        await _DB[coll].delete_many({"$or": [
            {"id": rx}, {"tenant_id": rx}, {"customer_id": rx},
        ]})


@pytest.fixture(autouse=True)
def _clean():
    _patch_db_everywhere()
    _run(_cleanup())
    yield
    _run(_cleanup())


async def _patch(pid, body, user_role="admin", tenant_id=TENANT_A):
    """Invoke the shipped ``patch_property`` handler directly so
    the test runs end-to-end through the enum guard + canonicalizer
    without the FastAPI stack.  Mirrors
    ``test_dashboard_service_category_breakdown.py`` harness."""
    from routers.properties import patch_property, PropertyPatch
    from utils import require_admin

    user = {"id": f"{PREFIX}-u", "role": user_role,
            "tenant_id": tenant_id}
    # Enforce the Depends chain by invoking the guard directly;
    # 403 path is tested below.
    require_admin(user=user)
    return await patch_property(
        pid=pid, body=PropertyPatch(**body),
        user=user, tenant={"id": tenant_id},
    )


# ═══════════════════════════════════════════════════════════════════
# 1. Role gate — admin / super_admin / owner may write; all others 403.
# ═══════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("role", ["admin", "super_admin", "owner"])
def test_privileged_roles_can_write_service_category(role):
    _run(_seed_tenant(TENANT_A))
    _run(_seed_customer(CUST_A, TENANT_A))
    _run(_seed_property(PROP_A, TENANT_A, CUST_A))
    out = _run(_patch(PROP_A, {"service_category": "pool"},
                        user_role=role))
    assert out["service_category"] == "pool"
    assert out["service_category_source"] == "admin_override"
    assert out.get("service_category_set_at")


@pytest.mark.parametrize("role",
                            ["technician", "manager", "customer", "sales"])
def test_non_privileged_roles_are_forbidden(role):
    _run(_seed_tenant(TENANT_A))
    _run(_seed_customer(CUST_A, TENANT_A))
    _run(_seed_property(PROP_A, TENANT_A, CUST_A))
    with pytest.raises(HTTPException) as exc:
        _run(_patch(PROP_A, {"service_category": "pool"},
                       user_role=role))
    assert exc.value.status_code == 403


# ═══════════════════════════════════════════════════════════════════
# 2. Tenant scoping — tenant-A admin cannot write tenant-B's row.
# ═══════════════════════════════════════════════════════════════════
def test_cross_tenant_write_404s():
    _run(_seed_tenant(TENANT_A))
    _run(_seed_tenant(TENANT_B))
    _run(_seed_customer(CUST_A, TENANT_B))
    _run(_seed_property(PROP_B, TENANT_B, CUST_A))
    # Tenant-A admin attempts to patch tenant-B's property.
    with pytest.raises(HTTPException) as exc:
        _run(_patch(PROP_B, {"service_category": "pool"},
                       user_role="admin", tenant_id=TENANT_A))
    assert exc.value.status_code == 404


# ═══════════════════════════════════════════════════════════════════
# 3. Value canonicalization.
# ═══════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("raw,expected", [
    ("pool",        "pool"),
    ("Pool",        "pool"),
    ("POOL",        "pool"),
    ("landscaping", "landscaping"),
    ("both",        "both"),
])
def test_valid_values_canonicalize_to_lowercase_enum(raw, expected):
    _run(_seed_tenant(TENANT_A))
    _run(_seed_customer(CUST_A, TENANT_A))
    _run(_seed_property(PROP_A, TENANT_A, CUST_A))
    out = _run(_patch(PROP_A, {"service_category": raw}))
    assert out["service_category"] == expected
    assert out["service_category_source"] == "admin_override"


@pytest.mark.parametrize("raw", [None, "", "unset", "UNSET", "  "])
def test_null_empty_or_unset_clears_the_field(raw):
    _run(_seed_tenant(TENANT_A))
    _run(_seed_customer(CUST_A, TENANT_A))
    _run(_seed_property(PROP_A, TENANT_A, CUST_A,
                           service_category="pool"))
    out = _run(_patch(PROP_A, {"service_category": raw}))
    assert out["service_category"] is None
    assert out["service_category_source"] == "admin_cleared"


def test_out_of_enum_value_is_silently_dropped():
    _run(_seed_tenant(TENANT_A))
    _run(_seed_customer(CUST_A, TENANT_A))
    _run(_seed_property(PROP_A, TENANT_A, CUST_A,
                           service_category="pool"))
    out = _run(_patch(PROP_A, {"service_category": "HVAC"}))
    # Out-of-enum raw string is dropped — original value preserved,
    # no source stamp overwrite.
    assert out["service_category"] == "pool"
    assert "service_category_source" not in out \
        or out.get("service_category_source") != "admin_override"


# ═══════════════════════════════════════════════════════════════════
# 4. Badge-derivation parity — simulate the FE reducer end-to-end
#    on the shipped BE output so a future refactor can't silently
#    drift the badge label.
# ═══════════════════════════════════════════════════════════════════
_ORDER = ["pool", "landscaping", "both"]
_LABEL = {"pool": "Pool", "landscaping": "Landscaping", "both": "Both"}


def _badge_label(properties):
    """Mirror of ``_computeCombinedCategory`` in
    ``frontend/src/components/customers/CombinedCategoryBadge.jsx``.
    Kept inline here so this suite can lock the derivation rule
    without reading the FE source."""
    if not properties:
        return None
    present = set()
    for p in properties:
        if p.get("active") is False:
            continue
        cat = (p.get("service_category") or "").lower()
        if cat in _ORDER:
            present.add(cat)
    if not present:
        return None
    parts = [_LABEL[c] for c in _ORDER if c in present]
    return " + ".join(parts)


async def _list_properties():
    rows = await _DB.properties.find(
        {"tenant_id": TENANT_A, "customer_id": CUST_A},
        {"_id": 0, "id": 1, "service_category": 1, "active": 1},
    ).to_list(50)
    return rows


def _seed_two_props_and_label():
    _run(_seed_tenant(TENANT_A))
    _run(_seed_customer(CUST_A, TENANT_A))
    _run(_seed_property(PROP_A, TENANT_A, CUST_A))
    _run(_seed_property(PROP_B, TENANT_A, CUST_A))


def test_badge_derivation_all_pool():
    _seed_two_props_and_label()
    _run(_patch(PROP_A, {"service_category": "pool"}))
    _run(_patch(PROP_B, {"service_category": "pool"}))
    assert _badge_label(_run(_list_properties())) == "Pool"


def test_badge_derivation_all_landscaping():
    _seed_two_props_and_label()
    _run(_patch(PROP_A, {"service_category": "landscaping"}))
    _run(_patch(PROP_B, {"service_category": "landscaping"}))
    assert _badge_label(_run(_list_properties())) == "Landscaping"


def test_badge_derivation_all_both():
    _seed_two_props_and_label()
    _run(_patch(PROP_A, {"service_category": "both"}))
    _run(_patch(PROP_B, {"service_category": "both"}))
    assert _badge_label(_run(_list_properties())) == "Both"


def test_badge_derivation_mixed_pool_and_landscaping():
    _seed_two_props_and_label()
    _run(_patch(PROP_A, {"service_category": "pool"}))
    _run(_patch(PROP_B, {"service_category": "landscaping"}))
    assert _badge_label(_run(_list_properties())) \
        == "Pool + Landscaping"


def test_badge_derivation_zero_properties_is_muted():
    _run(_seed_tenant(TENANT_A))
    _run(_seed_customer(CUST_A, TENANT_A))
    # No properties seeded.
    assert _badge_label(_run(_list_properties())) is None


def test_badge_derivation_all_null_service_category_is_muted():
    _seed_two_props_and_label()
    # Both properties stay with service_category unset — derivation
    # yields muted "—".
    assert _badge_label(_run(_list_properties())) is None
