"""Iteration 38 — D2D Refresh-only sold-leads, walked/skip endpoints.

Covers:
- GET /api/d2d/sold-leads?zip=85383&days=30 returns ~dozens of homes for admin/tech
- Validation: 400 on non 5-digit zip; auth: 403 for customer / 401 for anon
- POST /api/d2d/skip/{zpid} + DELETE persists skipped flag for the calling rep
- After POST /d2d/skip/{zpid}, sold-leads response has skipped=true for that zpid
- httpx timeout=20 keeps request bounded (no >30s hang)
"""
import os
import time
import pytest
import requests
from pathlib import Path
from dotenv import dotenv_values

_ENV = dotenv_values(Path(__file__).resolve().parents[2] / "frontend" / ".env")
BASE_URL = (_ENV.get("EXPO_PUBLIC_BACKEND_URL") or os.environ.get("EXPO_BACKEND_URL", "")).rstrip("/")
API = f"{BASE_URL}/api"

ADMIN = {"email": "admin@aquaterra.com", "password": "password123"}
TECH = {"email": "mike@aquaterra.com", "password": "password123"}
CUST = {"email": "customer@aquaterra.com", "password": "password123"}
ZIP = "85383"


def _login(sess, creds):
    r = sess.post(f"{API}/auth/login", json=creds, timeout=30)
    assert r.status_code == 200, f"login {creds['email']}: {r.status_code} {r.text}"
    tok = r.json().get("token") or r.json().get("access_token")
    assert tok
    sess.headers.update({"Authorization": f"Bearer {tok}"})


@pytest.fixture(scope="module")
def admin_session():
    s = requests.Session(); _login(s, ADMIN); return s


@pytest.fixture(scope="module")
def tech_session():
    s = requests.Session(); _login(s, TECH); return s


@pytest.fixture(scope="module")
def customer_session():
    s = requests.Session(); _login(s, CUST); return s


# ---------- sold-leads endpoint ----------
class TestSoldLeads:
    def test_admin_ok_zip_85383(self, admin_session):
        t0 = time.time()
        r = admin_session.get(f"{API}/d2d/sold-leads", params={"zip": ZIP, "days": 30}, timeout=30)
        dt = time.time() - t0
        assert r.status_code == 200, f"{r.status_code} {r.text}"
        assert dt < 25, f"request took {dt:.1f}s — timeout not enforced"
        data = r.json()
        assert data["zip"] == ZIP and data["days"] == 30
        assert data["count"] == len(data["properties"])
        assert data["count"] > 0, "expected recent sales for 85383"
        p = data["properties"][0]
        for k in ("zpid", "address", "lat", "lng", "price", "date_sold", "logged", "skipped"):
            assert k in p, f"missing {k}"
        assert p["lat"] is not None and p["lng"] is not None

    def test_technician_ok(self, tech_session):
        r = tech_session.get(f"{API}/d2d/sold-leads", params={"zip": ZIP, "days": 30}, timeout=30)
        assert r.status_code == 200

    def test_customer_403(self, customer_session):
        r = customer_session.get(f"{API}/d2d/sold-leads", params={"zip": ZIP, "days": 30}, timeout=15)
        assert r.status_code == 403, f"{r.status_code} {r.text}"

    def test_no_auth_401_or_403(self):
        r = requests.get(f"{API}/d2d/sold-leads", params={"zip": ZIP, "days": 30}, timeout=15)
        assert r.status_code in (401, 403), f"{r.status_code} {r.text}"

    @pytest.mark.parametrize("bad", ["abc", "123", "123456", "", "8538a"])
    def test_invalid_zip_400(self, admin_session, bad):
        r = admin_session.get(f"{API}/d2d/sold-leads", params={"zip": bad, "days": 30}, timeout=15)
        assert r.status_code == 400, f"zip={bad!r}: got {r.status_code}"


# ---------- skip / unskip ----------
class TestSkipEndpoint:
    def test_skip_flow_persists(self, tech_session):
        r = tech_session.get(f"{API}/d2d/sold-leads", params={"zip": ZIP, "days": 30}, timeout=30)
        assert r.status_code == 200
        props = r.json()["properties"]
        target = next((p for p in props if not p.get("skipped")), None)
        assert target, "no un-skipped property to test with"
        zpid = target["zpid"]

        # POST /d2d/skip/{zpid}
        s = tech_session.post(f"{API}/d2d/skip/{zpid}", json={}, timeout=15)
        assert s.status_code == 200, f"{s.status_code} {s.text}"
        assert s.json().get("skipped") is True
        assert s.json().get("zpid") == zpid

        try:
            # verify sold-leads reflects skipped=true for this rep
            r2 = tech_session.get(f"{API}/d2d/sold-leads", params={"zip": ZIP, "days": 30}, timeout=30)
            match = next((p for p in r2.json()["properties"] if p["zpid"] == zpid), None)
            assert match is not None, "zpid disappeared after skip"
            assert match["skipped"] is True, f"expected skipped=True, got {match}"
        finally:
            # DELETE /d2d/skip/{zpid} cleanup
            d = tech_session.delete(f"{API}/d2d/skip/{zpid}", timeout=15)
            assert d.status_code == 200
            assert d.json().get("skipped") is False

        # verify unskipped after DELETE
        r3 = tech_session.get(f"{API}/d2d/sold-leads", params={"zip": ZIP, "days": 30}, timeout=30)
        match3 = next((p for p in r3.json()["properties"] if p["zpid"] == zpid), None)
        if match3 is not None:
            assert match3["skipped"] is False

    def test_skip_customer_403(self, customer_session):
        r = customer_session.post(f"{API}/d2d/skip/test_zpid_xyz", json={}, timeout=15)
        assert r.status_code == 403

    def test_skip_is_per_rep(self, admin_session, tech_session):
        # tech skips a zpid; admin should NOT see it as skipped
        r = tech_session.get(f"{API}/d2d/sold-leads", params={"zip": ZIP, "days": 30}, timeout=30)
        target = next((p for p in r.json()["properties"] if not p.get("skipped")), None)
        assert target
        zpid = target["zpid"]

        assert tech_session.post(f"{API}/d2d/skip/{zpid}", json={}, timeout=15).status_code == 200
        try:
            r_admin = admin_session.get(f"{API}/d2d/sold-leads", params={"zip": ZIP, "days": 30}, timeout=30)
            m = next((p for p in r_admin.json()["properties"] if p["zpid"] == zpid), None)
            assert m is not None
            # admin has a different tech_id (or same as user id) — skip should be scoped
            assert m["skipped"] is False, "skip leaked across reps"
        finally:
            tech_session.delete(f"{API}/d2d/skip/{zpid}", timeout=15)
