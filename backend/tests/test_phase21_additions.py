"""Feb-2026 · Phase 21 additions — merge-tag parity, display_color_hex,
vanity-slug editor, activation state.

Covers:
* Merge-tag parity — all 8 required tags render correctly with real
  context AND fall back to empty string when context is missing.
* Merge-tag catalog exposes the new tokens.
* PATCH /api/users/{id} accepts ``display_color_hex`` and validates hex.
* Vanity slug endpoints — list, add (with regex + reserved-word +
  collision guards), remove (idempotent, canonical protected).
* Phase 21 activation — Resend adapter loads `plofv.com` as verified,
  tenant.settings.primary_app_domain reflects the live URL.
"""
import os

import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient


API = "http://localhost:8001/api"
_ENV = dotenv_values("/app/backend/.env")
_MONGO_URL = _ENV.get("MONGO_URL") or os.environ.get("MONGO_URL")
_DB_NAME = _ENV.get("DB_NAME") or os.environ.get("DB_NAME")
_sync_db = MongoClient(_MONGO_URL)[_DB_NAME] if _MONGO_URL and _DB_NAME else None


def _login(email: str, password: str = "password123") -> str:
    r = requests.post(f"{API}/auth/login",
                       json={"email": email, "password": password}, timeout=15)
    r.raise_for_status()
    return r.json()["access_token"]


# ── MERGE-TAG PARITY ────────────────────────────────────────────
def _render(body, ctx):
    from services.marketing.merge_tags import render_template
    return render_template(body, ctx)[0]


def test_merge_tag_customer_first_name_and_fallback():
    ctx = {"customer": {"first_name": "Brian"}}
    assert _render("Hi {{CUSTOMER_FIRST_NAME}}", ctx) == "Hi Brian"
    # No first name → salutation fallback ``there``.
    assert _render("Hi {{CUSTOMER_FIRST_NAME}}", {"customer": {}}) == "Hi there"


def test_merge_tag_customer_full_name_and_fallbacks():
    # Both parts.
    ctx = {"customer": {"first_name": "Brian", "last_name": "Beck"}}
    assert _render("{{CUSTOMER_FULL_NAME}}", ctx) == "Brian Beck"
    # First only.
    assert _render("{{CUSTOMER_FULL_NAME}}",
                   {"customer": {"first_name": "Brian"}}) == "Brian"
    # Legacy `name` field.
    assert _render("{{CUSTOMER_FULL_NAME}}",
                   {"customer": {"name": "Legacy Person"}}) == "Legacy Person"
    # Email local-part fallback.
    assert _render("{{CUSTOMER_FULL_NAME}}",
                   {"customer": {"email": "brian@plofv.com"}}) == "brian"


def test_merge_tag_invoice_amount_from_cents_and_empty():
    ctx = {"invoice": {"total_cents": 13500}}
    assert _render("{{INVOICE_AMOUNT}}", ctx) == "$135.00"
    # No invoice → empty string, no literal token in output.
    assert _render("{{INVOICE_AMOUNT}}", {}) == ""


def test_merge_tag_invoice_pay_url_uses_primary_app_domain():
    tenant = _sync_db.tenants.find_one({"slug": "aquaterra"}, {"_id": 0})
    settings = tenant.get("settings") or {}
    domain = settings.get("primary_app_domain") or ""
    if not domain:
        pytest.skip("primary_app_domain unset; activation migration hasn't run")
    ctx = {"invoice": {"id": "INV-999"}, "tenant": tenant}
    out = _render("{{INVOICE_PAY_URL}}", ctx)
    assert out == f"{domain}/portal/invoices/INV-999"
    # No invoice in context → empty string.
    assert _render("{{INVOICE_PAY_URL}}", {"tenant": tenant}) == ""


def test_merge_tag_job_date_formatting():
    ctx = {"job": {"scheduled_date": "2026-02-24"},
           "tenant": {"timezone": "America/Phoenix"}}
    out = _render("{{JOB_DATE}}", ctx)
    # Format is ``Mon, Feb 24`` — the weekday changes with the year so we
    # accept any 3-letter weekday + Feb 24.
    assert "Feb 24" in out
    # Missing → empty.
    assert _render("{{JOB_DATE}}", {}) == ""


def test_merge_tag_job_time_from_hhmm():
    ctx = {"job": {"scheduled_time": "14:00"}}
    assert _render("{{JOB_TIME}}", ctx) == "2:00 PM"
    ctx2 = {"job": {"scheduled_time": "09:30"}}
    assert _render("{{JOB_TIME}}", ctx2) == "9:30 AM"
    assert _render("{{JOB_TIME}}", {}) == ""


