"""Phase 38 · MICR font (GnuMICR) production-hardening tests.

Covers:
1. The bundled GnuMICR TTF is a valid TrueType file.
2. reportlab can register it via `pdfmetrics.registerFont(TTFont(...))`.
3. The `_render_check_pdf` helper embeds the font name into the PDF
   stream when the font is present.
4. When `MICR_FONT_PATH` points to a non-existent file the render still
   succeeds and the PDF ships the honest `TEST_ONLY_NOT_MICR_ENCODED`
   watermark — i.e. the missing-file path must NOT crash the endpoint.
5. `POST /api/checks/checks/{id}/print` + `GET /pdf` returns HTTP 200
   with `Content-Type: application/pdf`.
"""
import os
import sys
from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

_BE = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
_FE = dotenv_values(Path(__file__).resolve().parents[2] / "frontend" / ".env")
BASE = (_FE.get("EXPO_PUBLIC_BACKEND_URL") or "http://localhost:8001").rstrip("/")
API = f"{BASE}/api"

FONT_PATH = Path(__file__).resolve().parents[1] / "assets" / "fonts" / "gnumicr.ttf"


# ─── Unit: font file is real ─────────────────────────────────────────
def test_gnumicr_ttf_present_and_valid():
    assert FONT_PATH.exists(), f"missing GnuMICR at {FONT_PATH}"
    # TTF magic — SFNT scaler type is either 0x00010000 (Apple/Windows)
    # or 'OTTO' (OpenType) or 'true'/'typ1'. GnuMICR is Windows-format.
    head = FONT_PATH.read_bytes()[:4]
    assert head in (b"\x00\x01\x00\x00", b"true", b"OTTO"), head


# ─── Unit: reportlab can register the font ───────────────────────────
def test_reportlab_can_register_gnumicr():
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    # Any exception here means the TTF is malformed for reportlab.
    pdfmetrics.registerFont(TTFont("GnuMICR_TEST", str(FONT_PATH)))
    # `getFont` should now resolve.
    assert pdfmetrics.getFont("GnuMICR_TEST").fontName == "GnuMICR_TEST"


# ─── Unit: renderer embeds font when available ───────────────────────
def test_render_embeds_gnumicr_when_available(monkeypatch):
    """`_render_check_pdf` should load the font at render-time. The
    module-level `MICR_AVAILABLE` flag must flip True and the PDF must
    reference the `GnuMICR` font name."""
    # Reset the registration cache so this test drives the code path.
    from routers import checks as ck
    monkeypatch.setattr(ck, "_MICR_REGISTERED", False)
    monkeypatch.setattr(ck, "MICR_AVAILABLE", False)
    monkeypatch.setenv("MICR_FONT_PATH", str(FONT_PATH))

    pdf = ck._render_check_pdf(
        {"check_number": 5099, "amount": 12.34, "date": "2026-02-15",
         "memo": "phase-38", "amount_in_words": "Twelve and 34/100 dollars"},
        {"bank_name": "Test Bank", "routing_number": "123456789",
         "account_number_last4": "4321", "live_mode": False,
         # account_number_encrypted intentionally missing → _decrypt
         # returns empty string; harmless for this render path.
         },
        {"name": "Acme Vendor"},
        {"name": "Aquaterra Pool"},
    )
    assert pdf[:4] == b"%PDF"
    assert ck.MICR_AVAILABLE is True
    assert b"GnuMICR" in pdf, "PDF should reference the embedded GnuMICR font"


# ─── Unit: missing-file fallback does NOT crash ──────────────────────
def test_render_falls_back_when_font_missing(monkeypatch, caplog):
    """`MICR_FONT_PATH` pointing at a bogus file must NOT crash the
    render — it should log a warning and fall back to Courier-Bold."""
    from routers import checks as ck
    monkeypatch.setattr(ck, "_MICR_REGISTERED", False)
    monkeypatch.setattr(ck, "_MICR_WARNED", False)
    monkeypatch.setattr(ck, "MICR_AVAILABLE", False)
    monkeypatch.setenv("MICR_FONT_PATH", "/nonexistent/path/does-not-exist.ttf")

    pdf = ck._render_check_pdf(
        {"check_number": 5100, "amount": 1.0, "date": "2026-02-16",
         "memo": "fallback", "amount_in_words": "One and 00/100 dollars"},
        {"bank_name": "Bank X", "routing_number": "999999999",
         "account_number_last4": "0000", "live_mode": False},
        {"name": "Acme"},
        {"name": "Aquaterra"},
    )
    assert pdf[:4] == b"%PDF"
    assert ck.MICR_AVAILABLE is False
    # PDF should NOT reference GnuMICR (font missing).
    assert b"GnuMICR" not in pdf
    # Placeholder watermark IS baked into the PDF face when MICR is missing.
    assert b"TEST_ONLY_NOT_MICR_ENCODED" in pdf


# ─── Integration: /print + /pdf returns application/pdf ──────────────
def _login(email, pw="password123"):
    r = requests.post(f"{API}/auth/login",
                       json={"email": email, "password": pw}, timeout=15)
    r.raise_for_status()
    return r.json()


@pytest.fixture(scope="module")
def admin_h():
    return {"Authorization": f"Bearer {_login('admin@aquaterra.com')['access_token']}"}


def test_print_endpoint_returns_pdf(admin_h):
    # Look up (or create) a bank account + payee for this admin's tenant.
    ba_resp = requests.get(f"{API}/checks/bank-accounts", headers=admin_h, timeout=10).json()
    ba_list = ba_resp.get("items", []) if isinstance(ba_resp, dict) else ba_resp
    if not ba_list:
        ba = requests.post(f"{API}/checks/bank-accounts", headers=admin_h, json={
            "bank_name": "Phase38 Bank", "routing_number": "123456789",
            "account_number": "8887776665554321", "starting_check_number": 9001,
        }, timeout=10).json()
    else:
        ba = ba_list[0]
    payees_resp = requests.get(f"{API}/checks/payees", headers=admin_h, timeout=10).json()
    payees = payees_resp.get("items", []) if isinstance(payees_resp, dict) else payees_resp
    if not payees:
        payee = requests.post(f"{API}/checks/payees", headers=admin_h, json={
            "name": "Phase38 Vendor", "type": "vendor",
        }, timeout=10).json()
    else:
        payee = payees[0]

    check = requests.post(f"{API}/checks/checks", headers=admin_h, json={
        "bank_account_id": ba["id"], "payee_id": payee["id"],
        "amount": 88.88, "date": "2026-02-17", "memo": "phase-38 int",
        "category": "supplies",
    }, timeout=15).json()
    assert check.get("id"), check

    printed = requests.post(f"{API}/checks/checks/{check['id']}/print",
                             headers=admin_h, timeout=15).json()
    assert printed.get("status") == "printed", printed

    pdf = requests.get(f"{API}/checks/{check['id']}/pdf",
                        headers=admin_h, timeout=20)
    assert pdf.status_code == 200
    assert pdf.headers.get("content-type", "").startswith("application/pdf")
    assert pdf.content[:4] == b"%PDF"
    warnings = pdf.headers.get("X-Check-Warnings", "")
    # SAMPLE_MODE is always present on a non-live bank account.
    assert "SAMPLE_MODE" in warnings, warnings

    # Save a sample PDF for user inspection.
    sample = Path("/tmp") / f"sample_check_phase38_{check['check_number']}.pdf"
    sample.write_bytes(pdf.content)
    assert sample.stat().st_size > 500

    # Cleanup.
    requests.delete(f"{API}/checks/checks/{check['id']}", headers=admin_h, timeout=10)
