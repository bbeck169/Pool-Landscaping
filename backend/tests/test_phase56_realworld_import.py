"""Phase 56.1 · real-world CSV import regression.

Uses the fixture at ``tests/fixtures/active_customer_list.csv`` — a
semicolon-delimited export from the user's live customer list that
surfaced 10 root causes (delimiter, comma-in-date, phone noise, HTML
in notes, tags-with-commas, empty emails, etc.). This test locks all
of those down.
"""
import os
import pathlib
import re
import pytest
import requests

API = os.getenv("TEST_API_BASE", "http://localhost:8001/api")
FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "active_customer_list.csv"


def _login(email, pw):
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": pw}, timeout=15)
    r.raise_for_status()
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def admin_token():
    return _login("admin@aquaterra.com", "password123")


@pytest.fixture(scope="module")
def csv_text():
    assert FIXTURE.exists(), f"fixture missing: {FIXTURE}"
    return FIXTURE.read_text(encoding="utf-8", errors="replace")


def _headers(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


def test_realworld_import(admin_token, csv_text):
    r = requests.post(f"{API}/import/customers",
                      headers=_headers(admin_token),
                      json={"csv": csv_text}, timeout=60)
    assert r.status_code == 200, r.text
    body = r.json()

    # Fixture has 151 data lines after header + trailing blanks — importer
    # trims blank rows so the count settles somewhere in the low 130s.
    assert body["total_rows"] >= 120, body
    # The vast majority must land — allow up to 30% row-level errors from
    # genuine data problems (no email + no mobile, etc.).
    assert body["imported_count"] >= body["total_rows"] * 0.7, body

    # Any errors surfaced must be REAL data problems, not parser bugs.
    for err in body.get("errors", []):
        reason = (err.get("reason") or "").lower()
        # Fail loud if we still see delimiter/phone-noise/date-parser
        # regressions in the error stream.
        assert "delimiter" not in reason
        assert "invalid phone" not in reason
        assert "invalid mobile" not in reason
        assert "customer since" not in reason
    print(f"Phase 56.1 import: total={body['total_rows']} "
          f"created={body['created_count']} updated={body['updated_count']} "
          f"skipped={body['skipped_count']} errors={len(body.get('errors', []))}")


def test_realworld_spot_checks(admin_token):
    """Spot-check three known rows for correct parsing."""
    # Row 1 — Nehemiah Abuga, comma-in-date, no home phone, mobile only.
    r = requests.get(f"{API}/customers", headers=_headers(admin_token), timeout=15)
    all_c = r.json() if isinstance(r.json(), list) else r.json().get("rows", [])
    by_email = {c.get("email", "").lower(): c for c in all_c if c.get("email")}

    n = by_email.get("aduganahemiah@gmail.com")
    assert n, "Nehemiah Abuga not found"
    assert n.get("customer_since") == "2026-07-01"
    mobile = next((p for p in (n.get("phones") or []) if p.get("type") == "mobile"), None)
    assert mobile and mobile.get("e164") == "+14804505020"
    assert "One Time Job" in (n.get("tags") or [])

    # Row 2 — Darren Rosenberg, "(248) 506-0827" mobile.
    d = by_email.get("grooved1@gmail.com")
    assert d, "Darren Rosenberg not found"
    d_mob = next((p for p in (d.get("phones") or []) if p.get("type") == "mobile"), None)
    assert d_mob and d_mob.get("e164") == "+12485060827"

    # Row 3 — HTML-notes check: any customer whose notes was populated
    # must be plain text (no `<` or `&nbsp;` residue).
    html_leaks = [c for c in all_c
                  if c.get("notes") and re.search(r"<[a-z]|&nbsp;|&apos;", c["notes"], re.I)]
    assert not html_leaks, f"HTML leaked into {len(html_leaks)} notes fields"


def test_idempotent_reimport(admin_token, csv_text):
    """Re-running the same import UPDATES, never DOUBLE-creates."""
    r = requests.post(f"{API}/import/customers",
                      headers=_headers(admin_token),
                      json={"csv": csv_text}, timeout=60)
    body = r.json()
    assert body["created_count"] == 0, f"expected 0 creates on re-run, got {body['created_count']}"
    assert body["updated_count"] >= body["total_rows"] * 0.7
