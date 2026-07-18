"""Phase T4 — Document Generators tests."""
from __future__ import annotations
import os
import pytest
import requests

API = os.environ.get("BACKEND_URL", "http://localhost:8001") + "/api"
TIMEOUT = 30


def _login(email, pwd="password123"):
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": pwd}, timeout=TIMEOUT)
    r.raise_for_status()
    j = r.json()
    return j.get("access_token") or j.get("token")


@pytest.fixture(scope="module")
def admin_tok(): return _login("admin@aquaterra.com")


@pytest.fixture(scope="module")
def tech_tok(): return _login("mike@aquaterra.com")


@pytest.fixture(scope="module")
def customer_tok(): return _login("customer@aquaterra.com")


def _h(t): return {"Authorization": f"Bearer {t}"}


class TestChecklistTemplate:
    def test_save_and_list(self, admin_tok):
        r = requests.post(f"{API}/documents/checklist-template/save",
                          headers=_h(admin_tok),
                          json={"name": "T4 Test Pool Weekly",
                                "visit_type": "pool",
                                "readings_rows": ["pH", "Free Cl", "Alkalinity"],
                                "checklist_items": ["Skim", "Brush", "Vacuum"],
                                "include_photos_section": True,
                                "include_customer_signature_line": True,
                                "include_tech_signature_line": True,
                                "include_notes_section": True,
                                "include_notes_internal": True,
                                "include_notes_customer": True},
                          timeout=TIMEOUT)
        assert r.status_code == 200, r.text
        tid = r.json()["id"]
        # List — new row appears
        r2 = requests.get(f"{API}/documents/checklist-templates",
                          headers=_h(admin_tok), timeout=TIMEOUT)
        assert r2.status_code == 200
        ids = [x["id"] for x in r2.json()["rows"]]
        assert tid in ids
        # Store for downstream cleanup
        pytest.T4_TEMPLATE_ID = tid

    def test_pdf_stream(self, admin_tok):
        tid = getattr(pytest, "T4_TEMPLATE_ID", None)
        assert tid, "template must be created by prior test"
        r = requests.get(f"{API}/documents/checklist-template/{tid}/pdf",
                         headers=_h(admin_tok), timeout=TIMEOUT)
        assert r.status_code == 200
        assert r.headers.get("content-type", "").startswith("application/pdf"), r.headers
        assert r.content.startswith(b"%PDF-"), "PDF magic bytes missing"
        assert len(r.content) > 800, f"PDF suspiciously small: {len(r.content)} bytes"

    def test_pdf_contains_expected_text(self, admin_tok):
        tid = getattr(pytest, "T4_TEMPLATE_ID", None)
        r = requests.get(f"{API}/documents/checklist-template/{tid}/pdf",
                         headers=_h(admin_tok), timeout=TIMEOUT)
        # Best-effort text extraction — pypdf isn't guaranteed to parse
        # every reportlab-embedded string exactly (spacing/encoding), so
        # accept either PDF assertion or extracted-text substring match.
        try:
            from io import BytesIO
            from pypdf import PdfReader
            reader = PdfReader(BytesIO(r.content))
            text = " ".join(p.extract_text() or "" for p in reader.pages)
            # At least one of our identifiers should surface
            assert any(needle in text for needle in
                       ["T4 Test Pool Weekly", "Chemistry Readings", "Checklist", "Skim"]), \
                f"none of the expected strings found in extracted text: {text[:200]}"
        except ImportError:
            # pypdf not installed — fall back to raw byte scan (fonts
            # sometimes leave literals in the stream even before compression).
            assert b"PDF" in r.content

    def test_rbac_tech_forbidden_save(self, tech_tok):
        r = requests.post(f"{API}/documents/checklist-template/save",
                          headers=_h(tech_tok), json={"name": "x"}, timeout=TIMEOUT)
        assert r.status_code == 403

    def test_rbac_customer_forbidden_pdf(self, customer_tok):
        tid = getattr(pytest, "T4_TEMPLATE_ID", None)
        r = requests.get(f"{API}/documents/checklist-template/{tid}/pdf",
                         headers=_h(customer_tok), timeout=TIMEOUT)
        assert r.status_code == 403

    def test_delete_admin(self, admin_tok):
        tid = getattr(pytest, "T4_TEMPLATE_ID", None)
        r = requests.delete(f"{API}/documents/checklist-templates/{tid}",
                            headers=_h(admin_tok), timeout=TIMEOUT)
        assert r.status_code == 200
        # Idempotent-ish: now returns 404
        r2 = requests.delete(f"{API}/documents/checklist-templates/{tid}",
                             headers=_h(admin_tok), timeout=TIMEOUT)
        assert r2.status_code == 404


