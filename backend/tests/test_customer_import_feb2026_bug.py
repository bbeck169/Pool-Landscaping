"""Feb-2026 real-world CSV import bug fix — regression suite.

User reported: importing an ``Active Clients.csv`` (122 rows, header shape
``Customer Since,,Email,Service address Street,City,State,Postal Code,
Phone,Mobile,First Name,Last Name,Tag,``) resulted in **0 created / 122
updated** and dropped every address field.

Root cause (four distinct failures):
  1. Address parts were saved to ``service_address.{street,city,state,
     postal_code}`` (nested) but ``CustomersList`` / ``CustomerDetail``
     render ``customer.address`` (flat string) and ``comm_tokens``
     substitutes ``customer.address_line1`` — so the flat / top-level
     shape was missing.
  2. Rows whose ``Phone`` column was blank but ``Mobile`` populated only
     carried a mobile-type phone. Downstream SMS/invoice matchers that
     iterate ``phones[type=home]`` missed them.
  3. Dedup logic did not defensively handle rows with neither email nor
     mobile — historically fine, but a subtle regression risk if any
     future refactor introduces a truthy default. Explicit hard-guard
     documents the invariant with a warning.
  4. ``Customer Since`` values that are a bare year (e.g. ``2023``) were
     rejected as unparseable — real-world CSVs often carry just the year.

This suite pins all four fixes against the actual customer-supplied CSV
fixture at ``tests/fixtures/active_clients.csv``.
"""
import os
from pathlib import Path

import pytest
import requests

BASE_URL = (
    os.environ.get("REACT_APP_BACKEND_URL")
    or os.environ.get("EXPO_PUBLIC_BACKEND_URL")
    or "http://localhost:8001"
).rstrip("/")
API = f"{BASE_URL}/api"

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "active_clients.csv"


def _login(email: str, password: str = "password123") -> str:
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=30)
    assert r.status_code == 200, f"login {email} => {r.status_code} {r.text}"
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def admin_headers():
    return {"Authorization": f"Bearer {_login('admin@aquaterra.com')}"}


@pytest.fixture(scope="module")
def real_csv_text() -> str:
    assert FIXTURE_PATH.exists(), (
        f"missing fixture at {FIXTURE_PATH} — download it before running: "
        "curl -o tests/fixtures/active_clients.csv "
        "'https://customer-assets-agu9un31.emergentagent.net/job_pool-project-1/"
        "artifacts/saa32wr9_Active%20CLients.csv'"
    )
    return FIXTURE_PATH.read_text(encoding="utf-8")


def _fetch_customer(admin_headers, email: str) -> dict | None:
    r = requests.get(
        f"{API}/customers", headers=admin_headers, params={"search": email}, timeout=30,
    )
    assert r.status_code == 200, r.text
    for c in r.json() or []:
        if (c.get("email") or "").lower() == email.lower():
            return c
    return None


# ---------------------------------------------------------------------------
# Test 1 — real-world CSV addresses are populated on both the flat + nested
# fields so CustomersList / CustomerDetail / comm_tokens all render.
# ---------------------------------------------------------------------------

def test_import_active_clients_csv_addresses_populated(admin_headers, real_csv_text):
    r = requests.post(
        f"{API}/import/customers", headers=admin_headers,
        json={"csv": real_csv_text}, timeout=90,
    )
    assert r.status_code == 200, r.text
    data = r.json()
    # 122 rows; imported == created + updated. Either path must persist address.
    assert data["total_rows"] == 122, data
    assert data["imported"] >= 120, (
        f"imported={data['imported']} skipped={data['skipped']} — "
        f"real CSV should import cleanly. errors={data.get('errors')[:3]}"
    )

    # Sample known rows from the fixture. Each must have flat + nested +
    # top-level address parts populated so every downstream consumer works.
    samples = [
        ("sarjongarcia1976@live.com", "13798 West Whisper Rock Trail",
         "Peoria", "AZ", "85383"),
        ("lyndseyh93@ymail.com", "29944 N 128th Ave",
         "Peoria", "AZ", "85383"),
    ]
    for email, street, city, state, postal in samples:
        doc = _fetch_customer(admin_headers, email)
        assert doc is not None, f"row for {email} not persisted"

        # (a) Top-level flat address string — CustomersList + CustomerDetail
        assert street in (doc.get("address") or ""), (
            f"{email}: flat address missing street; got address={doc.get('address')!r}"
        )
        assert city in (doc.get("address") or "")
        assert postal in (doc.get("address") or "")

        # (b) Top-level individual fields — comm_tokens substitution
        assert doc.get("address_line1") == street, doc.get("address_line1")
        assert doc.get("city") == city, doc.get("city")
        assert doc.get("state") == state, doc.get("state")
        assert doc.get("postal_code") == postal, doc.get("postal_code")

        # (c) Nested block — kept for newer consumers.
        sa = doc.get("service_address") or {}
        assert sa.get("street") == street
        assert sa.get("city") == city
        assert sa.get("state") == state
        assert sa.get("postal_code") == postal


