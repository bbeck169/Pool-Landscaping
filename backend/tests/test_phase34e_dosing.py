"""Phase 34e — Pool chemical dosing recommendations."""
import uuid
from pathlib import Path
from unittest.mock import patch

import pytest
import requests
from dotenv import dotenv_values

_FE = dotenv_values(Path(__file__).resolve().parents[2] / "frontend" / ".env")
BASE = (_FE.get("REACT_APP_BACKEND_URL") or "http://localhost:8001").rstrip("/")
API = f"{BASE}/api"

ADMIN = {"email": "admin@aquaterra.com", "password": "password123"}
TECH  = {"email": "mike@aquaterra.com",  "password": "password123"}
CUST  = {"email": "customer@aquaterra.com", "password": "password123"}


def _login(creds):
    r = requests.post(f"{API}/auth/login", json=creds, timeout=30)
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _auth(tok):
    return {"Authorization": f"Bearer {tok}"}


@pytest.fixture(scope="module")
def admin_tok(): return _login(ADMIN)


@pytest.fixture(scope="module")
def tech_tok(): return _login(TECH)


@pytest.fixture(scope="module")
def customer_tok(): return _login(CUST)


def _mk_name(): return f"TEST-e-{uuid.uuid4().hex[:8]}"


def _cleanup(tok, cid, jid=None):
    if jid:
        requests.delete(f"{API}/jobs/{jid}", headers=_auth(tok), timeout=15)
    if cid:
        requests.delete(f"{API}/customers/{cid}", headers=_auth(tok), timeout=15)


