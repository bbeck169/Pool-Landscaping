"""Phase 53d · Feb-2026 — EBIT response-shape contract lock.

Snapshots the shape of the two read endpoints so a future refactor
can't silently drop a required field. The tests exercise the LIVE
endpoint (not a mock) so any drift between the code and the wire
contract is caught immediately.

Fields locked here MUST stay stable. If a field must legitimately
change, update this test in the same PR — that keeps the contract
change intentional + reviewable.
"""
from __future__ import annotations

import os
import re
import uuid
from datetime import datetime, timezone

import requests

API = os.environ.get("BACKEND_URL", "http://localhost:8001") + "/api"
TIMEOUT = 30

ADMIN_EMAIL = "admin@aquaterra.com"
PW = "password123"

FIX_FROM = "2016-04-01"
FIX_TO = "2016-04-30"

_ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}(T.*)?$")


def _login(email: str) -> str:
    r = requests.post(f"{API}/auth/login",
                      json={"email": email, "password": PW}, timeout=TIMEOUT)
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _hdr(email: str = ADMIN_EMAIL) -> dict:
    return {"Authorization": f"Bearer {_login(email)}"}


# ═══════════════════════════════════════════════════════════════════
# GET /ebit/compute — LIVE compute response contract
# ═══════════════════════════════════════════════════════════════════
def test_compute_response_shape_locked():
    """Every field the web + mobile clients read from ``GET /ebit/compute``
    must be present with the documented type. Regression guard against
    silent contract drift."""
    r = requests.get(
        f"{API}/ebit/compute",
        headers=_hdr(),
        params={"range": "custom", "from": FIX_FROM, "to": FIX_TO,
                "revenue_basis": "cash"},
        timeout=TIMEOUT,
    )
    assert r.status_code == 200, r.text
    d = r.json()

    # ── Primary EBIT figures ─────────────────────────────────────
    for k in ("revenue", "cogs", "opex", "depreciation", "ebit"):
        assert k in d, f"compute response missing required key: {k}"
        assert isinstance(d[k], (int, float)), \
            f"compute.{k} expected number, got {type(d[k]).__name__}"

    # ── Identity: ebit = revenue - cogs - opex - depreciation ────
    assert abs(d["ebit"] - (d["revenue"] - d["cogs"] - d["opex"] - d["depreciation"])) < 0.01

    # ── Range + basis metadata ───────────────────────────────────
    assert d["range_from"] == FIX_FROM
    assert d["range_to"] == FIX_TO
    assert d["range_kind"] == "custom"
    assert d["revenue_basis"] == "cash"

    # ── Edit state (blanks on compute) ────────────────────────────
    for k in ("line_adjustments", "line_overrides"):
        assert k in d, f"compute response missing {k}"
        assert isinstance(d[k], dict)
        for line in ("revenue", "cogs", "opex", "depreciation"):
            assert line in d[k], f"compute.{k}.{line} missing"

    # ── Breakdown ────────────────────────────────────────────────
    b = d["breakdown"]
    assert isinstance(b, dict)
    for k in ("invoice_count", "line_count", "opex_payroll", "opex_other",
              "opex_by_category", "depreciation_by_category",
              "wages_by_role"):
        assert k in b, f"compute.breakdown.{k} missing"


def test_compute_rejects_invalid_range_via_openapi_literal():
    """Phase 53d — a bogus ``range`` returns 422 with a Pydantic
    literal_error listing every accepted value. This confirms the
    Literal type is actually driving OpenAPI validation instead of
    the description string."""
    r = requests.get(
        f"{API}/ebit/compute",
        headers=_hdr(),
        params={"range": "not-a-real-preset", "revenue_basis": "cash"},
        timeout=TIMEOUT,
    )
    assert r.status_code == 422
    msg = r.text.lower()
    for val in ("this_month", "last_month", "qtd", "ytd",
                "monthly", "quarterly", "custom"):
        assert val in msg, f"error message must list {val}"


def test_compute_rejects_invalid_revenue_basis_via_openapi_literal():
    r = requests.get(
        f"{API}/ebit/compute",
        headers=_hdr(),
        params={"range": "this_month", "revenue_basis": "banana"},
        timeout=TIMEOUT,
    )
    assert r.status_code == 422
    msg = r.text.lower()
    for val in ("cash", "accrual"):
        assert val in msg