# ---------------------------------------------------------------------------
# Test 2 — dedup math with mocked existing rows. Verifies that two rows
# with no email/phone don't collapse onto each other, and that a row
# whose email matches an existing customer updates instead of creating.
# ---------------------------------------------------------------------------

def test_import_active_clients_csv_dedup_math(admin_headers):
    """Two "John Smith" rows without email or phone must both insert
    separately; a row whose email is already in DB must upsert (update),
    not create a duplicate. Uses a controlled 3-row CSV so we can assert
    exact create/update counts irrespective of tenant history."""
    unique_email = "dedup_test_math@example.com"

    # Seed: create one customer via the real endpoint so we know the
    # dedup key exists in this tenant.
    r0 = requests.post(f"{API}/customers", headers=admin_headers, json={
        "name": "Existing DedupTest", "email": unique_email,
        "phone": "+14805551234", "address": "1 Original Way, Peoria, AZ 85383",
    }, timeout=30)
    assert r0.status_code in (200, 201), r0.text
    seeded_id = r0.json().get("id")
    assert seeded_id

    try:
        # 3-row CSV:
        #  - row A: same email as seed → must UPDATE the seeded row
        #  - row B: no email + no phone (John Smith #1)  → must CREATE
        #  - row C: no email + no phone (John Smith #2)  → must CREATE
        # Note: identity fields (first + last) are still required.
        csv_text = (
            "Customer Since,,Email,Service address Street,City,State,Postal Code,"
            "Phone,Mobile,First Name,Last Name,Tag,\n"
            f"6/1/2024,,{unique_email},1 New Way,Peoria,AZ,85383,,,Existing,"
            "TEST_DedupTest,,\n"
            ",,,,,,,,,John,TEST_DedupSmithA,,\n"
            ",,,,,,,,,John,TEST_DedupSmithB,,\n"
        )
        r = requests.post(
            f"{API}/import/customers", headers=admin_headers,
            json={"csv": csv_text}, timeout=30,
        )
        assert r.status_code == 200, r.text
        data = r.json()
        # Exactly 1 update (the seeded email row) and 2 creates.
        assert data["updated_count"] == 1, (
            f"expected 1 update; got {data['updated_count']} — email dedup broken"
        )
        assert data["created_count"] == 2, (
            f"expected 2 creates for the two no-key rows; got {data['created_count']} — "
            "keyless rows are collapsing onto each other"
        )
        # The two no-key inserts must have surfaced the "no dedup key" warning.
        warn_messages = [w["message"] for w in data["warnings"]]
        no_key_warnings = [m for m in warn_messages if "no dedup key" in m]
        assert len(no_key_warnings) >= 2, (
            f"expected ≥2 'no dedup key' warnings; got {no_key_warnings}"
        )
    finally:
        # Cleanup — remove the 3 rows this test created/updated.
        for last in ("TEST_DedupTest", "TEST_DedupSmithA", "TEST_DedupSmithB"):
            search = requests.get(
                f"{API}/customers", headers=admin_headers,
                params={"search": last}, timeout=30,
            ).json() or []
            for c in search:
                if last in (c.get("last_name") or "") or last in (c.get("name") or ""):
                    requests.delete(f"{API}/customers/{c['id']}",
                                     headers=admin_headers, timeout=15)


# ---------------------------------------------------------------------------
# Test 3 — Mobile promoted to Phone when Phone column is blank.
# ---------------------------------------------------------------------------

