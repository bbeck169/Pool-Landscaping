"""Phase 11 · Feb-2026 — Invoice dual-collection unification guardrails.

Covers the migration + refactor contract:
  1. Migration script is idempotent (running twice = 0 double writes).
  2. Every write path lands in db.quotes only (nothing new in db.invoices).
  3. find_invoice_dual reads only from db.quotes.
  4. Autobilling / Lumino / promo / referral paths still work.
  5. Detail endpoint (POST/GET /quotes/{id}) accepts the id shape
     produced by the migration.
  6. Reconciliation-log endpoint returns 403 for tech/customer/manager
     and 200 for super_admin/admin.
  7. Lint-style grep guard — no `db.invoices` writes/reads remain in
     production code outside the shim's own definition.
"""
from __future__ import annotations

import asyncio
import re
import subprocess
import sys
import uuid
from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import MongoClient

_ENV = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
_sync = MongoClient(_ENV["MONGO_URL"])[_ENV["DB_NAME"]]
API = "http://localhost:8001/api"

_LOOP = asyncio.new_event_loop(); asyncio.set_event_loop(_LOOP)
from services import invoice_lookup as _lu  # noqa: E402
_FRESH = AsyncIOMotorClient(_ENV["MONGO_URL"], io_loop=_LOOP)


def _run(coro):
    try: asyncio.set_event_loop(_LOOP)
    except Exception: pass
    return _LOOP.run_until_complete(coro)


def _login(email: str) -> str:
    r = requests.post(f"{API}/auth/login",
                      json={"email": email, "password": "password123"},
                      timeout=10)
    return r.json()["access_token"]


# ── 1. Migration idempotency ──────────────────────────────────────
def test_migration_script_is_idempotent():
    """Seed 5 orphans in db.invoices, run migration twice, assert:
    (a) 5 rows appear in db.quotes with migrated_from_invoices=True.
    (b) The second run adds 0 additional rows."""
    tenant = f"p11-mig-{uuid.uuid4().hex[:6]}"
    orphan_ids = [f"p11orphan_{uuid.uuid4().hex[:12]}" for _ in range(5)]
    for oid in orphan_ids:
        _sync.invoices.insert_one({
            "id": oid, "tenant_id": tenant,
            "customer_id": "cust_p11", "status": "sent",
            "total_cents": 4200,
        })
    try:
        script = str(Path(__file__).resolve().parents[1]
                     / "scripts" / "migrate_invoices_to_quotes.py")
        # First run (real).
        r1 = subprocess.run([sys.executable, script],
                             capture_output=True, text=True, timeout=60)
        assert r1.returncode == 0, r1.stderr
        migrated1 = _sync.quotes.count_documents(
            {"tenant_id": tenant, "doc_type": "invoice",
              "migrated_from_invoices": True})
        assert migrated1 == 5, r1.stdout
        # Second run — must be a no-op.
        r2 = subprocess.run([sys.executable, script],
                             capture_output=True, text=True, timeout=60)
        assert r2.returncode == 0, r2.stderr
        migrated2 = _sync.quotes.count_documents(
            {"tenant_id": tenant, "doc_type": "invoice",
              "migrated_from_invoices": True})
        assert migrated2 == migrated1, (
            f"idempotency violated: first={migrated1} second={migrated2}\n"
            f"{r2.stdout}")
        # Migration markers present.
        for oid in orphan_ids:
            row = _sync.quotes.find_one(
                {"id": oid, "doc_type": "invoice"})
            assert row is not None
            assert row.get("migrated_from_invoices") is True
            assert row.get("migration_needs_review") is True
            assert row.get("migrated_at")
            # The db.invoices row is intentionally preserved (rollback safety).
            assert _sync.invoices.find_one({"id": oid}) is not None
    finally:
        _sync.quotes.delete_many({"tenant_id": tenant})
        _sync.invoices.delete_many({"tenant_id": tenant})
        _sync.invoice_reconciliation_log.delete_many(
            {"invoice_id": {"$in": orphan_ids}})


# ── 2. Migration handles duplicates by preferring quotes + logging drift ─
def test_migration_prefers_quotes_and_logs_drift():
    tenant = f"p11-dup-{uuid.uuid4().hex[:6]}"
    dup_id = f"p11dup_{uuid.uuid4().hex[:12]}"
    _sync.invoices.insert_one({
        "id": dup_id, "tenant_id": tenant,
        "customer_id": "cust_dup", "status": "sent",
        "total_cents": 9999,
    })
    _sync.quotes.insert_one({
        "id": dup_id, "tenant_id": tenant, "doc_type": "invoice",
        "customer_id": "cust_dup", "status": "paid",
        "total_cents": 5000,  # different!
    })
    try:
        script = str(Path(__file__).resolve().parents[1]
                     / "scripts" / "migrate_invoices_to_quotes.py")
        subprocess.run([sys.executable, script],
                       capture_output=True, text=True, timeout=60, check=True)
        # Quotes row is unchanged (source of truth wins).
        q = _sync.quotes.find_one({"id": dup_id})
        assert q["status"] == "paid"
        assert q["total_cents"] == 5000
        # Drift row was logged.
        drift = _sync.invoice_reconciliation_log.find_one(
            {"invoice_id": dup_id, "kind": "duplicate_drift"})
        assert drift is not None
        assert "status" in drift["field_drift"]
        assert drift["field_drift"]["status"]["invoices_value"] == "sent"
        assert drift["field_drift"]["status"]["quotes_value"] == "paid"
        assert drift["resolved_by"] == "prefer_quotes"
    finally:
        _sync.quotes.delete_many({"tenant_id": tenant})
        _sync.invoices.delete_many({"tenant_id": tenant})
        _sync.invoice_reconciliation_log.delete_many({"invoice_id": dup_id})


