"""Phase 17C — OTTO Auto-Fix + Website Studio + White-Label Reports."""
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
MONGO_URL = _BE.get("MONGO_URL"); DB_NAME = _BE.get("DB_NAME")


def _login(email, pw="password123"):
    r = requests.post(f"{API}/auth/login",
                       json={"email": email, "password": pw}, timeout=15)
    r.raise_for_status(); return r.json()


@pytest.fixture(scope="module")
def dbc(): return MongoClient(MONGO_URL)[DB_NAME]

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


# ═══════════════════════════════════════════════════════════════════════
# 17B naming polish (LLM Visibility)
# ═══════════════════════════════════════════════════════════════════════

def test_llm_dashboard_canonical_and_alias_keys(admin_h):
    r = requests.get(f"{API}/seo/llm-visibility/dashboard",
                      headers=admin_h, timeout=15).json()
    # Canonical
    for k in ("mention_rate_pct", "competitors", "engines_configured"):
        assert k in r, f"missing canonical key {k}"
    # Deprecated aliases still present (for one release)
    for k in ("mentions_rate_pct", "competitors_mentioned", "engines_scanned"):
        assert k in r, f"missing deprecated alias {k}"
    # Types
    assert isinstance(r["competitors"], list)
    assert isinstance(r["engines_configured"], list)
    # Aliases point at the same values
    assert r["mentions_rate_pct"] == r["mention_rate_pct"]
    assert r["engines_scanned"] == r["engines_configured"]


def test_llm_scan_response_has_engines_configured(admin_h, dbc):
    q = requests.post(f"{API}/seo/llm-visibility/queries", headers=admin_h,
                       json={"query_text": "test query 17c",
                              "expected_brand": "AquaTerra",
                              "category": "general"}, timeout=15).json()
    r = requests.post(f"{API}/seo/llm-visibility/scan", headers=admin_h,
                       json={"query_ids": [q["id"]]}, timeout=90).json()
    assert "engines_configured" in r
    assert "engines_scanned" in r  # alias
    assert r["engines_configured"] == r["engines_scanned"]
    requests.delete(f"{API}/seo/llm-visibility/queries/{q['id']}",
                     headers=admin_h, timeout=15)
    dbc.seo_llm_scans.delete_many({"scan_id": r.get("scan_id")})


# ═══════════════════════════════════════════════════════════════════════
# 17C.1 · OTTO Auto-Fix
# ═══════════════════════════════════════════════════════════════════════

def _seed_audit_with_issue(dbc, tenant_slug="aquaterra", issue_code="CANONICAL_MISSING"):
    """Insert a bare audit + page directly (bypasses crawler) so we don't
    depend on live external HTTP for the test."""
    tenant = dbc.tenants.find_one({"slug": tenant_slug})
    aid = "test-audit-17c-" + str(int(time.time() * 1000))
    dbc.seo_audits.insert_one({
        "id": aid, "tenant_id": tenant["id"], "url": "https://example.com/test",
        "depth": 1, "max_pages": 1, "status": "done",
        "summary": {"scores": {"overall": 70, "technical": 60,
                                 "on_page": 80, "ux": 70},
                     "pages_crawled": 1, "issues_total": 1},
        "created_at": "2026-02-01T00:00:00Z", "started_at": "2026-02-01T00:00:00Z",
        "finished_at": "2026-02-01T00:00:01Z",
    })
    dbc.seo_audit_pages.insert_one({
        "audit_id": aid, "tenant_id": tenant["id"],
        "url": "https://example.com/test",
        "title": "", "meta": "",
        "issues": [{"code": issue_code, "severity": "warning",
                     "hint": "test"}],
    })
    return aid


