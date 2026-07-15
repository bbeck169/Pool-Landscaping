"""Phase 24 · Check Writer tests."""
import time
from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient


_FE = dotenv_values(Path(__file__).resolve().parents[2] / "frontend" / ".env")
_BE = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
BASE = (_FE.get("EXPO_PUBLIC_BACKEND_URL") or "http://localhost:8001").rstrip("/")
API = f"{BASE}/api"


def _login(email, pw="password123"):
    r = requests.post(f"{API}/auth/login",
                       json={"email": email, "password": pw}, timeout=15)
    r.raise_for_status(); return r.json()


@pytest.fixture(scope="module")
def dbc(): return MongoClient(_BE["MONGO_URL"])[_BE["DB_NAME"]]

@pytest.fixture(scope="module")
def admin_h():
    return {"Authorization": f"Bearer {_login('admin@aquaterra.com')['access_token']}"}

@pytest.fixture(scope="module")
def tech_h():
    return {"Authorization": f"Bearer {_login('mike@aquaterra.com')['access_token']}"}

@pytest.fixture(scope="module")
def customer_h():
    return {"Authorization": f"Bearer {_login('customer@aquaterra.com')['access_token']}"}

@pytest.fixture(scope="module")
def sunbelt_admin_h():
    try:
        return {"Authorization": f"Bearer {_login('admin@sunbelt.com')['access_token']}"}
    except Exception:
        pytest.skip("no sunbelt admin")


# ─── Unit: amount to words ───────────────────────────────────────────
def test_amount_to_words_unit():
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from routers.checks import amount_to_words as w
    assert w(1234.56) == "One thousand two hundred thirty-four and 56/100 dollars"
    assert w(100) == "One hundred and 00/100 dollars"
    assert w(0.99) == "Zero and 99/100 dollars"
    assert w(1000000) == "One million and 00/100 dollars"
    assert w(1) == "One and 00/100 dollars"
    # Python banker's rounding of 0.995 → 0.99 (correct/expected).
    assert w(0.995) == "Zero and 99/100 dollars"


# ─── Bank accounts CRUD ──────────────────────────────────────────────
@pytest.fixture(scope="module")
def bank_account(admin_h, dbc):
    r = requests.post(f"{API}/checks/bank-accounts", headers=admin_h, json={
        "nickname": "Test Ops " + str(int(time.time())),
        "bank_name": "First National Test",
        "routing_number": "123456789",
        "account_number": "9876543210",
        "next_check_number": 5001,
        "starting_balance": 10000.0,
    }, timeout=15)
    assert r.status_code == 200, r.text
    ba = r.json()
    yield ba
    # cleanup at module end
    dbc.checks.delete_many({"bank_account_id": ba["id"]})
    dbc.bank_accounts.delete_one({"id": ba["id"]})


def test_bank_account_created_masked(bank_account):
    assert bank_account["account_number_last4"] == "3210"
    assert "account_number" not in bank_account
    assert bank_account["next_check_number"] == 5001
    assert bank_account["current_balance"] == 10000.0
    assert bank_account["live_mode"] is False  # safety default


def test_bank_account_rejects_bad_routing(admin_h):
    r = requests.post(f"{API}/checks/bank-accounts", headers=admin_h, json={
        "nickname": "Bad",
        "bank_name": "X",
        "routing_number": "12345",  # too short
        "account_number": "12345",
    }, timeout=15)
    assert r.status_code == 422


# ─── Payee CRUD ──────────────────────────────────────────────────────
@pytest.fixture(scope="module")
def payee(admin_h, dbc):
    r = requests.post(f"{API}/checks/payees", headers=admin_h, json={
        "name": "AcmeSupply " + str(int(time.time())),
        "kind": "vendor",
        "email": "billing@acme.test",
    }, timeout=15).json()
    yield r
    dbc.check_payees.delete_one({"id": r["id"]})


def test_payee_created(payee):
    assert payee["kind"] == "vendor"
    assert payee["name"].startswith("AcmeSupply")