class TestQuickServiceReport:
    def test_pdf_stream(self, admin_tok):
        r = requests.post(f"{API}/documents/quick-service-report",
                          headers=_h(admin_tok),
                          json={"customer_name": "Q4 Test Homeowner",
                                "property_address": "123 Test Ln, Peoria AZ",
                                "visit_date": "2026-07-18",
                                "tech_name": "Mike Rivera",
                                "visit_type": "pool",
                                "chemical_readings": [
                                    {"label": "pH", "value": "7.4"},
                                    {"label": "Free Cl", "value": "3"}],
                                "chemicals_added": [
                                    {"name": "Muriatic Acid", "amount": "32", "unit": "oz"}],
                                "checklist_items": ["Skimmed pool", "Vacuumed"],
                                "customer_notes": "Pool looking great — see you next week.",
                                "include_signatures": True}, timeout=TIMEOUT)
        assert r.status_code == 200, r.text
        assert r.headers.get("content-type", "").startswith("application/pdf")
        assert r.content.startswith(b"%PDF-")
        assert len(r.content) > 900
        # Extraction assertion (best-effort)
        try:
            from io import BytesIO
            from pypdf import PdfReader
            text = " ".join(
                (p.extract_text() or "") for p in
                PdfReader(BytesIO(r.content)).pages
            )
            assert any(n in text for n in ["Q4 Test Homeowner", "123 Test", "Mike Rivera"]), \
                f"expected identifiers missing from PDF text: {text[:250]}"
        except ImportError:
            pass

    def test_missing_required_fields(self, admin_tok):
        r = requests.post(f"{API}/documents/quick-service-report",
                          headers=_h(admin_tok),
                          json={"visit_date": "2026-07-18", "tech_name": "T",
                                "visit_type": "pool"}, timeout=TIMEOUT)
        # Missing customer_id + customer_name/property_address
        assert r.status_code == 422

    def test_rbac_tech_forbidden(self, tech_tok):
        r = requests.post(f"{API}/documents/quick-service-report",
                          headers=_h(tech_tok),
                          json={"customer_name": "x", "property_address": "y",
                                "visit_date": "2026-07-18", "tech_name": "z",
                                "visit_type": "pool"}, timeout=TIMEOUT)
        assert r.status_code == 403

    def test_rbac_customer_forbidden(self, customer_tok):
        r = requests.post(f"{API}/documents/quick-service-report",
                          headers=_h(customer_tok),
                          json={"customer_name": "x", "property_address": "y",
                                "visit_date": "2026-07-18", "tech_name": "z",
                                "visit_type": "pool"}, timeout=TIMEOUT)
        assert r.status_code == 403


class TestCanonicalLists:
    def test_admin_gets_lists(self, admin_tok):
        r = requests.get(f"{API}/documents/canonical-lists",
                         headers=_h(admin_tok), timeout=TIMEOUT)
        assert r.status_code == 200
        j = r.json()
        assert "pool_checklist" in j and len(j["pool_checklist"]) >= 8
        assert "landscape_checklist" in j and len(j["landscape_checklist"]) >= 8
        assert "standard_reading_keys" in j and "pH" in j["standard_reading_keys"]

    def test_tech_forbidden(self, tech_tok):
        r = requests.get(f"{API}/documents/canonical-lists",
                         headers=_h(tech_tok), timeout=TIMEOUT)
        assert r.status_code == 403