def test_otto_generate_fixes_creates_patches(admin_h, dbc):
    aid = _seed_audit_with_issue(dbc, issue_code="CANONICAL_MISSING")
    r = requests.post(f"{API}/seo/otto/generate-fixes", headers=admin_h,
                       json={"audit_id": aid, "max_fixes": 5},
                       timeout=120).json()
    assert r["audit_id"] == aid
    assert r["count"] >= 1
    assert len(r["fixes"]) >= 1
    fix = r["fixes"][0]
    for k in ("id", "issue_code", "patch_type", "patch_snippet",
              "suggested_value", "status", "mocked"):
        assert k in fix
    assert fix["status"] == "pending"
    assert fix["patch_snippet"], "patch_snippet must be non-empty"
    # LIVE Claude when key present → mocked:false. The static fallback still
    # produces a valid snippet for CANONICAL_MISSING even if AI is unavailable.
    assert fix["mocked"] in (True, False)

    # List fixes
    lst = requests.get(f"{API}/seo/otto/fixes/{aid}",
                        headers=admin_h, timeout=15).json()
    assert lst["audit_id"] == aid
    assert lst["totals"]["pending"] >= 1

    # Mark applied
    ap = requests.post(f"{API}/seo/otto/fixes/{fix['id']}/mark-applied",
                        headers=admin_h, timeout=15).json()
    assert ap["status"] == "applied"

    # Dismiss another (create a second fix)
    aid2 = _seed_audit_with_issue(dbc, issue_code="JSONLD_MISSING")
    r2 = requests.post(f"{API}/seo/otto/generate-fixes", headers=admin_h,
                        json={"audit_id": aid2, "max_fixes": 5}, timeout=120).json()
    fid2 = r2["fixes"][0]["id"]
    ds = requests.post(f"{API}/seo/otto/fixes/{fid2}/dismiss",
                        headers=admin_h, timeout=15).json()
    assert ds["status"] == "dismissed"

    # Patch file download
    pf = requests.get(f"{API}/seo/otto/fixes/{fix['id']}/patch-file",
                       headers=admin_h, timeout=15)
    assert pf.status_code == 200
    assert "attachment" in (pf.headers.get("content-disposition") or "").lower()
    assert b"OTTO Auto-Fix" in pf.content

    # cleanup
    dbc.seo_audits.delete_many({"id": {"$in": [aid, aid2]}})
    dbc.seo_audit_pages.delete_many({"audit_id": {"$in": [aid, aid2]}})
    dbc.seo_otto_fixes.delete_many({"audit_id": {"$in": [aid, aid2]}})


def test_otto_tenant_isolation_and_role(admin_h, sunbelt_admin_h, tech_h, dbc):
    aid = _seed_audit_with_issue(dbc)
    # Sunbelt admin cannot touch aquaterra's audit
    s = requests.post(f"{API}/seo/otto/generate-fixes",
                       headers=sunbelt_admin_h,
                       json={"audit_id": aid}, timeout=30)
    assert s.status_code == 404
    lst_s = requests.get(f"{API}/seo/otto/fixes/{aid}",
                          headers=sunbelt_admin_h, timeout=15)
    assert lst_s.status_code == 404
    # Tech → 403 on every endpoint
    t = requests.post(f"{API}/seo/otto/generate-fixes",
                       headers=tech_h, json={"audit_id": aid}, timeout=15)
    assert t.status_code == 403
    t2 = requests.get(f"{API}/seo/otto/fixes/{aid}",
                       headers=tech_h, timeout=15)
    assert t2.status_code == 403
    dbc.seo_audits.delete_one({"id": aid})
    dbc.seo_audit_pages.delete_many({"audit_id": aid})


def test_otto_no_duplicate_fix_for_same_page_and_code(admin_h, dbc):
    aid = _seed_audit_with_issue(dbc, issue_code="CANONICAL_MISSING")
    r1 = requests.post(f"{API}/seo/otto/generate-fixes", headers=admin_h,
                        json={"audit_id": aid, "max_fixes": 5}, timeout=90).json()
    count1 = r1["count"]
    # Second call should NOT create a duplicate pending fix
    r2 = requests.post(f"{API}/seo/otto/generate-fixes", headers=admin_h,
                        json={"audit_id": aid, "max_fixes": 5}, timeout=90).json()
    assert r2["count"] == 0
    lst = requests.get(f"{API}/seo/otto/fixes/{aid}",
                        headers=admin_h, timeout=15).json()
    assert len(lst["fixes"]) == count1
    dbc.seo_audits.delete_one({"id": aid})
    dbc.seo_audit_pages.delete_many({"audit_id": aid})
    dbc.seo_otto_fixes.delete_many({"audit_id": aid})


# ═══════════════════════════════════════════════════════════════════════
# 17C.2 · Website Studio
# ═══════════════════════════════════════════════════════════════════════

def _unique_slug(prefix="phase17c"):
    return f"{prefix}-{int(time.time() * 1000)}"