# ─── Check create + auto-increment ───────────────────────────────────
def test_check_number_autoincrements(admin_h, bank_account, payee, dbc):
    made = []
    for i in range(3):
        r = requests.post(f"{API}/checks/checks", headers=admin_h, json={
            "bank_account_id": bank_account["id"],
            "payee_id": payee["id"], "amount": 100 + i,
            "date": "2026-02-14", "memo": f"test {i}",
        }, timeout=15).json()
        made.append(r)
    numbers = [m["check_number"] for m in made]
    assert numbers == [5001, 5002, 5003], numbers
    assert all(m["status"] == "draft" for m in made)
    assert made[0]["amount_in_words"] == \
        "One hundred and 00/100 dollars"
    # cleanup those checks
    for m in made:
        dbc.checks.delete_one({"id": m["id"]})
    # Reset bank counter so downstream tests get a predictable base
    dbc.bank_accounts.update_one({"id": bank_account["id"]},
                                   {"$set": {"next_check_number": 5004}})


# ─── Print returns real PDF ──────────────────────────────────────────
def test_print_check_returns_real_pdf(admin_h, bank_account, payee, dbc):
    c = requests.post(f"{API}/checks/checks", headers=admin_h, json={
        "bank_account_id": bank_account["id"], "payee_id": payee["id"],
        "amount": 1234.56, "date": "2026-02-14", "memo": "PDF test",
        "category": "supplies",
    }, timeout=15).json()
    p = requests.post(f"{API}/checks/checks/{c['id']}/print",
                       headers=admin_h, timeout=15).json()
    assert p["status"] == "printed"
    assert p["pdf_url"].endswith("/pdf")
    pdf = requests.get(f"{API}/checks/{c['id']}/pdf",
                        headers=admin_h, timeout=20)
    assert pdf.status_code == 200
    assert pdf.headers.get("content-type", "").startswith("application/pdf")
    assert len(pdf.content) > 500
    # PDF preamble
    assert pdf.content[:4] == b"%PDF", "not a real PDF"
    # Non-silent warnings: MICR warning is conditional on font availability
    # (Phase 38 embeds GnuMICR when present). SAMPLE_MODE always fires on
    # a bank account with live_mode=False.
    warnings = pdf.headers.get("X-Check-Warnings", "")
    assert "SAMPLE_MODE" in warnings, warnings
    # If MICR fell back to placeholder, verify the loud watermark IS in
    # the (uncompressed) stream.
    if "TEST_ONLY_NOT_MICR_ENCODED" in warnings:
        assert b"TEST_ONLY_NOT_MICR_ENCODED" in pdf.content \
            or b"NOT NEGOTIABLE" in pdf.content, \
            "warning watermarks missing from PDF face"
    else:
        # MICR font loaded — the placeholder watermark must NOT appear.
        assert b"TEST_ONLY_NOT_MICR_ENCODED" not in pdf.content
        assert b"NOT NEGOTIABLE" in pdf.content, \
            "SAMPLE_MODE watermark missing from PDF face"
    dbc.checks.delete_one({"id": c["id"]})


# ─── Void ────────────────────────────────────────────────────────────
def test_void_check(admin_h, bank_account, payee, dbc):
    c = requests.post(f"{API}/checks/checks", headers=admin_h, json={
        "bank_account_id": bank_account["id"], "payee_id": payee["id"],
        "amount": 42.0, "date": "2026-02-14",
    }, timeout=15).json()
    v = requests.post(f"{API}/checks/checks/{c['id']}/void", headers=admin_h,
                       json={"reason": "duplicate"}, timeout=15).json()
    assert v["status"] == "voided"
    assert v["void_reason"] == "duplicate"
    # Still visible in register
    lst = requests.get(f"{API}/checks/checks?bank_account_id={bank_account['id']}",
                        headers=admin_h, timeout=15).json()
    assert any(x["id"] == c["id"] for x in lst["items"])
    dbc.checks.delete_one({"id": c["id"]})


# ─── Clear / Unclear round-trip ──────────────────────────────────────
def test_clear_and_unclear(admin_h, bank_account, payee, dbc):
    c = requests.post(f"{API}/checks/checks", headers=admin_h, json={
        "bank_account_id": bank_account["id"], "payee_id": payee["id"],
        "amount": 500.0, "date": "2026-02-14",
    }, timeout=15).json()
    cleared = requests.post(f"{API}/checks/checks/{c['id']}/mark-cleared",
                              headers=admin_h,
                              json={"cleared_amount": 500.0},
                              timeout=15).json()
    assert cleared["status"] == "cleared"
    # Bank balance should drop
    ba = requests.get(f"{API}/checks/bank-accounts",
                        headers=admin_h, timeout=15).json()
    curr = next(x for x in ba["items"] if x["id"] == bank_account["id"])
    assert curr["current_balance"] == 10000.0 - 500.0
    # Unclear reverses
    uncleared = requests.post(
        f"{API}/checks/checks/{c['id']}/mark-uncleared",
        headers=admin_h, timeout=15).json()
    assert uncleared["status"] in ("draft", "printed")
    ba2 = requests.get(f"{API}/checks/bank-accounts",
                         headers=admin_h, timeout=15).json()
    curr2 = next(x for x in ba2["items"] if x["id"] == bank_account["id"])
    assert curr2["current_balance"] == 10000.0
    dbc.checks.delete_one({"id": c["id"]})