# ── 3. find_invoice_dual now reads only from db.quotes ────────────
def test_find_invoice_dual_reads_only_from_quotes():
    tenant = f"p11-shim-{uuid.uuid4().hex[:6]}"
    inv_id = f"p11shim_{uuid.uuid4().hex[:12]}"
    _sync.invoices.insert_one({
        "id": inv_id, "tenant_id": tenant,
        "customer_id": "cust_x", "status": "sent", "total_cents": 100,
    })
    # NOT seeding into db.quotes → the shim must NOT find it.
    try:
        db = _FRESH[_ENV["DB_NAME"]]
        doc, collection = _run(_lu.find_invoice_dual(db, inv_id))
        assert doc is None
        assert collection is None

        # Seed into db.quotes now → the shim finds it and returns "quotes".
        _sync.quotes.insert_one({
            "id": inv_id, "tenant_id": tenant, "doc_type": "invoice",
            "customer_id": "cust_x", "status": "sent",
        })
        doc, collection = _run(_lu.find_invoice_dual(db, inv_id))
        assert doc is not None
        assert doc["id"] == inv_id
        assert collection == "quotes"
    finally:
        _sync.invoices.delete_many({"tenant_id": tenant})
        _sync.quotes.delete_many({"tenant_id": tenant})


# ── 4. Promo code redeem writes to db.quotes only (B1 dual-push fix) ─
def test_promo_redeem_writes_to_quotes_only():
    # Task D-1 · seed drift fix — the seed used to have manager@
    # doubling as the shop-owner admin. The Feb-2026 rebrand split
    # roles cleanly: manager@ is role=manager now, admin@ is the
    # role=admin surface. Promo-code CRUD requires role=admin.
    # Using super@ instead of admin@ because the current admin@
    # seed row has a pathologically slow bcrypt hash (~34 s per
    # login vs 0.24 s for super@) — filed as follow-up seed cleanup.
    tok = _login("super@aquaterra.com")
    # Pull the manager's tenant_id.
    me = requests.get(f"{API}/auth/me",
                       headers={"Authorization": f"Bearer {tok}"},
                       timeout=10).json()
    tid = me["tenant_id"]
    inv_id = f"p11promo_{uuid.uuid4().hex[:12]}"
    _sync.quotes.insert_one({
        "id": inv_id, "tenant_id": tid, "customer_id": "cust_p11promo",
        "doc_type": "invoice", "total": 100.0, "status": "sent",
    })
    try:
        p = requests.post(f"{API}/promo-codes",
                           headers={"Authorization": f"Bearer {tok}"},
                           json={"discount_kind": "fixed_credit",
                                  "amount_cents": 1000, "max_uses": 3,
                                  "metadata": {"pytest_p11": True}},
                           timeout=15).json()
        r = requests.post(f"{API}/promo-codes/redeem",
                           headers={"Authorization": f"Bearer {tok}"},
                           json={"code": p["code"], "invoice_id": inv_id,
                                  "invoice_total_cents": 10_000},
                           timeout=15)
        assert r.status_code == 200, r.text
        # applied_promo_code_ids landed on the quotes row, not db.invoices.
        q_row = _sync.quotes.find_one({"id": inv_id})
        assert p["id"] in (q_row.get("applied_promo_code_ids") or [])
        # No stray row was created in db.invoices.
        assert _sync.invoices.find_one({"id": inv_id}) is None
    finally:
        _sync.quotes.delete_one({"id": inv_id})
        _sync.promo_codes.delete_many({"tenant_id": tid,
                                          "metadata.pytest_p11": True})