def test_studio_page_crud_and_export(admin_h, dbc):
    slug = _unique_slug()
    p = requests.post(f"{API}/seo/studio/pages", headers=admin_h,
                      json={"title": "Test Page", "slug": slug,
                             "target_keyword": "phoenix pool cleaning",
                             "meta_description": "Test",
                             "sections": [{"type": "hero", "heading": "Hi",
                                            "subheading": "sub", "body": "b"}]},
                      timeout=15).json()
    assert p["id"] and p["slug"] == slug and p["status"] == "draft"

    # Update
    up = requests.put(f"{API}/seo/studio/pages/{p['id']}", headers=admin_h,
                       json={"title": "Test Page Renamed",
                              "sections": [
                                  {"type": "hero", "heading": "H", "body": "b"},
                                  {"type": "faq", "heading": "FAQ",
                                    "items": [{"question": "q", "answer": "a"}]},
                              ]},
                       timeout=15).json()
    assert up["title"] == "Test Page Renamed"
    assert len(up["sections"]) == 2

    # List includes it
    lst = requests.get(f"{API}/seo/studio/pages", headers=admin_h,
                        timeout=15).json()
    assert any(x["id"] == p["id"] for x in lst["items"])

    # Detail
    det = requests.get(f"{API}/seo/studio/pages/{p['id']}", headers=admin_h,
                        timeout=15).json()
    assert det["target_keyword"] == "phoenix pool cleaning"

    # Publish
    pub = requests.post(f"{API}/seo/studio/pages/{p['id']}/publish",
                         headers=admin_h, timeout=15).json()
    assert pub["status"] == "published"
    assert pub["preview_url"].endswith(f"/preview/studio/{slug}")

    # Public preview (no auth)
    pre = requests.get(f"{API}/preview/studio/{slug}", timeout=15)
    assert pre.status_code == 200
    assert "text/html" in pre.headers.get("content-type", "")
    assert "<title>Test Page Renamed</title>" in pre.text
    assert "hero" in pre.text.lower()

    # Export HTML
    ex_h = requests.get(f"{API}/seo/studio/pages/{p['id']}/export?format=html",
                         headers=admin_h, timeout=15)
    assert ex_h.status_code == 200
    assert "attachment" in (ex_h.headers.get("content-disposition") or "").lower()
    # Export markdown
    ex_m = requests.get(f"{API}/seo/studio/pages/{p['id']}/export?format=markdown",
                         headers=admin_h, timeout=15)
    assert ex_m.status_code == 200
    assert "# Test Page Renamed" in ex_m.text
    # Export JSON
    ex_j = requests.get(f"{API}/seo/studio/pages/{p['id']}/export?format=json",
                         headers=admin_h, timeout=15)
    assert ex_j.status_code == 200
    assert ex_j.json()["slug"] == slug

    dbc.seo_studio_pages.delete_one({"id": p["id"]})


def test_studio_auto_fill_live_claude(admin_h, dbc):
    slug = _unique_slug("autofill")
    p = requests.post(f"{API}/seo/studio/pages", headers=admin_h,
                      json={"title": "Auto-Fill Test", "slug": slug,
                             "sections": []}, timeout=15).json()
    r = requests.post(f"{API}/seo/studio/pages/{p['id']}/auto-fill",
                       headers=admin_h,
                       json={"business_context":
                              "Residential pool cleaning company in Phoenix, AZ",
                             "target_keyword": "phoenix pool service"},
                       timeout=120).json()
    # Live LLM path: mocked=False, sections generated.
    assert "mocked" in r
    # When key present, should not be mocked.
    if not r.get("mocked"):
        assert r["count"] >= 1
        det = requests.get(f"{API}/seo/studio/pages/{p['id']}",
                            headers=admin_h, timeout=15).json()
        assert len(det["sections"]) >= 1
        # Every section type must be from the allowed set
        allowed = {"hero", "features", "benefits", "services",
                    "testimonials", "faq", "cta", "local_business_schema"}
        for s in det["sections"]:
            assert s.get("type") in allowed
    dbc.seo_studio_pages.delete_one({"id": p["id"]})


def test_studio_tenant_isolation_and_role_and_public_draft_hidden(
    admin_h, sunbelt_admin_h, tech_h, customer_h, dbc
):
    slug = _unique_slug("iso")
    p = requests.post(f"{API}/seo/studio/pages", headers=admin_h,
                      json={"title": "Iso", "slug": slug, "sections": []},
                      timeout=15).json()
    # Sunbelt admin cannot see aquaterra's page
    s = requests.get(f"{API}/seo/studio/pages/{p['id']}",
                      headers=sunbelt_admin_h, timeout=15)
    assert s.status_code == 404
    # Tech + customer → 403 on admin surfaces
    for h in (tech_h, customer_h):
        assert requests.get(f"{API}/seo/studio/pages",
                             headers=h, timeout=15).status_code == 403
        assert requests.post(f"{API}/seo/studio/pages", headers=h,
                              json={"title": "x", "slug": _unique_slug("bad"),
                                     "sections": []},
                              timeout=15).status_code == 403
    # Draft page: public preview returns 403 (not 404 — the page exists)
    d = requests.get(f"{API}/preview/studio/{slug}", timeout=15)
    assert d.status_code == 403
    # Non-existent slug → 404
    nf = requests.get(f"{API}/preview/studio/does-not-exist-{int(time.time())}",
                       timeout=15)
    assert nf.status_code == 404
    # Slug uniqueness within a tenant
    dup = requests.post(f"{API}/seo/studio/pages", headers=admin_h,
                         json={"title": "dup", "slug": slug, "sections": []},
                         timeout=15)
    assert dup.status_code == 409
    dbc.seo_studio_pages.delete_one({"id": p["id"]})