# ─── Voided checks do NOT move balance ───────────────────────────────
def test_voided_does_not_move_balance(admin_h, bank_account, payee, dbc):
    starting = requests.get(f"{API}/checks/bank-accounts",
                              headers=admin_h, timeout=15).json()
    b0 = next(x for x in starting["items"]
                if x["id"] == bank_account["id"])["current_balance"]
    c = requests.post(f"{API}/checks/checks", headers=admin_h, json={
        "bank_account_id": bank_account["id"], "payee_id": payee["id"],
        "amount": 999.99, "date": "2026-02-14",
    }, timeout=15).json()
    requests.post(f"{API}/checks/checks/{c['id']}/void", headers=admin_h,
                    json={"reason": "test"}, timeout=15)
    ba = requests.get(f"{API}/checks/bank-accounts",
                        headers=admin_h, timeout=15).json()
    b1 = next(x for x in ba["items"]
                if x["id"] == bank_account["id"])["current_balance"]
    assert b0 == b1, f"balance moved {b0} → {b1} for voided check"
    dbc.checks.delete_one({"id": c["id"]})


# ─── Concurrency: two checks get different numbers ───────────────────
def test_concurrent_check_numbers_are_unique(admin_h, bank_account, payee, dbc):
    import concurrent.futures
    def _mk():
        return requests.post(f"{API}/checks/checks", headers=admin_h, json={
            "bank_account_id": bank_account["id"], "payee_id": payee["id"],
            "amount": 1.0, "date": "2026-02-14",
        }, timeout=15).json()
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as ex:
        out = list(ex.map(lambda _: _mk(), range(5)))
    nums = [c["check_number"] for c in out]
    assert len(set(nums)) == 5, f"duplicate check numbers: {nums}"
    for c in out:
        dbc.checks.delete_one({"id": c["id"]})


# ─── Tenant isolation ────────────────────────────────────────────────
def test_tenant_isolation(admin_h, sunbelt_admin_h, bank_account):
    # sunbelt admin can't see aquaterra's bank account
    r = requests.get(f"{API}/checks/bank-accounts",
                       headers=sunbelt_admin_h, timeout=15).json()
    assert not any(x["id"] == bank_account["id"] for x in r["items"])


# ─── Role gating ─────────────────────────────────────────────────────
def test_role_gating(tech_h, customer_h):
    for h in (tech_h, customer_h):
        r = requests.get(f"{API}/checks/bank-accounts", headers=h,
                          timeout=15)
        assert r.status_code == 403
        r2 = requests.get(f"{API}/checks/checks", headers=h, timeout=15)
        assert r2.status_code == 403
        r3 = requests.get(f"{API}/checks/analytics", headers=h, timeout=15)
        assert r3.status_code == 403


# ─── Cannot edit printed check amount ────────────────────────────────
def test_no_edit_amount_after_print(admin_h, bank_account, payee, dbc):
    c = requests.post(f"{API}/checks/checks", headers=admin_h, json={
        "bank_account_id": bank_account["id"], "payee_id": payee["id"],
        "amount": 10.0, "date": "2026-02-14",
    }, timeout=15).json()
    requests.post(f"{API}/checks/checks/{c['id']}/print",
                    headers=admin_h, timeout=15)
    # amount change on a printed check is rejected
    r = requests.patch(f"{API}/checks/checks/{c['id']}",
                        headers=admin_h, json={"amount": 500.0}, timeout=15)
    assert r.status_code == 409
    # memo edit still allowed
    r2 = requests.patch(f"{API}/checks/checks/{c['id']}",
                         headers=admin_h, json={"memo": "updated"}, timeout=15)
    assert r2.status_code == 200
    assert r2.json()["memo"] == "updated"
    dbc.checks.delete_one({"id": c["id"]})
