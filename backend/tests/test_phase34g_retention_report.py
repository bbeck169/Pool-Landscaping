"""Phase 34g — Customer Retention Report."""
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

# Phase 34-migrate-v2 · Phase 34-v2-d · Feb 2026 — swapped requests
# for the in-process ASGI shim.
from tests._phase34_http_shim import http
from dotenv import dotenv_values

_FE = dotenv_values(Path(__file__).resolve().parents[2] / "frontend" / ".env")
BASE = (_FE.get("REACT_APP_BACKEND_URL") or "http://localhost:8001").rstrip("/")
API = f"{BASE}/api"

ADMIN = {"email": "admin@aquaterra.com", "password": "password123"}
TECH  = {"email": "mike@aquaterra.com",  "password": "password123"}
SUPER = {"email": "super@aquaterra.com", "password": "password123"}


def _login(creds):
    r = http.post(f"{API}/auth/login", json=creds, timeout=30)
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _auth(tok):
    return {"Authorization": f"Bearer {tok}"}


@pytest.fixture(scope="module")
def admin_tok():
    return _login(ADMIN)


@pytest.fixture(scope="module")
def tech_tok():
    return _login(TECH)


def _mk_name():
    return f"TEST-retention-{uuid.uuid4().hex[:8]}"


def _iso_days(delta):
    return (datetime.now(timezone.utc) + timedelta(days=delta)).strftime("%Y-%m-%d")


def _cleanup(tok, cids, jids=()):
    for jid in jids:
        http.delete(f"{API}/jobs/{jid}", headers=_auth(tok), timeout=15)
    for cid in cids:
        http.delete(f"{API}/customers/{cid}", headers=_auth(tok), timeout=15)


def test_endpoint_basic_shape(admin_tok):
    r = http.get(f"{API}/reports/customer-retention?period=month",
                      headers=_auth(admin_tok), timeout=30)
    assert r.status_code == 200, r.text
    body = r.json()
    for key in ("period", "start", "end", "buckets", "totals", "yoy"):
        assert key in body, body
    assert body["period"] == "month"
    assert isinstance(body["buckets"], list)
    for b in body["buckets"]:
        for k in ("label", "start", "end", "gained", "lost", "net"):
            assert k in b


def test_gained_and_lost_counts(admin_tok):
    """Seed 3 gained + 2 lost inside the current window and verify totals."""
    # Baseline totals BEFORE seeding — the tenant has legacy data, so we
    # compute a diff, not an absolute.
    base = http.get(f"{API}/reports/customer-retention?period=month",
                        headers=_auth(admin_tok), timeout=30).json()
    base_g = base["totals"]["gained"]
    base_l = base["totals"]["lost"]

    # Seed 3 gained customers (created_at = now, inside the default 12-month
    # window).
    cids = []
    for _ in range(3):
        r = http.post(f"{API}/customers",
                           json={"name": _mk_name()},
                           headers=_auth(admin_tok), timeout=15)
        assert r.status_code == 200
        cids.append(r.json()["id"])

    # Seed 2 lost events by flipping is_active on two of them.
    for cid in cids[:2]:
        http.put(f"{API}/customers/{cid}",
                     json={"name": "test", "is_active": False},
                     headers=_auth(admin_tok), timeout=15)

    try:
        after = http.get(f"{API}/reports/customer-retention?period=month",
                              headers=_auth(admin_tok), timeout=30).json()
        assert after["totals"]["gained"] - base_g == 3, (base, after)
        assert after["totals"]["lost"]   - base_l == 2, (base, after)
        assert after["totals"]["net"] == (base["totals"]["net"] + 1), after
        # The active bucket (this month) must include at least +3 gained
        # and +2 lost.
        cur_label = datetime.now(timezone.utc).strftime("%Y-%m")
        cur = next((b for b in after["buckets"] if b["label"] == cur_label), None)
        assert cur is not None, after
        assert cur["gained"] >= 3
        assert cur["lost"]   >= 2
    finally:
        _cleanup(admin_tok, cids)


def test_period_week(admin_tok):
    r = http.get(f"{API}/reports/customer-retention?period=week",
                      headers=_auth(admin_tok), timeout=30)
    assert r.status_code == 200
    body = r.json()
    assert body["period"] == "week"
    # Between 50 and 54 weekly buckets in the default window.
    assert 50 <= len(body["buckets"]) <= 54, len(body["buckets"])
    for b in body["buckets"]:
        assert b["label"].startswith(("20", "19"))
        assert "W" in b["label"]


def test_period_year(admin_tok):
    r = http.get(f"{API}/reports/customer-retention?period=year",
                      headers=_auth(admin_tok), timeout=30).json()
    assert r["period"] == "year"
    assert 4 <= len(r["buckets"]) <= 6


def test_yoy_mocked_when_no_history(admin_tok):
    """Use a start-of-history window that's clearly before the tenant even
    existed to force the insufficient-history branch."""
    r = http.get(
        f"{API}/reports/customer-retention?period=month"
        f"&start=1990-01-01&end=1990-12-31",
        headers=_auth(admin_tok), timeout=30,
    ).json()
    assert r["yoy"]["mocked"] is True
    assert "insufficient history" in (r["yoy"]["reason"] or "").lower()
    assert r["yoy"]["previous_totals"] is None
    assert r["totals"]["gained"] == 0
    assert r["totals"]["lost"] == 0


def test_yoy_shape_is_valid(admin_tok):
    """The YoY block always has a valid shape: either mocked=True with
    previous_totals=None + a non-empty reason, OR mocked=False with a real
    previous_totals dict."""
    r = http.get(f"{API}/reports/customer-retention?period=month",
                      headers=_auth(admin_tok), timeout=30).json()
    yoy = r["yoy"]
    assert "mocked" in yoy and "reason" in yoy
    if yoy["mocked"]:
        assert yoy["previous_totals"] is None
        assert yoy["reason"] and len(yoy["reason"]) > 0
    else:
        assert isinstance(yoy["previous_totals"], dict)
        for k in ("gained", "lost", "net"):
            assert k in yoy["previous_totals"]


def test_invalid_period(admin_tok):
    r = http.get(f"{API}/reports/customer-retention?period=fortnight",
                      headers=_auth(admin_tok), timeout=15)
    assert r.status_code == 400


def test_tech_forbidden(tech_tok):
    r = http.get(f"{API}/reports/customer-retention?period=month",
                      headers=_auth(tech_tok), timeout=15)
    assert r.status_code == 403
