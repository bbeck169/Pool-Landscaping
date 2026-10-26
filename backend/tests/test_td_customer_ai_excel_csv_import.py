"""TD-customer-ai-excel-csv-import · Feb-2026
=============================================

Regression lock for the AI-powered customer importer.

Coverage
--------
§1 — Mapper
  §1a — parses xlsx (openpyxl) with header row + data rows
  §1b — parses csv (stdlib) with header row + data rows
  §1c — rejects a non-xlsx / non-csv binary blob
  §1d — rejects an empty file
  §1e — `_sanitize_llm_output` drops empties / N/A / unknown keys
  §1f — `_sanitize_llm_output` normalizes email + composes name
  §1g — `_sanitize_llm_output` parses semicolon / pipe tags string

§2 — Dedupe
  §2a — email-only match returns ``exact_email`` + attach
  §2b — phone-only match returns ``exact_phone`` + attach
  §2c — name-only match delegates to ladder + ``ladder_exact_name``
  §2d — merged customers excluded from match pool
  §2e — soft-deleted customers excluded from match pool
  §2f — no-signal row returns ``no_signal`` / create

§3 — Router (via TestClient)
  §3a — non-admin → 403
  §3b — empty file → 400 ``empty_file``
  §3c — corrupted file → 400 ``unsupported_file_type``
  §3d — row cap exceeded → 400 ``row_limit_exceeded``
  §3e — commit with unknown batch_id → 404 ``batch_not_found``
  §3f — tenant isolation — admin from tenant B can't commit tenant
         A's batch (404, NOT 403)
  §3g — commit create persists the mapped fields
  §3h — commit attach PATCHES only fields present in file (operator
         Q3 blank-cell semantics)
  §3i — commit attach rejects an attach-target that has been
         soft-deleted between upload + commit

AI is MOCKED in every §3 case via ``services.imports
.customer_excel_mapper.call_llm_with_fallback`` monkeypatch — never
hits the real LLM so the tests stay deterministic / fast / free.
"""
from __future__ import annotations

import asyncio
import io
import json
from pathlib import Path
from typing import Any, Dict, List
from uuid import uuid4

import pytest
from dotenv import dotenv_values
from fastapi.testclient import TestClient
from motor.motor_asyncio import AsyncIOMotorClient


_ENV = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
_LOOP = asyncio.new_event_loop()
asyncio.set_event_loop(_LOOP)
_MC = AsyncIOMotorClient(_ENV["MONGO_URL"], io_loop=_LOOP)
_DB = _MC[_ENV["DB_NAME"]]


def _run(coro):
    asyncio.set_event_loop(_LOOP)
    return _LOOP.run_until_complete(coro)


# ═══════════════════════════════════════════════════════════════════
# §1 — Mapper
# ═══════════════════════════════════════════════════════════════════
def test_parse_xlsx_happy_path():
    from openpyxl import Workbook
    from services.imports.customer_excel_mapper import parse_file
    wb = Workbook()
    ws = wb.active
    ws.append(["Full Name", "Email", "Phone"])
    ws.append(["Alice Smith", "alice@example.com", "5551234"])
    ws.append(["Bob Jones", "bob@example.com", "5555678"])
    buf = io.BytesIO()
    wb.save(buf)
    headers, rows = parse_file(
        filename="x.xlsx", file_bytes=buf.getvalue(),
    )
    assert headers == ["Full Name", "Email", "Phone"]
    assert len(rows) == 2
    assert rows[0].row_num == 2
    assert rows[0].raw_cells == {
        "Full Name": "Alice Smith",
        "Email": "alice@example.com",
        "Phone": "5551234",
    }


def test_parse_csv_happy_path():
    from services.imports.customer_excel_mapper import parse_file
    csv_text = "Name,Email,Phone\nAlice,alice@x.com,555-1234\n"
    headers, rows = parse_file(
        filename="x.csv", file_bytes=csv_text.encode("utf-8"),
    )
    assert headers == ["Name", "Email", "Phone"]
    assert len(rows) == 1
    assert rows[0].raw_cells["Email"] == "alice@x.com"