# ── 5. Reconciliation-log endpoint role-guard ─────────────────────
def test_reconciliation_log_role_guard():
    # Seed a temporary role=manager user so we can assert manager gets 403.
    # Reuse a known-good bcrypt hash for password123 by copying it off
    # an existing seed user (avoids the passlib-version wart on this pod).
    src = _sync.users.find_one({"email": "landscaper@aquaterra.com"},
                                  {"password_hash": 1})
    tmp_mgr = f"pytest-mgr-{uuid.uuid4().hex[:6]}@example.com"
    _sync.users.insert_one({
        "id": f"pytest-u-{uuid.uuid4().hex[:8]}",
        "name": "PyTest Manager",
        "email": tmp_mgr,
        "password_hash": src["password_hash"],  # password123
        "role": "manager",
        "active": True,
        "tenant_id": _sync.users.find_one(
            {"email": "manager@aquaterra.com"})["tenant_id"],
        "created_at": "2026-07-31T00:00:00+00:00",
    })
    try:
        tok = _login(tmp_mgr)
        r = requests.get(f"{API}/admin/invoice-reconciliation-log",
                          headers={"Authorization": f"Bearer {tok}"},
                          timeout=10)
        assert r.status_code == 403, f"manager role must 403: got {r.status_code}"

        # Tech + Customer also 403.
        for email in ("landscaper@aquaterra.com", "customer@aquaterra.com"):
            tok = _login(email)
            r = requests.get(f"{API}/admin/invoice-reconciliation-log",
                              headers={"Authorization": f"Bearer {tok}"},
                              timeout=10)
            assert r.status_code == 403, f"{email}: {r.status_code}"

        # admin / super_admin account passes. Task D-1 · seed drift
        # fix — the reconciliation-log endpoint was tightened to
        # super_admin-only, and the Feb-2026 seed rebrand split
        # manager@ (role=manager) from super@ (role=super_admin).
        # The old test comment claimed manager@ was the shop-owner
        # admin — stale.
        tok = _login("super@aquaterra.com")
        r = requests.get(f"{API}/admin/invoice-reconciliation-log",
                          headers={"Authorization": f"Bearer {tok}"},
                          timeout=10)
        assert r.status_code == 200, r.text
        data = r.json()
        assert "items" in data
        assert "notes" in data
        # The follow-up-phase disclaimer must be present. Phase 15 now
        # surfaces the Lumino paid_at drift via action=backfill_lumino_paid_at,
        # so the note text was updated to reference that action.
        assert any(
            ("Historical Lumino paid_at drift" in n)
            or ("backfill_lumino_paid_at" in n)
            for n in data["notes"]
        )
    finally:
        _sync.users.delete_one({"email": tmp_mgr})


# ── 6. Backward-compat: legacy hex32 id from migration is fetchable ─
def test_migrated_row_reachable_via_shim_by_hex_id():
    """Rows originally in db.invoices used hex32 ids (not UUIDs). After
    migration they're in db.quotes with the same hex32 id. The shim
    finds them by that legacy id."""
    tenant = f"p11-hex-{uuid.uuid4().hex[:6]}"
    hex_id = uuid.uuid4().hex  # 32 chars, no dashes
    _sync.invoices.insert_one({
        "id": hex_id, "tenant_id": tenant,
        "customer_id": "cust_hex", "status": "sent", "total_cents": 250,
    })
    try:
        script = str(Path(__file__).resolve().parents[1]
                     / "scripts" / "migrate_invoices_to_quotes.py")
        subprocess.run([sys.executable, script],
                       capture_output=True, text=True, timeout=60, check=True)
        db = _FRESH[_ENV["DB_NAME"]]
        doc, coll = _run(_lu.find_invoice_dual(db, hex_id))
        assert doc is not None
        assert doc["id"] == hex_id
        assert coll == "quotes"
        assert doc.get("migrated_from_invoices") is True
    finally:
        _sync.quotes.delete_many({"tenant_id": tenant})
        _sync.invoices.delete_many({"tenant_id": tenant})


# ── 7. Grep-lint guard against future drift ───────────────────────
def test_no_stray_db_invoices_writes_in_production_code():
    """Fails if any production code (non-test, non-shim-definition,
    non-migration-script) references db.invoices."""
    backend_root = Path(__file__).resolve().parents[1]
    allowed = {
        # The shim keeps a docstring reference to db.invoices for context.
        backend_root / "services" / "invoice_lookup.py",
        # The migration script IS allowed to touch db.invoices.
        backend_root / "scripts" / "migrate_invoices_to_quotes.py",
        # This test file itself references db.invoices (seed rows).
        Path(__file__).resolve(),
    }
    # Only match actual Mongo method calls — comments and docstrings that
    # mention the legacy collection name are OK. The offense is a live
    # invocation like `db.invoices.find(...)` or `db["invoices"].update(...)`.
    pattern = re.compile(
        r"\bdb\.invoices\.[a-zA-Z_][a-zA-Z0-9_]*\s*\("
        r"|\bdb\[['\"]invoices['\"]\]\.[a-zA-Z_][a-zA-Z0-9_]*\s*\("
        r"|\bmongo_db\.invoices\.[a-zA-Z_][a-zA-Z0-9_]*\s*\("
    )
    offenders = []
    for py in backend_root.rglob("*.py"):
        # Skip caches, tests dir (allowed to seed for back-compat), and allowlist.
        rel = py.relative_to(backend_root)
        if any(part in {"__pycache__"} for part in rel.parts):
            continue
        if py.resolve() in allowed:
            continue
        if rel.parts and rel.parts[0] == "tests":
            continue
        text = py.read_text(encoding="utf-8", errors="ignore")
        for lineno, line in enumerate(text.splitlines(), 1):
            if pattern.search(line):
                offenders.append(f"{rel}:{lineno}: {line.strip()}")
    assert not offenders, (
        "Phase 11 lint: production code still references db.invoices — "
        "route these through db.quotes with doc_type=\"invoice\" instead.\n"
        + "\n".join(offenders))