# ═══════════════════════════════════════════════════════════════════
# GET /ebit/snapshots/{id} — saved-snapshot response contract
# ═══════════════════════════════════════════════════════════════════
def test_snapshot_response_shape_locked():
    """Every field returned by ``GET /ebit/snapshots/{id}`` must be
    present with the documented type. The web + mobile version-history
    modals + PDF exporter read these directly."""
    r_save = requests.post(
        f"{API}/ebit/snapshots",
        headers=_hdr(),
        json={"range_kind": "custom",
              "range_from": FIX_FROM, "range_to": FIX_TO,
              "revenue_basis": "cash",
              "note": "phase53d-contract-lock"},
        timeout=TIMEOUT,
    )
    assert r_save.status_code == 200, r_save.text
    sid = r_save.json()["id"]

    r = requests.get(f"{API}/ebit/snapshots/{sid}",
                     headers=_hdr(), timeout=TIMEOUT)
    assert r.status_code == 200, r.text
    d = r.json()

    # ── Identity ────────────────────────────────────────────────
    assert isinstance(d["id"], str) and d["id"] == sid
    assert isinstance(d["tenant_id"], str) and d["tenant_id"]

    # ── EBIT figures (post-edit "effective" values) ─────────────
    for k in ("revenue", "cogs", "opex", "depreciation", "ebit"):
        assert isinstance(d[k], (int, float)), \
            f"snapshot.{k} expected number"
    assert abs(d["ebit"] - (d["revenue"] - d["cogs"] - d["opex"] - d["depreciation"])) < 0.01

    # ── Range metadata ──────────────────────────────────────────
    assert d["range_kind"] == "custom"
    assert d["range_from"] == FIX_FROM
    assert d["range_to"] == FIX_TO
    assert d["revenue_basis"] == "cash"

    # ── Immutable versioning ────────────────────────────────────
    assert isinstance(d["version"], int) and d["version"] >= 1

    # ── Edit vectors ─────────────────────────────────────────────
    for k in ("line_adjustments", "line_overrides"):
        assert isinstance(d[k], dict)
        for line in ("revenue", "cogs", "opex", "depreciation"):
            assert line in d[k]

    # ── Breakdown ────────────────────────────────────────────────
    assert isinstance(d["breakdown"], dict)

    # ── Authorship + audit ───────────────────────────────────────
    assert isinstance(d["author_user_id"], str)
    # Phase 53d — author_display_name is contract-locked; it may be
    # empty for legacy rows but the key MUST be present.
    assert "author_display_name" in d
    assert isinstance(d["author_display_name"], str)
    assert isinstance(d["saved_at"], str)
    assert _ISO_RE.match(d["saved_at"]), \
        f"saved_at must be ISO-8601, got {d['saved_at']!r}"
    assert "note" in d
    assert isinstance(d["note"], str)


def test_snapshot_author_display_name_populates_from_user():
    """New saves must populate ``author_display_name`` from the
    caller's ``name`` (else ``email``) — the versions modal on both
    surfaces relies on this."""
    r_save = requests.post(
        f"{API}/ebit/snapshots",
        headers=_hdr(),
        json={"range_kind": "custom",
              "range_from": FIX_FROM, "range_to": FIX_TO,
              "revenue_basis": "cash"},
        timeout=TIMEOUT,
    )
    assert r_save.status_code == 200
    d = r_save.json()
    # Admin user has a name OR email — either way, this must be non-empty.
    assert d["author_display_name"], \
        "author_display_name should populate from user.name || user.email"


# ═══════════════════════════════════════════════════════════════════
# OpenAPI schema self-check
# ═══════════════════════════════════════════════════════════════════
def test_openapi_range_and_basis_enums_present():
    """Phase 53d — the ``range`` + ``revenue_basis`` query params on
    ``GET /ebit/compute`` must expose their enum values in OpenAPI
    (via ``Literal``). Any generator consuming the schema needs this."""
    r = requests.get(f"{API}/openapi.json", timeout=TIMEOUT)
    assert r.status_code == 200
    schema = r.json()
    op = schema["paths"]["/api/ebit/compute"]["get"]
    params = {p["name"]: p for p in op.get("parameters", [])}
    range_enum = params["range"]["schema"]["enum"]
    assert set(range_enum) == {
        "this_month", "last_month", "qtd", "ytd",
        "monthly", "quarterly", "custom",
    }
    basis_enum = params["revenue_basis"]["schema"]["enum"]
    assert set(basis_enum) == {"cash", "accrual"}
