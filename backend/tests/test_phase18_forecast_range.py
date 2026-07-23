"""Feb-2026 · Enhancement 2 — Revenue Forecast preset ranges.

Verifies that ``GET /api/reports/forecast?range=…`` returns the
correct inclusive [date_from, date_to] window in the tenant timezone
(America/Phoenix, no DST) for each preset."""
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

try:
    from zoneinfo import ZoneInfo
except ImportError:
    ZoneInfo = None

import pytest
import requests
from dotenv import dotenv_values

_env = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
API = "http://localhost:8001/api"


def _login(email, pw="password123"):
    r = requests.post(f"{API}/auth/login",
                       json={"email": email, "password": pw}, timeout=10)
    r.raise_for_status()
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture(scope="module")
def admin_headers():
    return _login("admin@aquaterra.com")


def _phoenix_today():
    tz = ZoneInfo("America/Phoenix") if ZoneInfo else None
    return datetime.now(tz).date()


def test_today_range(admin_headers):
    r = requests.get(f"{API}/reports/forecast?range=today",
                      headers=admin_headers, timeout=10)
    assert r.status_code == 200, r.text
    body = r.json()
    d = _phoenix_today().isoformat()
    assert body["range"] == "today"
    assert body["date_from"] == d
    assert body["date_to"] == d
    # series has exactly one bucket.
    assert len(body["series"]) == 1


def test_tomorrow_range(admin_headers):
    r = requests.get(f"{API}/reports/forecast?range=tomorrow",
                      headers=admin_headers, timeout=10)
    body = r.json()
    d = (_phoenix_today() + timedelta(days=1)).isoformat()
    assert body["date_from"] == d
    assert body["date_to"] == d
    assert len(body["series"]) == 1


def test_week_range_is_mon_to_sun(admin_headers):
    r = requests.get(f"{API}/reports/forecast?range=week",
                      headers=admin_headers, timeout=10)
    body = r.json()
    today = _phoenix_today()
    monday = today - timedelta(days=today.weekday())
    sunday = monday + timedelta(days=6)
    assert body["date_from"] == monday.isoformat()
    assert body["date_to"] == sunday.isoformat()
    assert len(body["series"]) == 7


def test_month_range(admin_headers):
    r = requests.get(f"{API}/reports/forecast?range=month",
                      headers=admin_headers, timeout=10)
    body = r.json()
    today = _phoenix_today()
    first = today.replace(day=1)
    assert body["date_from"] == first.isoformat()
    # date_to is last day of month.
    last = datetime.fromisoformat(body["date_to"]).date()
    assert last.month == today.month and last >= today


def test_custom_range_requires_both_dates(admin_headers):
    r = requests.get(f"{API}/reports/forecast?range=custom",
                      headers=admin_headers, timeout=10)
    assert r.status_code == 400


def test_custom_range_returns_full_window(admin_headers):
    r = requests.get(
        f"{API}/reports/forecast?range=custom&date_from=2026-02-01&date_to=2026-02-07",
        headers=admin_headers, timeout=10)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["date_from"] == "2026-02-01"
    assert body["date_to"] == "2026-02-07"
    assert len(body["series"]) == 7


def test_custom_range_rejects_inverted(admin_headers):
    r = requests.get(
        f"{API}/reports/forecast?range=custom&date_from=2026-02-10&date_to=2026-02-01",
        headers=admin_headers, timeout=10)
    assert r.status_code == 400


def test_invalid_range_rejected(admin_headers):
    r = requests.get(f"{API}/reports/forecast?range=quarter",
                      headers=admin_headers, timeout=10)
    assert r.status_code == 400


def test_legacy_days_flow_unchanged(admin_headers):
    """Callers without ``range=`` still use the legacy weekly ``days=90`` flow."""
    r = requests.get(f"{API}/reports/forecast?days=30",
                      headers=admin_headers, timeout=10)
    assert r.status_code == 200
    body = r.json()
    # Legacy shape has ``series`` + ``total`` and NO ``range`` key.
    assert "series" in body and "total" in body
    assert "range" not in body