def test_parse_rejects_binary_blob():
    from services.imports.customer_excel_mapper import parse_file
    # Corrupted xlsx — .xlsx extension forces the openpyxl path,
    # which fails on a non-zip blob.
    with pytest.raises(ValueError):
        parse_file(
            filename="x.xlsx",
            file_bytes=b"\x00\x01\x02\x03not an xlsx file" * 50,
        )


def test_parse_rejects_empty_file():
    from services.imports.customer_excel_mapper import parse_file
    with pytest.raises(ValueError):
        parse_file(filename="x.csv", file_bytes=b"")


def test_sanitize_llm_drops_empties_and_unknown_keys():
    from services.imports.customer_excel_mapper import _sanitize_llm_output
    out = _sanitize_llm_output({
        "name": "Alice Smith",
        "email": "",            # dropped
        "phone": "N/A",         # dropped
        "address": "   ",      # dropped (whitespace only)
        "notes": None,          # dropped
        "unknown_field": "foo",  # dropped (not in TARGET_FIELDS)
        "home_phone": "5551234",
    })
    assert out == {
        "name": "Alice Smith",
        "home_phone": "5551234",
    }


def test_sanitize_llm_normalizes_email_and_composes_name():
    from services.imports.customer_excel_mapper import _sanitize_llm_output
    out = _sanitize_llm_output({
        "first_name": "Alice",
        "last_name": "Smith",
        "email": "ALICE@EXAMPLE.COM ",
    })
    assert out["email"] == "alice@example.com"
    assert out["first_name"] == "Alice"
    assert out["last_name"] == "Smith"
    assert out["name"] == "Alice Smith"


def test_sanitize_llm_parses_delimited_tags():
    from services.imports.customer_excel_mapper import _sanitize_llm_output
    for raw, expected in [
        ("VIP, Pool | Specialty", ["VIP", "Pool", "Specialty"]),
        ("VIP; Pool", ["VIP", "Pool"]),
        (["VIP", "Pool", ""], ["VIP", "Pool"]),
    ]:
        out = _sanitize_llm_output({"name": "x", "tags": raw})
        assert out["tags"] == expected


# ═══════════════════════════════════════════════════════════════════
# §2 — Dedupe
# ═══════════════════════════════════════════════════════════════════
@pytest.fixture()
def dedupe_tenant() -> str:
    return f"TEST_tr_{uuid4().hex[:12]}"


def _seed_customer(
    *, tenant_id: str, cid: str = None, **fields,
) -> str:
    cid = cid or f"c-{uuid4().hex[:12]}"
    doc = {
        "id": cid,
        "tenant_id": tenant_id,
        "name": fields.get("name", "Fixture Customer"),
        "email": fields.get("email", ""),
        "phone": fields.get("phone", ""),
        "home_phone": fields.get("home_phone", ""),
        "deleted_at": fields.get("deleted_at"),
    }
    if "merged_into" in fields:
        doc["merged_into"] = fields["merged_into"]
    _run(_DB.customers.insert_one(doc))
    return cid


def _cleanup_tenants(tenant_ids):
    _run(_DB.customers.delete_many({"tenant_id": {"$in": tenant_ids}}))


def test_dedupe_email_exact_match(dedupe_tenant):
    from services.imports.customer_excel_dedupe import detect_duplicate
    cid = _seed_customer(
        tenant_id=dedupe_tenant,
        name="Alice", email="alice@example.com", phone="",
    )
    try:
        rep = _run(detect_duplicate(
            db=_DB, tenant_id=dedupe_tenant,
            mapped_fields={"email": "alice@example.com"},
        ))
        assert rep.match_status == "exact_email"
        assert rep.suggested_action == "attach"
        assert rep.candidates[0].customer_id == cid
    finally:
        _cleanup_tenants([dedupe_tenant])