def test_low_ph_recommends_soda_ash(admin_tok):
    """10k-gallon pool with pH 7.0 → soda-ash recommendation with quantity > 0."""
    r = requests.post(
        f"{API}/service-report/recommend-chemicals",
        json={
            "readings": {"ph": 7.0},
            "pool_gallons": 10000,
            "use_llm_phrasing": False,
        },
        headers=_auth(admin_tok), timeout=30,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["mocked"] is False
    ph_rec = next((x for x in body["recommendations"] if x["reading_key"] == "ph"), None)
    assert ph_rec is not None, body
    assert "soda ash" in ph_rec["chemical"].lower()
    assert ph_rec["quantity"] > 0
    assert ph_rec["unit"] == "oz"
    assert ph_rec["target_range"] == [7.2, 7.6]


def test_quantity_scales_with_pool_gallons(admin_tok):
    """20k-gallon pool needs exactly 2x the chlorine of a 10k pool for the
    same FC deficiency."""
    common = {"readings": {"free_chlorine": 0.5}, "use_llm_phrasing": False}

    r_10k = requests.post(
        f"{API}/service-report/recommend-chemicals",
        json={**common, "pool_gallons": 10000},
        headers=_auth(admin_tok), timeout=30,
    ).json()
    r_20k = requests.post(
        f"{API}/service-report/recommend-chemicals",
        json={**common, "pool_gallons": 20000},
        headers=_auth(admin_tok), timeout=30,
    ).json()

    fc_10 = next(x for x in r_10k["recommendations"] if x["reading_key"] == "free_chlorine")
    fc_20 = next(x for x in r_20k["recommendations"] if x["reading_key"] == "free_chlorine")
    # Allow a 5% floating-point slack.
    assert abs(fc_20["quantity"] - 2 * fc_10["quantity"]) < (fc_10["quantity"] * 0.05 + 0.1)


def test_all_in_range_returns_empty(admin_tok):
    r = requests.post(
        f"{API}/service-report/recommend-chemicals",
        json={
            "readings": {
                "ph": 7.4,
                "free_chlorine": 2.0,
                "total_alkalinity": 100,
                "calcium_hardness": 250,
                "cyanuric_acid": 40,
            },
            "pool_gallons": 15000,
            "use_llm_phrasing": False,
        },
        headers=_auth(admin_tok), timeout=30,
    ).json()
    assert r["mocked"] is False
    assert r["recommendations"] == []


def test_pool_gallons_missing_both_places(admin_tok):
    """No pool_gallons on request AND no job_id → mocked=True with reason."""
    r = requests.post(
        f"{API}/service-report/recommend-chemicals",
        json={"readings": {"ph": 7.0}, "use_llm_phrasing": False},
        headers=_auth(admin_tok), timeout=30,
    ).json()
    assert r["mocked"] is True
    assert "pool_gallons" in (r["reason"] or "")
    assert r["recommendations"] == []
    assert r["pool_gallons"] is None


def test_fallback_to_customer_pool_gallons(admin_tok):
    """pool_gallons omitted in the body — resolved from the job → customer."""
    c = requests.post(f"{API}/customers",
                       json={"name": _mk_name(), "pool_gallons": 18000},
                       headers=_auth(admin_tok), timeout=15).json()
    j = requests.post(f"{API}/jobs",
                       json={"title": "svc", "customer_id": c["id"],
                              "scheduled_date": "2026-08-15"},
                       headers=_auth(admin_tok), timeout=15).json()
    try:
        r = requests.post(
            f"{API}/service-report/recommend-chemicals",
            json={"job_id": j["id"], "readings": {"ph": 7.0},
                    "use_llm_phrasing": False},
            headers=_auth(admin_tok), timeout=30,
        ).json()
        assert r["mocked"] is False
        assert r["pool_gallons"] == 18000
        assert len(r["recommendations"]) >= 1
    finally:
        _cleanup(admin_tok, c["id"], j["id"])


def test_llm_off_returns_deterministic_only(admin_tok):
    r = requests.post(
        f"{API}/service-report/recommend-chemicals",
        json={"readings": {"ph": 7.0}, "pool_gallons": 10000,
                "use_llm_phrasing": False},
        headers=_auth(admin_tok), timeout=30,
    ).json()
    assert r["source"] == "deterministic-only"
    assert r["tokens_used"] == 0


def test_customer_role_forbidden(customer_tok):
    r = requests.post(
        f"{API}/service-report/recommend-chemicals",
        json={"readings": {"ph": 7.0}, "pool_gallons": 10000,
                "use_llm_phrasing": False},
        headers=_auth(customer_tok), timeout=15,
    )
    assert r.status_code == 403


def test_technician_allowed(tech_tok):
    """Techs need this in the field — must be allowed."""
    r = requests.post(
        f"{API}/service-report/recommend-chemicals",
        json={"readings": {"ph": 7.4, "free_chlorine": 2.0},
                "pool_gallons": 10000, "use_llm_phrasing": False},
        headers=_auth(tech_tok), timeout=15,
    )
    assert r.status_code == 200, r.text


# ── Deterministic engine unit tests (no HTTP) ────────────────────────────
def test_engine_high_ph_recommends_acid():
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from services.pool_dosing import compute
    recs = compute({"ph": 7.9}, 10_000)
    ph_rec = next((x for x in recs if x["reading_key"] == "ph"), None)
    assert ph_rec is not None
    assert "muriatic" in ph_rec["chemical"].lower()
    assert ph_rec["quantity"] > 0


def test_engine_salt_only_recommended_if_reading_present():
    from services.pool_dosing import compute
    r_no_salt = compute({"ph": 7.4}, 10_000)
    assert not any(x["reading_key"] == "salt" for x in r_no_salt)
    r_low_salt = compute({"salt": 2000}, 10_000)
    assert any(x["reading_key"] == "salt" for x in r_low_salt)


def test_engine_aliases_normalize_reading_keys():
    from services.pool_dosing import compute
    # FC / chlorine / Free Chlorine all map to free_chlorine.
    r1 = compute({"FC": 0.5}, 10_000)
    r2 = compute({"Free Chlorine": 0.5}, 10_000)
    r3 = compute({"chlorine": 0.5}, 10_000)
    for r in (r1, r2, r3):
        assert any(x["reading_key"] == "free_chlorine" for x in r), r


def test_engine_capped_at_6():
    from services.pool_dosing import compute
    # Every reading maxed out — should still cap at 6.
    recs = compute({
        "ph": 6.5, "free_chlorine": 0.1, "total_alkalinity": 40,
        "calcium_hardness": 100, "cyanuric_acid": 10, "salt": 1500,
    }, 30_000)
    assert len(recs) <= 6
    # Chlorine (immediate) must be first.
    assert recs[0]["reading_key"] == "free_chlorine"
