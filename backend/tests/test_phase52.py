"""Phase 52 backend tests — 5 Phase 51 fixes + Phase 52.A + env-key handoffs."""
import os
import re
import datetime as dt
import subprocess
from pathlib import Path

import pytest
import requests

BASE = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
if not BASE:
    with open("/app/frontend/.env") as f:
        for line in f:
            if line.startswith("REACT_APP_BACKEND_URL="):
                BASE = line.split("=", 1)[1].strip().rstrip("/")
                break
API = f"{BASE}/api"
TIMEOUT = 30

CREDS = {
    "admin": ("admin@aquaterra.com", "password123"),
    "tech": ("mike@aquaterra.com", "password123"),
    "landscaper": ("landscaper@aquaterra.com", "password123"),
}


def _login(role):
    email, pw = CREDS[role]
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": pw}, timeout=TIMEOUT)
    assert r.status_code == 200, f"login {role}: {r.status_code} {r.text}"
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def admin_h():
    return {"Authorization": f"Bearer {_login('admin')}"}


@pytest.fixture(scope="module")
def tech_h():
    return {"Authorization": f"Bearer {_login('tech')}"}


# ─────────────── Fix 1 · api.delete() removed from frontend ───────────
def test_fix1_no_api_delete_callsites():
    src = Path("/app/frontend/src")
    hits = []
    for p in src.rglob("*"):
        if p.suffix in (".js", ".jsx", ".ts", ".tsx") and not p.name.endswith(".d.ts"):
            try:
                txt = p.read_text(errors="ignore")
            except Exception:
                continue
            for i, line in enumerate(txt.splitlines(), 1):
                if re.search(r"\bapi\.delete\(", line):
                    hits.append(f"{p}:{i}: {line.strip()}")
    print(f"api.delete( callsites found: {len(hits)}")
    for h in hits[:20]:
        print(h)
    assert len(hits) == 0, f"Expected 0 api.delete() callsites, found {len(hits)}"


# ─────────────── Fix 2 · payroll schema ───────────────────────────────
def test_fix2_payroll_schema(admin_h, tech_h):
    r = requests.get(f"{API}/cfo/payroll", params={"period": "2026-02"}, headers=admin_h, timeout=TIMEOUT)
    assert r.status_code == 200, r.text
    j = r.json()
    for k in ("this_month_cents", "ytd_cents", "total_cents", "employee_count", "employees"):
        assert k in j, f"missing {k}: {list(j.keys())}"
    assert isinstance(j["this_month_cents"], int)
    assert isinstance(j["ytd_cents"], int)
    assert isinstance(j["total_cents"], int)
    assert j.get("mocked") is False
    # tech 403
    r2 = requests.get(f"{API}/cfo/payroll", params={"period": "2026-02"}, headers=tech_h, timeout=TIMEOUT)
    assert r2.status_code == 403


# ─────────────── Fix 3 · today filter + seed_mike_today_job idempotent ─
def test_fix3_today_filter_and_idempotent(tech_h):
    today = dt.date.today().isoformat()
    r1 = requests.get(f"{API}/jobs", params={"scheduled_date": today}, headers=tech_h, timeout=TIMEOUT)
    assert r1.status_code == 200, r1.text
    d1 = r1.json()
    items1 = d1.get("items") if isinstance(d1, dict) else d1
    assert isinstance(items1, list)
    print(f"Mike today jobs count: {len(items1)}")
    assert len(items1) >= 1, f"Expected >=1 job for mike today ({today}); got {len(items1)}"
    r2 = requests.get(f"{API}/jobs", params={"scheduled_date": today}, headers=tech_h, timeout=TIMEOUT)
    d2 = r2.json()
    items2 = d2.get("items") if isinstance(d2, dict) else d2
    assert len(items2) == len(items1), f"idempotency failed: {len(items1)} vs {len(items2)}"


# ─────────────── Fix 4 · ap_aging gone; ap_aging_detailed present ─────
def test_fix4_dashboard_no_legacy_ap_aging(admin_h):
    r = requests.get(f"{API}/cfo/dashboard", params={"period": "mtd"}, headers=admin_h, timeout=TIMEOUT)
    assert r.status_code == 200, r.text
    j = r.json()
    assert "ap_aging" not in j, f"legacy ap_aging still present: {list(j.keys())}"
    assert "ap_aging_detailed" in j, f"ap_aging_detailed missing: {list(j.keys())}"
    ad = j["ap_aging_detailed"]
    for k in ("current_cents", "1_30_cents", "31_60_cents", "61_90_cents", "over_90_cents", "total_open_cents"):
        assert k in ad, f"ap_aging_detailed missing {k}: {list(ad.keys())}"