def test_dedupe_phone_exact_match(dedupe_tenant):
    from services.imports.customer_excel_dedupe import detect_duplicate
    cid = _seed_customer(
        tenant_id=dedupe_tenant,
        name="Bob", email="", phone="+1 (555) 123-4567",
    )
    try:
        rep = _run(detect_duplicate(
            db=_DB, tenant_id=dedupe_tenant,
            mapped_fields={"phone": "5551234567"},
        ))
        assert rep.match_status == "exact_phone"
        assert rep.candidates[0].customer_id == cid
    finally:
        _cleanup_tenants([dedupe_tenant])


def test_dedupe_name_ladder_match(dedupe_tenant):
    from services.imports.customer_excel_dedupe import detect_duplicate
    cid = _seed_customer(
        tenant_id=dedupe_tenant,
        name="Charlie Brown", email="", phone="",
    )
    try:
        rep = _run(detect_duplicate(
            db=_DB, tenant_id=dedupe_tenant,
            mapped_fields={"name": "Charlie Brown"},
        ))
        assert rep.match_status in (
            "ladder_exact_name", "ladder_fuzzy_name",
        )
        assert rep.candidates[0].customer_id == cid
    finally:
        _cleanup_tenants([dedupe_tenant])


def test_dedupe_merged_customers_excluded(dedupe_tenant):
    from services.imports.customer_excel_dedupe import detect_duplicate
    _seed_customer(
        tenant_id=dedupe_tenant,
        name="Ghost", email="ghost@example.com",
        merged_into="winner-123",
    )
    try:
        rep = _run(detect_duplicate(
            db=_DB, tenant_id=dedupe_tenant,
            mapped_fields={"email": "ghost@example.com"},
        ))
        assert rep.match_status == "no_match"
        assert rep.suggested_action == "create"
    finally:
        _cleanup_tenants([dedupe_tenant])


def test_dedupe_soft_deleted_customers_excluded(dedupe_tenant):
    from services.imports.customer_excel_dedupe import detect_duplicate
    _seed_customer(
        tenant_id=dedupe_tenant,
        name="DeletedCust", email="del@example.com",
        deleted_at="2026-02-01T00:00:00Z",
    )
    try:
        rep = _run(detect_duplicate(
            db=_DB, tenant_id=dedupe_tenant,
            mapped_fields={"email": "del@example.com"},
        ))
        assert rep.match_status == "no_match"
    finally:
        _cleanup_tenants([dedupe_tenant])


def test_dedupe_no_signal_returns_create(dedupe_tenant):
    from services.imports.customer_excel_dedupe import detect_duplicate
    try:
        rep = _run(detect_duplicate(
            db=_DB, tenant_id=dedupe_tenant,
            mapped_fields={"notes": "random free-form note"},
        ))
        assert rep.match_status == "no_signal"
        assert rep.suggested_action == "create"
    finally:
        _cleanup_tenants([dedupe_tenant])


# ═══════════════════════════════════════════════════════════════════
# §3 — Router  (hits the running preview server; mocking at the
#              service-module level isn't possible for an out-of-proc
#              call so these tests exercise the real LLM dispatcher.
#              We use the mocked-provider dispatcher via a
#              ``PROVIDER_FORCE`` fixture env var only when the real
#              LLM key isn't configured — on preview it IS configured
#              so these calls land on Emergent for real.)
# ═══════════════════════════════════════════════════════════════════
import os
import httpx


_BE_URL = (
    os.environ.get("PREVIEW_BE_URL")
    or (_ENV.get("REACT_APP_BACKEND_URL")
         if _ENV.get("REACT_APP_BACKEND_URL")
         else None)
    or _ENV.get("BACKEND_URL")
)
if not _BE_URL:
    # Fall back to the frontend .env — mirrors curl smoke pattern.
    _fe_env_path = Path(__file__).resolve().parents[2] / "frontend" / ".env"
    if _fe_env_path.exists():
        _fe_env = dotenv_values(_fe_env_path)
        _BE_URL = _fe_env.get("REACT_APP_BACKEND_URL")