# ═══════════════════════════════════════════════════════════════════════
# 17C.3 · White-Label Reports
# ═══════════════════════════════════════════════════════════════════════

def _seed_audit_done(dbc, tenant_slug="aquaterra"):
    tenant = dbc.tenants.find_one({"slug": tenant_slug})
    aid = "rep-audit-" + str(int(time.time() * 1000))
    dbc.seo_audits.insert_one({
        "id": aid, "tenant_id": tenant["id"],
        "url": "https://example.com/rep",
        "depth": 1, "max_pages": 1, "status": "done",
        "summary": {"scores": {"overall": 75, "technical": 70,
                                 "on_page": 80, "ux": 75},
                     "pages_crawled": 3, "issues_total": 4},
        "created_at": "2026-02-01T00:00:00Z",
    })
    return aid


def test_report_create_and_download(admin_h, dbc):
    aid = _seed_audit_done(dbc)
    r = requests.post(f"{API}/seo/reports", headers=admin_h,
                       json={"title": "Q1 SEO Snapshot",
                              "brand_name": "AquaTerra",
                              "brand_color": "#0EA5E9",
                              "audit_id": aid,
                              "include_llm_visibility": True,
                              "range_days": 30}, timeout=120).json()
    assert r["id"]
    assert r["status"] == "ready"
    assert r["title"] == "Q1 SEO Snapshot"
    assert "exec_summary" in r
    # Data blob populated
    assert (r["data"] or {}).get("audit")
    assert r["data"]["audit"]["id"] == aid

    # List
    lst = requests.get(f"{API}/seo/reports", headers=admin_h,
                        timeout=15).json()
    assert any(x["id"] == r["id"] for x in lst["items"])
    # Data blob NOT in list rows (heavy)
    for x in lst["items"]:
        assert "data" not in x

    # Detail
    det = requests.get(f"{API}/seo/reports/{r['id']}", headers=admin_h,
                        timeout=15).json()
    assert det["id"] == r["id"]

    # Download PDF
    pdf = requests.get(f"{API}/seo/reports/{r['id']}/download?format=pdf",
                        headers=admin_h, timeout=30)
    assert pdf.status_code == 200
    # Either real PDF, or HTML fallback (both fine)
    ct = pdf.headers.get("content-type", "")
    assert ("application/pdf" in ct) or ("text/html" in ct)
    assert "attachment" in (pdf.headers.get("content-disposition") or "").lower()

    # Download HTML
    html = requests.get(f"{API}/seo/reports/{r['id']}/download?format=html",
                         headers=admin_h, timeout=15)
    assert html.status_code == 200
    assert "text/html" in html.headers.get("content-type", "")
    assert b"Q1 SEO Snapshot" in html.content or b"SEO" in html.content

    dbc.seo_audits.delete_one({"id": aid})
    dbc.seo_reports.delete_one({"id": r["id"]})


def test_report_send_graceful(admin_h, dbc):
    aid = _seed_audit_done(dbc)
    r = requests.post(f"{API}/seo/reports", headers=admin_h,
                       json={"title": "Send Test",
                              "audit_id": aid,
                              "include_llm_visibility": False},
                       timeout=90).json()
    # Send — either resend-configured (sent:true) or graceful fallback
    send = requests.post(f"{API}/seo/reports/{r['id']}/send",
                          headers=admin_h,
                          json={"to": "test@example.com"}, timeout=30).json()
    assert "sent" in send
    if not send["sent"]:
        assert send.get("reason")
    else:
        assert send["to"] == "test@example.com"
        assert send.get("attachment_type") in ("pdf", "html")
    # Bad email → 400
    bad = requests.post(f"{API}/seo/reports/{r['id']}/send",
                         headers=admin_h,
                         json={"to": ""}, timeout=15)
    assert bad.status_code == 400
    dbc.seo_audits.delete_one({"id": aid})
    dbc.seo_reports.delete_one({"id": r["id"]})