# ─────────────── Fix 5 · recurring_template_id filter ─────────────────
def test_fix5_recurring_template_id_filter(admin_h):
    # Create customer + template
    c = requests.post(f"{API}/customers", headers=admin_h, json={
        "name": "TEST_P52_TPL", "email": "test_p52_tpl@t.com", "phone": "555-0002"
    }, timeout=TIMEOUT)
    assert c.status_code in (200, 201), c.text
    cid = c.json()["id"]
    start = (dt.date.today() - dt.timedelta(days=1)).isoformat()
    tpl = requests.post(f"{API}/recurring-jobs", headers=admin_h, json={
        "customer_id": cid, "service_type": "P52 Weekly", "frequency": "weekly",
        "day_of_week": dt.date.today().weekday(), "start_date": start,
        "price_cents": 11100, "active": True,
    }, timeout=TIMEOUT)
    assert tpl.status_code in (200, 201), tpl.text
    tid = tpl.json()["id"]
    through = (dt.date.today() + dt.timedelta(days=21)).isoformat()
    g = requests.post(f"{API}/recurring-jobs/{tid}/generate", params={"through": through},
                       headers=admin_h, timeout=TIMEOUT)
    assert g.status_code in (200, 201), g.text
    inserted = g.json().get("inserted", 0)
    assert inserted > 0, f"expected >0 inserted; got {g.json()}"
    # Filter
    r = requests.get(f"{API}/jobs", params={"recurring_template_id": tid}, headers=admin_h, timeout=TIMEOUT)
    assert r.status_code == 200, r.text
    data = r.json()
    items = data.get("items") if isinstance(data, dict) else data
    assert len(items) >= inserted, f"filter returned {len(items)} < inserted {inserted}"
    for job in items:
        assert job.get("recurring_template_id") == tid, f"leak: {job.get('id')} tpl={job.get('recurring_template_id')}"


# ─────────────── 52.A · least-profitable-services ─────────────────────
def test_52a_least_profitable_services(admin_h, tech_h):
    r = requests.get(f"{API}/reports/least-profitable-services",
                      params={"month": "2026-06", "limit": 3}, headers=admin_h, timeout=TIMEOUT)
    assert r.status_code == 200, r.text
    j = r.json()
    assert j.get("month") == "2026-06"
    assert "services" in j and isinstance(j["services"], list)
    assert "total_evaluated" in j
    for s in j["services"]:
        for k in ("service_type", "job_count", "revenue_cents", "cost_cents",
                  "margin_cents", "margin_pct", "avg_hours_per_job"):
            assert k in s, f"service missing {k}: {list(s.keys())}"
    # ascending by margin_pct
    pcts = [s["margin_pct"] for s in j["services"]]
    assert pcts == sorted(pcts), f"not ascending: {pcts}"
    # tech 403
    r2 = requests.get(f"{API}/reports/least-profitable-services",
                       params={"month": "2026-06"}, headers=tech_h, timeout=TIMEOUT)
    assert r2.status_code == 403


# ─────────────── 52.A · price-increase-suggestions ────────────────────
def test_52a_price_increase_suggestions_cache_and_403(admin_h, tech_h):
    # 1st call — may or may not use cache from a prior test run. We'll
    # drop the cache to be safe.
    from pymongo import MongoClient
    mongo = MongoClient(os.environ.get("MONGO_URL", "mongodb://localhost:27017"))
    db_name = os.environ.get("DB_NAME", "aquaterra")
    mongo[db_name].pricing_suggestions_cache.delete_many({"month": "2026-06"})

    r1 = requests.post(f"{API}/cfo/price-increase-suggestions",
                       headers=admin_h, json={"month": "2026-06"}, timeout=60)
    assert r1.status_code == 200, r1.text
    j1 = r1.json()
    assert j1.get("month") == "2026-06"
    assert "suggestions" in j1
    assert j1.get("cached") is False, f"first call should not be cached: {j1}"
    print(f"suggestions count: {len(j1['suggestions'])} raw_error={j1.get('raw_error')}")

    # 2nd call — if first produced any suggestions, this should be cached.
    r2 = requests.post(f"{API}/cfo/price-increase-suggestions",
                       headers=admin_h, json={"month": "2026-06"}, timeout=60)
    assert r2.status_code == 200, r2.text
    j2 = r2.json()
    if j1["suggestions"]:
        assert j2.get("cached") is True, f"second call should be cached when suggestions exist: {j2}"

    # null month accepted (defaults to previous month)
    r3 = requests.post(f"{API}/cfo/price-increase-suggestions",
                       headers=admin_h, json={}, timeout=60)
    assert r3.status_code == 200, r3.text

    # tech 403
    r4 = requests.post(f"{API}/cfo/price-increase-suggestions",
                       headers=tech_h, json={"month": "2026-06"}, timeout=TIMEOUT)
    assert r4.status_code == 403