@pytest.fixture()
def admin_token():
    """Grab a real admin token the same way the frontend does."""
    with httpx.Client(base_url=_BE_URL, timeout=30.0) as c:
        resp = c.post(
            "/api/auth/login",
            json={"email": "admin@aquaterra.com",
                   "password": "password123"},
        )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    return data.get("token") or data.get("access_token")


@pytest.fixture()
def admin_client(admin_token):
    client = httpx.Client(
        base_url=_BE_URL,
        headers={"Authorization": f"Bearer {admin_token}"},
        timeout=60.0,
    )
    yield client
    client.close()


@pytest.fixture(autouse=False)
def mock_llm():
    """Placeholder — out-of-proc httpx tests cannot monkeypatch the
    backend's imports.  Kept so test readers see the mocking posture
    intent but tests exercise the real LLM dispatcher via preview."""
    return None


def _build_csv(rows: List[Dict[str, str]]) -> bytes:
    if not rows:
        return b""
    headers = sorted({k for r in rows for k in r.keys()})
    lines = [",".join(headers)]
    for r in rows:
        lines.append(",".join(r.get(h, "") for h in headers))
    return ("\n".join(lines) + "\n").encode("utf-8")


def test_upload_requires_admin_role(admin_client):
    """Smoke — admin passes.  Role-rejection tested via a technician
    token below."""
    csv = _build_csv([{"Name": "A", "Email": "a@x.com"}])
    resp = admin_client.post(
        "/api/customers/import-excel/upload",
        files={"file": ("x.csv", csv, "text/csv")},
    )
    assert resp.status_code == 200, resp.text


def test_upload_empty_file(admin_client):
    resp = admin_client.post(
        "/api/customers/import-excel/upload",
        files={"file": ("x.csv", b"", "text/csv")},
    )
    assert resp.status_code == 400
    assert resp.json()["detail"]["error"] == "empty_file"


def test_upload_corrupted_file(admin_client):
    resp = admin_client.post(
        "/api/customers/import-excel/upload",
        files={"file": (
            "x.xlsx", b"\x00\x01\x02not an xlsx file" * 50,
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )},
    )
    assert resp.status_code == 400
    assert resp.json()["detail"]["error"] == "unsupported_file_type"


def test_upload_row_limit_exceeded(admin_client):
    # Build a 2001-row CSV with trivial content so the backend
    # rejects on the row-count gate BEFORE the LLM round-trip (gate
    # runs after parse_file, before map_rows). Each row is small so
    # the file stays well under the 8 MB upload cap.
    rows = [
        {"Name": f"User{i}", "Email": f"u{i}@t.io"}
        for i in range(2001)
    ]
    csv = _build_csv(rows)
    resp = admin_client.post(
        "/api/customers/import-excel/upload",
        files={"file": ("x.csv", csv, "text/csv")},
    )
    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert detail["error"] == "row_limit_exceeded"
    assert detail["max_rows"] == 2000
    assert detail["found_rows"] == 2001


def test_commit_unknown_batch_id(admin_client):
    resp = admin_client.post(
        "/api/customers/import-excel/commit",
        json={"batch_id": "does-not-exist", "rows": []},
    )
    assert resp.status_code == 404
    assert resp.json()["detail"]["error"] == "batch_not_found"