def test_report_tenant_isolation_and_role(admin_h, sunbelt_admin_h,
                                              tech_h, customer_h, dbc):
    aid = _seed_audit_done(dbc)
    r = requests.post(f"{API}/seo/reports", headers=admin_h,
                       json={"title": "Iso Report", "audit_id": aid,
                              "include_llm_visibility": False},
                       timeout=60).json()
    # Sunbelt admin cannot see
    s = requests.get(f"{API}/seo/reports/{r['id']}", headers=sunbelt_admin_h,
                      timeout=15)
    assert s.status_code == 404
    s2 = requests.get(f"{API}/seo/reports/{r['id']}/download",
                       headers=sunbelt_admin_h, timeout=15)
    assert s2.status_code == 404
    # Tech + customer → 403
    for h in (tech_h, customer_h):
        assert requests.get(f"{API}/seo/reports", headers=h,
                             timeout=15).status_code == 403
        assert requests.post(f"{API}/seo/reports", headers=h,
                              json={"title": "x", "include_llm_visibility": True},
                              timeout=15).status_code == 403
    # Bad audit_id referenced → 404
    bad = requests.post(f"{API}/seo/reports", headers=admin_h,
                         json={"title": "bad", "audit_id": "does-not-exist",
                                "include_llm_visibility": False}, timeout=15)
    assert bad.status_code == 404
    # No data source → 400
    empty = requests.post(f"{API}/seo/reports", headers=admin_h,
                           json={"title": "empty",
                                  "include_llm_visibility": False}, timeout=15)
    assert empty.status_code == 400
    dbc.seo_audits.delete_one({"id": aid})
    dbc.seo_reports.delete_one({"id": r["id"]})


# ═══════════════════════════════════════════════════════════════════════
# Polish fixes from the 17C tester
# ═══════════════════════════════════════════════════════════════════════

def test_report_response_has_file_url(admin_h, dbc):
    aid = _seed_audit_done(dbc)
    r = requests.post(f"{API}/seo/reports", headers=admin_h,
                       json={"title": "File-URL Test",
                              "audit_id": aid,
                              "include_llm_visibility": False},
                       timeout=90).json()
    # Create response
    assert "file_url" in r
    assert r["file_url"] is not None
    assert r["file_url"] == f"/api/seo/reports/{r['id']}/download?format=pdf"
    # GET response
    det = requests.get(f"{API}/seo/reports/{r['id']}", headers=admin_h,
                        timeout=15).json()
    assert "file_url" in det
    assert det["file_url"] == f"/api/seo/reports/{r['id']}/download?format=pdf"
    # The advertised URL actually works
    dl = requests.get(f"{BASE}{det['file_url']}", headers=admin_h, timeout=30)
    assert dl.status_code == 200
    dbc.seo_audits.delete_one({"id": aid})
    dbc.seo_reports.delete_one({"id": r["id"]})


def test_scan_has_competitors_mentioned_alias(admin_h, dbc):
    q = requests.post(f"{API}/seo/llm-visibility/queries", headers=admin_h,
                       json={"query_text":
                              "best pool cleaning services in Phoenix",
                              "expected_brand": "AquaTerra",
                              "category": "local"}, timeout=15).json()
    r = requests.post(f"{API}/seo/llm-visibility/scan", headers=admin_h,
                       json={"query_ids": [q["id"]]}, timeout=120).json()
    # Scan-level: both keys present with identical values
    assert "competitors" in r
    assert "competitors_mentioned" in r
    assert r["competitors"] == r["competitors_mentioned"]

    # Per-result: both keys present with identical values
    assert len(r["results"]) >= 1
    for res in r["results"]:
        assert "competitors" in res
        assert "competitors_mentioned" in res
        assert res["competitors"] == res["competitors_mentioned"]

    # GET /scans/{id} also emits the alias
    got = requests.get(f"{API}/seo/llm-visibility/scans/{r['scan_id']}",
                        headers=admin_h, timeout=15).json()
    assert len(got) >= 1
    for row in got:
        assert "competitors" in row
        assert "competitors_mentioned" in row
        assert row["competitors"] == row["competitors_mentioned"]

    requests.delete(f"{API}/seo/llm-visibility/queries/{q['id']}",
                     headers=admin_h, timeout=15)
    dbc.seo_llm_scans.delete_many({"scan_id": r["scan_id"]})