# ─────────────── 52.A · pricing-insights email history ────────────────
def test_52a_pricing_insights_email_history(admin_h, tech_h):
    r = requests.get(f"{API}/reports/pricing-insights/email-history",
                      params={"limit": 10}, headers=admin_h, timeout=TIMEOUT)
    assert r.status_code == 200, r.text
    j = r.json()
    assert "items" in j and "count" in j
    assert isinstance(j["items"], list)
    r2 = requests.get(f"{API}/reports/pricing-insights/email-history",
                       params={"limit": 10}, headers=tech_h, timeout=TIMEOUT)
    assert r2.status_code == 403


# ─────────────── Stripe · /stripe/health ──────────────────────────────
def test_stripe_health(admin_h, tech_h):
    r = requests.get(f"{API}/stripe/health", headers=admin_h, timeout=TIMEOUT)
    assert r.status_code == 200, r.text
    j = r.json()
    for k in ("configured", "secret_key_configured", "publishable_key_configured",
              "webhook_secret_configured", "mode"):
        assert k in j, f"missing {k}: {list(j.keys())}"
    assert j["secret_key_configured"] is True
    assert j["publishable_key_configured"] is True
    assert j["webhook_secret_configured"] is True
    assert j["mode"] == "live", f"mode={j['mode']}"
    # No leaked key value.
    body = r.text
    assert "sk_live_" not in body and "sk_test_" not in body and "whsec_" not in body, \
        "Stripe health leaked a key value!"
    # tech 403
    r2 = requests.get(f"{API}/stripe/health", headers=tech_h, timeout=TIMEOUT)
    assert r2.status_code == 403


# ─────────────── Stripe · /publishable-key (public) ───────────────────
def test_stripe_publishable_key_public():
    r = requests.get(f"{API}/stripe/publishable-key", timeout=TIMEOUT)
    assert r.status_code == 200, f"{r.status_code} {r.text}"
    j = r.json()
    assert "key" in j and "mode" in j
    assert j["key"], "publishable key missing"
    assert j["key"].startswith("pk_live_") or j["key"].startswith("pk_test_"), \
        f"unexpected prefix (masked)"
    assert j["mode"] in ("live", "test")
    # Log prefix + length only, not the full value.
    key = j["key"]
    print(f"publishable-key prefix={key[:8]}... len={len(key)} mode={j['mode']}")


# ─────────────── Stripe · webhook signature verification ──────────────
def test_stripe_webhook_bad_signature():
    r = requests.post(f"{API}/stripe/webhook",
                       headers={"stripe-signature": "t=1,v1=deadbeef",
                                "Content-Type": "application/json"},
                       data='{"type":"payment_intent.succeeded"}', timeout=TIMEOUT)
    assert r.status_code == 400, f"{r.status_code} {r.text}"
    body = r.text
    assert body.lower().find("invalid signature") >= 0 or "invalid signature" in body
    # secret must NOT leak
    assert "whsec_" not in body, "webhook secret leaked in error body!"

def test_stripe_webhook_missing_signature():
    r = requests.post(f"{API}/stripe/webhook",
                       headers={"Content-Type": "application/json"},
                       data='{"type":"payment_intent.succeeded"}', timeout=TIMEOUT)
    assert r.status_code == 400, f"expected 400, got {r.status_code}: {r.text}"
    assert "whsec_" not in r.text


# ─────────────── Zillow · /zillow/health ──────────────────────────────
def test_zillow_health(admin_h, tech_h):
    r = requests.get(f"{API}/zillow/health", headers=admin_h, timeout=TIMEOUT)
    assert r.status_code == 200, r.text
    j = r.json()
    assert "configured" in j
    assert j["configured"] is True
    # No key leak
    assert "ak_" not in r.text
    r2 = requests.get(f"{API}/zillow/health", headers=tech_h, timeout=TIMEOUT)
    assert r2.status_code == 403


# ─────────────── Env key confidentiality in backend logs ──────────────
def test_env_keys_not_in_backend_logs():
    log_paths = [
        "/var/log/supervisor/backend.err.log",
        "/var/log/supervisor/backend.out.log",
    ]
    patterns = [r"sk_live_[A-Za-z0-9]+", r"sk_test_[A-Za-z0-9]+", r"whsec_[A-Za-z0-9]+"]
    leaks = []
    for p in log_paths:
        if not os.path.exists(p):
            continue
        try:
            # tail last 500 lines
            out = subprocess.check_output(["tail", "-n", "500", p], stderr=subprocess.STDOUT).decode(errors="ignore")
        except Exception:
            continue
        for pat in patterns:
            for m in re.finditer(pat, out):
                leaks.append(f"{p}: {m.group(0)[:8]}...")
    assert not leaks, f"env key material leaked into backend logs: {leaks}"