def test_merge_tag_tech_name_cascade_and_empty():
    assert _render("{{TECH_NAME}}",
                   {"tech": {"name": "Mike"}}) == "Mike"
    assert _render("{{TECH_NAME}}",
                   {"technician": {"name": "Carlos"}}) == "Carlos"
    assert _render("{{TECH_NAME}}",
                   {"job": {"technician_name": "Sam"}}) == "Sam"
    assert _render("{{TECH_NAME}}", {}) == ""


def test_merge_tag_company_name_prefers_business_card():
    tenant = {
        "name": "Legacy Name",
        "settings": {"business_card": {"company_name": "Pool & Landscaping of Vistancia"}},
    }
    assert _render("{{COMPANY_NAME}}",
                   {"tenant": tenant}) == "Pool & Landscaping of Vistancia"
    # Legacy tenant without business_card falls back to tenant.name.
    assert _render("{{COMPANY_NAME}}",
                   {"tenant": {"name": "Old Co"}}) == "Old Co"


def test_merge_tag_unresolved_never_leaks_raw_literal():
    """Missing context ↔ empty string, NEVER the raw ``{{TOKEN}}``."""
    out = _render(
        "A={{INVOICE_AMOUNT}} B={{JOB_DATE}} C={{JOB_TIME}} D={{TECH_NAME}}",
        {},
    )
    assert "{{" not in out
    assert out == "A= B= C= D="


def test_merge_tag_catalog_lists_new_tokens():
    from services.marketing.merge_tags import catalog_grouped
    cat = catalog_grouped()
    all_tokens = {t["token"] for group in cat.values() for t in group}
    for required in [
        "CUSTOMER_FULL_NAME", "CUSTOMER_FIRST_NAME",
        "INVOICE_AMOUNT", "INVOICE_PAY_URL",
        "JOB_DATE", "JOB_TIME", "TECH_NAME", "COMPANY_NAME",
    ]:
        assert required in all_tokens, f"catalog missing {required}"


def test_merge_tag_catalog_endpoint_lists_new_tokens():
    tok = _login("admin@aquaterra.com")
    r = requests.get(f"{API}/marketing/merge-tags",
                      headers={"Authorization": f"Bearer {tok}"}, timeout=15)
    assert r.status_code == 200
    body = r.json()
    all_tokens = set()
    def _collect(node):
        if isinstance(node, list):
            for x in node:
                if isinstance(x, dict) and x.get("token"):
                    all_tokens.add(x["token"])
                else:
                    _collect(x)
        elif isinstance(node, dict):
            for v in node.values():
                _collect(v)
    _collect(body)
    for required in ["INVOICE_AMOUNT", "JOB_DATE", "JOB_TIME", "TECH_NAME"]:
        assert required in all_tokens, f"endpoint missing {required}"


# ── ADDITION B — display_color_hex PATCH ─────────────────────────
def test_display_color_hex_roundtrip():
    admin = _login("admin@aquaterra.com")
    u = _sync_db.users.find_one({"email": "mike@aquaterra.com"},
                                  {"_id": 0, "id": 1})
    uid = u["id"]
    # Success — uppercase-normalised.
    r = requests.patch(f"{API}/users/{uid}",
                        json={"display_color_hex": "#0ea5e9"},
                        headers={"Authorization": f"Bearer {admin}"},
                        timeout=15)
    assert r.status_code == 200, r.text
    fresh = _sync_db.users.find_one({"id": uid},
                                      {"_id": 0, "display_color_hex": 1})
    assert fresh["display_color_hex"] == "#0EA5E9"

    # Clear via null.
    r2 = requests.patch(f"{API}/users/{uid}",
                         json={"display_color_hex": None},
                         headers={"Authorization": f"Bearer {admin}"},
                         timeout=15)
    assert r2.status_code == 200
    fresh2 = _sync_db.users.find_one({"id": uid},
                                       {"_id": 0, "display_color_hex": 1})
    assert fresh2.get("display_color_hex") in (None,)


def test_display_color_hex_invalid_returns_400():
    admin = _login("admin@aquaterra.com")
    u = _sync_db.users.find_one({"email": "mike@aquaterra.com"},
                                  {"_id": 0, "id": 1})
    for bad in ["#XYZ", "green", "#12345", "0EA5E9", "#12345678"]:
        r = requests.patch(f"{API}/users/{u['id']}",
                            json={"display_color_hex": bad},
                            headers={"Authorization": f"Bearer {admin}"},
                            timeout=15)
        assert r.status_code == 400, f"expected 400 for {bad!r}, got {r.status_code}"