def test_import_mobile_promoted_to_phone_when_phone_blank(admin_headers):
    """Row where Phone column is blank but Mobile is set. Both the
    scalar ``customer.phone`` field AND a ``phones[type=home]`` entry
    must carry the mobile number in E.164 form, so downstream matchers
    (SMS inbound, invoice merge fields) resolve identically to a row
    that had a real Phone column."""
    email = "test_mobile_promoted@example.com"
    csv_text = (
        "Customer Since,,Email,Service address Street,City,State,Postal Code,"
        "Phone,Mobile,First Name,Last Name,Tag,\n"
        f",,{email},11 Promote Ln,Peoria,AZ,85383,,(623) 555-0001,"
        "Promo,TEST_MobilePromo,,\n"
    )
    try:
        r = requests.post(f"{API}/import/customers", headers=admin_headers,
                           json={"csv": csv_text}, timeout=30)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["imported"] == 1

        doc = _fetch_customer(admin_headers, email)
        assert doc is not None

        # Scalar `phone` field carries the E.164 form of the mobile.
        assert doc.get("phone") == "+16235550001", doc.get("phone")

        # phones[] carries both a home (promoted) and a mobile entry,
        # both with the same E.164 number.
        phones = doc.get("phones") or []
        home = [p for p in phones if p.get("type") == "home"]
        mobile = [p for p in phones if p.get("type") == "mobile"]
        assert len(home) == 1, f"expected 1 home entry (promoted from mobile); got {phones}"
        assert len(mobile) == 1, f"expected 1 mobile entry; got {phones}"
        assert home[0].get("number") == "+16235550001"
        assert mobile[0].get("number") == "+16235550001"

        # Warning must be surfaced so the admin sees the promotion.
        promotion_warnings = [w for w in data["warnings"] if "promoted" in w["message"]]
        assert promotion_warnings, (
            f"expected 'mobile promoted' warning; got warnings={data['warnings']!r}"
        )
    finally:
        doc = _fetch_customer(admin_headers, email)
        if doc:
            requests.delete(f"{API}/customers/{doc['id']}",
                             headers=admin_headers, timeout=15)


# ---------------------------------------------------------------------------
# Test 4 — Empty header column (double comma in the header row) does not
# shift subsequent columns. Verifies that the fixture's exact quirks —
# empty second column + trailing comma — do NOT contaminate Email into
# Customer Since, etc.
# ---------------------------------------------------------------------------

def test_import_empty_header_column_does_not_shift_others(admin_headers):
    """Fixture-shaped CSV with an empty second header column and a
    trailing comma. After import, the email must live in the ``email``
    field, the street in ``address_line1``, etc. — no column shift.

    Also exercises the bare-year Customer Since (``2023``) which must
    now parse to ``2023-01-01`` with a partial-parse warning.
    """
    email = "test_headershift_check@example.com"
    csv_text = (
        # Empty second column, trailing 13th column.
        "Customer Since,,Email,Service address Street,City,State,Postal Code,"
        "Phone,Mobile,First Name,Last Name,Tag,\n"
        # Bare-year Customer Since (2023).
        f"2023,,{email},99 Shift Test Blvd,Peoria,AZ,85383,,4805557777,"
        "Shift,TEST_HeaderShift,VIP,\n"
    )
    try:
        r = requests.post(f"{API}/import/customers", headers=admin_headers,
                           json={"csv": csv_text}, timeout=30)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["imported"] == 1

        doc = _fetch_customer(admin_headers, email)
        assert doc is not None, "row was silently dropped — column shift regression?"

        # No column shift — every value landed in the correct field.
        assert (doc.get("email") or "").lower() == email, doc.get("email")
        assert doc.get("address_line1") == "99 Shift Test Blvd", doc.get("address_line1")
        assert doc.get("city") == "Peoria"
        assert doc.get("state") == "AZ"
        assert doc.get("postal_code") == "85383"
        assert doc.get("first_name") == "Shift"
        assert doc.get("last_name") == "TEST_HeaderShift"
        assert doc.get("tags") == ["VIP"], doc.get("tags")

        # Bare-year → Jan 1 with a partial warning.
        assert doc.get("customer_since") == "2023-01-01", doc.get("customer_since")
        partial = [w for w in data["warnings"] if "assumed Jan 1" in w["message"]]
        assert partial, (
            f"expected 'assumed Jan 1' partial warning for year-only date; "
            f"got warnings={[w['message'] for w in data['warnings']]!r}"
        )
    finally:
        doc = _fetch_customer(admin_headers, email)
        if doc:
            requests.delete(f"{API}/customers/{doc['id']}",
                             headers=admin_headers, timeout=15)