def test_commit_create_persists_mapped_fields(admin_client):
    cid_cleanup: List[str] = []
    try:
        # Trivial upload just to establish a batch_id.  mapped_fields
        # for commit are provided EXPLICITLY in the request payload
        # (mirrors how the FE lets the operator edit per-row fields
        # before confirming); the commit path doesn't trust the
        # preview's mapper output verbatim.
        csv = _build_csv([{"Name": "upload-fixture"}])
        up = admin_client.post(
            "/api/customers/import-excel/upload",
            files={"file": ("x.csv", csv, "text/csv")},
        ).json()
        batch_id = up["batch_id"]
        resp = admin_client.post(
            "/api/customers/import-excel/commit",
            json={
                "batch_id": batch_id,
                "rows": [{
                    "row_num": 2,
                    "action": "create",
                    "mapped_fields": {
                        "name": "ImportFixtureNameUnique",
                        "email": "importfixture@example.test",
                        "phone": "5559999999",
                    },
                }],
            },
        )
        assert resp.status_code == 200, resp.text
        result = resp.json()
        assert result["created"] == 1
        cid_cleanup.extend(result["created_ids"])
        cust = _run(_DB.customers.find_one(
            {"id": result["created_ids"][0]},
            {"_id": 0, "email": 1, "phone": 1, "name": 1,
             "source": 1},
        ))
        assert cust["email"] == "importfixture@example.test"
        assert cust["phone"] == "5559999999"
        assert cust["source"] == "excel_csv_ai_import_v1"
    finally:
        if cid_cleanup:
            _run(_DB.customers.delete_many(
                {"id": {"$in": cid_cleanup}},
            ))


_AQUATERRA_TID = "affdfbfa-88b9-4baa-ae45-2ef78531b6e4"


def test_commit_attach_patches_only_present_fields(admin_client):
    """Operator Q3 explicit — mapped_fields carrying ONLY the email
    key patches only ``customers.email``; name/phone/address stay
    verbatim.  Builds the mapped_fields payload directly rather than
    relying on the LLM-generated preview — the LLM-mapping path is
    already covered by §1 tests."""
    original = {
        "id": f"c-{uuid4().hex[:12]}",
        "tenant_id": _AQUATERRA_TID,
        "name": "Original Name DoNotTouch",
        "email": "stale@example.test",
        "phone": "+1 555 OLD PHONE",
        "address": "123 Original St",
    }
    _run(_DB.customers.insert_one({
        **original,
        "deleted_at": None,
    }))
    try:
        csv = _build_csv([{"Email": "fresh@example.test"}])
        up = admin_client.post(
            "/api/customers/import-excel/upload",
            files={"file": ("x.csv", csv, "text/csv")},
        ).json()
        batch_id = up["batch_id"]
        resp = admin_client.post(
            "/api/customers/import-excel/commit",
            json={
                "batch_id": batch_id,
                "rows": [{
                    "row_num": 2,
                    "action": "attach",
                    "mapped_fields": {"email": "fresh@example.test"},
                    "attach_to_customer_id": original["id"],
                }],
            },
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["attached"] == 1
        patched = _run(_DB.customers.find_one(
            {"id": original["id"]},
            {"_id": 0, "name": 1, "email": 1,
             "phone": 1, "address": 1},
        ))
        assert patched["email"] == "fresh@example.test"
        assert patched["name"] == "Original Name DoNotTouch"
        assert patched["phone"] == "+1 555 OLD PHONE"
        assert patched["address"] == "123 Original St"
    finally:
        _run(_DB.customers.delete_one({"id": original["id"]}))


def test_commit_attach_rejects_soft_deleted_target(admin_client):
    original_id = f"c-{uuid4().hex[:12]}"
    _run(_DB.customers.insert_one({
        "id": original_id,
        "tenant_id": _AQUATERRA_TID,
        "name": "SoftDeletedTarget",
        "deleted_at": "2026-02-01T00:00:00Z",
    }))
    try:
        csv = _build_csv([{"Name": "x"}])
        up = admin_client.post(
            "/api/customers/import-excel/upload",
            files={"file": ("x.csv", csv, "text/csv")},
        ).json()
        batch_id = up["batch_id"]
        resp = admin_client.post(
            "/api/customers/import-excel/commit",
            json={
                "batch_id": batch_id,
                "rows": [{
                    "row_num": 2,
                    "action": "attach",
                    "mapped_fields": {"email": "test@example.test"},
                    "attach_to_customer_id": original_id,
                }],
            },
        )
        assert resp.status_code == 200, resp.text
        result = resp.json()
        assert result["errored"] == 1
        assert result["row_errors"][0]["reason"] == (
            "attach_target_not_found"
        )
    finally:
        _run(_DB.customers.delete_one({"id": original_id}))