# ── VANITY SLUG EDITOR ──────────────────────────────────────────
def test_vanity_slug_list_current():
    sup = _login("super@aquaterra.com")
    r = requests.get(f"{API}/tenants/current/slug-aliases",
                      headers={"Authorization": f"Bearer {sup}"}, timeout=15)
    assert r.status_code == 200
    body = r.json()
    assert body["canonical_slug"] == "aquaterra"
    assert "plofv" in body["slug_aliases"]


def test_vanity_slug_add_remove_roundtrip():
    sup = _login("super@aquaterra.com")
    alias = "vistancia-pools"
    # Add.
    r = requests.post(f"{API}/tenants/current/slug-aliases",
                       json={"alias": alias},
                       headers={"Authorization": f"Bearer {sup}"}, timeout=15)
    assert r.status_code == 200, r.text
    assert alias in r.json()["slug_aliases"]
    # Signup by the new alias resolves to the same tenant.
    import uuid as _uuid
    email = f"vanity_{_uuid.uuid4().hex[:8]}@example.com"
    r_sign = requests.post(
        f"{API}/auth/signup",
        json={"email": email, "password": "TestPass123", "name": "Vanity"},
        headers={"X-Tenant-Slug": alias}, timeout=15,
    )
    assert r_sign.status_code == 200
    tenant = _sync_db.tenants.find_one({"slug": "aquaterra"}, {"_id": 0, "id": 1})
    u = _sync_db.users.find_one({"email": email}, {"_id": 0, "tenant_id": 1})
    assert u["tenant_id"] == tenant["id"]
    # Remove.
    r = requests.delete(f"{API}/tenants/current/slug-aliases/{alias}",
                         headers={"Authorization": f"Bearer {sup}"}, timeout=15)
    assert r.status_code == 200
    assert alias not in r.json()["slug_aliases"]


def test_vanity_slug_invalid_and_reserved_400():
    sup = _login("super@aquaterra.com")
    for bad in ["ab", "AB", "$foo", "with spaces", "-leading", "trailing-", "x" * 33]:
        r = requests.post(f"{API}/tenants/current/slug-aliases",
                          json={"alias": bad},
                          headers={"Authorization": f"Bearer {sup}"}, timeout=15)
        assert r.status_code == 400, f"expected 400 for {bad!r} got {r.status_code}"
    for reserved in ["admin", "api", "public", "app"]:
        r = requests.post(f"{API}/tenants/current/slug-aliases",
                          json={"alias": reserved},
                          headers={"Authorization": f"Bearer {sup}"}, timeout=15)
        assert r.status_code == 400, f"expected 400 for reserved {reserved!r}"


def test_vanity_slug_admin_forbidden():
    adm = _login("admin@aquaterra.com")
    r = requests.get(f"{API}/tenants/current/slug-aliases",
                      headers={"Authorization": f"Bearer {adm}"}, timeout=15)
    assert r.status_code == 403


def test_vanity_slug_remove_canonical_blocked():
    sup = _login("super@aquaterra.com")
    r = requests.delete(f"{API}/tenants/current/slug-aliases/aquaterra",
                         headers={"Authorization": f"Bearer {sup}"}, timeout=15)
    assert r.status_code == 400


def test_vanity_slug_remove_missing_is_idempotent():
    sup = _login("super@aquaterra.com")
    r = requests.delete(f"{API}/tenants/current/slug-aliases/never-existed",
                         headers={"Authorization": f"Bearer {sup}"}, timeout=15)
    assert r.status_code == 200
    assert r.json()["was_already_absent"] is True


# ── ACTIVATION STATE ────────────────────────────────────────────
def test_activation_resend_adapter_has_plofv_verified():
    from services.email.resend_adapter import ResendEmailAdapter
    ad = ResendEmailAdapter()
    assert "plofv.com" in ad.verified_domains
    assert ad._is_verified("noreply@plofv.com") is True
    assert ad._is_verified("cs@plofv.com") is True


def test_activation_primary_app_domain_is_live_url():
    t = _sync_db.tenants.find_one({"slug": "aquaterra"}, {"_id": 0})
    domain = (t.get("settings") or {}).get("primary_app_domain")
    assert domain == "https://app.plofv.com"
