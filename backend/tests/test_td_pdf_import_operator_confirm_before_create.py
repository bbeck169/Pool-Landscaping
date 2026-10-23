"""TD-pdf-import-operator-confirm-before-create · Feb-2026
================================================================

Pytest coverage for Part 1 (commit-time confirmation gate) and
Part 2 (match-ladder + fuzzy-mapper merged-customer exclusion).

Convention mirrors ``test_td_invoice_customer_id_repair_on_merge``:
sync ``pymongo`` for seed/assert, single ``asyncio.run()`` per
test for the async entrypoint, dedicated test-tenant namespace.
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest
from dotenv import load_dotenv
from tests._shared_mongo import (
    shared_client as _shared_client,
    shared_db as _shared_db,
)

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

_sync_db = _shared_db()


def _tnt() -> str:
    return f"_test_tenant_tdpdfimp_{uuid.uuid4().hex[:12]}"


def _mk_customer(
    tenant_id: str, name: str, *,
    is_active: bool = True,
    merged_into: Optional[str] = None,
) -> str:
    cid = f"cust_{uuid.uuid4().hex[:12]}"
    doc: Dict[str, Any] = {
        "id": cid, "tenant_id": tenant_id, "name": name,
        "is_active": is_active, "deleted_at": None,
    }
    if merged_into is not None:
        doc["merged_into"] = merged_into
        doc["merged_at"] = datetime.now(timezone.utc).isoformat()
    _sync_db.customers.insert_one(doc)
    return cid


def _teardown(tenant_id: str) -> None:
    _sync_db.customers.delete_many({"tenant_id": tenant_id})


# ═════════════════════════════════════════════════════════════
# Part 2 — Match ladder excludes merged customers
# ═════════════════════════════════════════════════════════════
def test_match_ladder_excludes_merged_customers() -> None:
    """Merged customer whose name matches the extracted name
    MUST NOT be returned by the ladder.  The non-merged
    (canonical) customer with the same name SHOULD be returned.
    """
    from config import db as motor_db  # noqa: PLC0415
    from services.imports.customer_match_ladder import (  # noqa: PLC0415
        run_match_ladder,
    )
    tenant = _tnt()
    try:
        canonical = _mk_customer(tenant, "Acme Pools LLC")
        ghost = _mk_customer(
            tenant, "Acme Pools LLC", merged_into=canonical,
        )

        async def _exercise():
            try:
                from config import client as _c
                _c._io_loop = asyncio.get_running_loop()
            except Exception:
                pass
            return await run_match_ladder(
                db=motor_db,
                tenant_id=tenant,
                extracted_name="Acme Pools LLC",
                extracted_address=None,
                extracted_phone=None,
            )

        result = asyncio.run(_exercise())
        # The ladder MUST pick the canonical (non-merged) record.
        assert result.match_status in {"active", "inactive", "muted"}
        assert result.matched_customer_id == canonical
        assert result.matched_customer_id != ghost
    finally:
        _teardown(tenant)


def test_match_ladder_falls_through_when_only_merged_match_exists() -> None:
    """If the ONLY name match is a merged (ghost) record, the
    ladder MUST return ``will_auto_create`` — the ghost is
    excluded from the pool entirely."""
    from config import db as motor_db  # noqa: PLC0415
    from services.imports.customer_match_ladder import (  # noqa: PLC0415
        run_match_ladder,
    )
    tenant = _tnt()
    try:
        winner = _mk_customer(tenant, "Unrelated Winner")
        _mk_customer(tenant, "Ghost Pools", merged_into=winner)

        async def _exercise():
            try:
                from config import client as _c
                _c._io_loop = asyncio.get_running_loop()
            except Exception:
                pass
            return await run_match_ladder(
                db=motor_db,
                tenant_id=tenant,
                extracted_name="Ghost Pools",
                extracted_address=None,
                extracted_phone=None,
            )

        result = asyncio.run(_exercise())
        assert result.match_status == "will_auto_create"
        assert result.matched_customer_id is None
    finally:
        _teardown(tenant)


# ═════════════════════════════════════════════════════════════
# Part 2 — Fuzzy mapper also excludes merged customers
# ═════════════════════════════════════════════════════════════
def test_fuzzy_match_customer_excludes_merged() -> None:
    from config import db as motor_db  # noqa: PLC0415
    from services.imports import pdf_mapper  # noqa: PLC0415
    tenant = _tnt()
    try:
        canonical = _mk_customer(tenant, "Dianne Lloyd")
        ghost = _mk_customer(
            tenant, "Dianne Lloyd", merged_into=canonical,
        )

        async def _exercise():
            try:
                from config import client as _c
                _c._io_loop = asyncio.get_running_loop()
            except Exception:
                pass
            return await pdf_mapper._fuzzy_match_customer(
                motor_db,
                tenant_id=tenant,
                extracted_name="Dianne LIoyd",  # near-miss
            )

        result = asyncio.run(_exercise())
        # Must match the canonical record (ghost is excluded).
        assert result is not None
        matched = result.get("customer") or {}
        assert matched.get("id") == canonical
        assert matched.get("id") != ghost
    finally:
        _teardown(tenant)


# ═════════════════════════════════════════════════════════════
# Part 1 — Static source contract on the commit gate
# ═════════════════════════════════════════════════════════════
def test_commit_options_carries_confirm_will_auto_create_flag() -> None:
    """``_CommitOptions`` schema MUST declare the new flag so
    the FE's payload field names resolve to a real Pydantic
    attribute (not silently dropped)."""
    from routers.imports import _CommitOptions  # noqa: PLC0415
    opts = _CommitOptions(confirm_will_auto_create=True)
    assert opts.confirm_will_auto_create is True
    opts2 = _CommitOptions()
    # Default is None — triggers the 400 gate when will_auto
    # count is non-zero.
    assert opts2.confirm_will_auto_create is None


def test_commit_endpoint_source_has_confirmation_gate() -> None:
    """Static-source guard: the commit endpoint MUST raise
    ``unmatched_customers_require_confirmation`` on the ``opts.
    confirm_will_auto_create is not True`` branch.  Guards
    against a refactor that silently drops the gate.
    """
    src = (
        Path(__file__).resolve().parents[1]
        / "routers/imports.py"
    ).read_text(encoding="utf-8")
    assert "unmatched_customers_require_confirmation" in src
    assert "confirm_will_auto_create is not True" in src
    assert "classify_pending_for_preview" in src


def test_match_ladder_cursor_filters_merged_into() -> None:
    """Static-source guard: the ladder cursor MUST include the
    merged_into exclusion filter.  Mirrors the sibling test on
    the fuzzy mapper so a refactor can't drop ONE filter
    without failing CI."""
    src = (
        Path(__file__).resolve().parents[1]
        / "services/imports/customer_match_ladder.py"
    ).read_text(encoding="utf-8")
    # Normalise whitespace for the multi-line filter comparison —
    # the literal in-source formatting uses newlines + spaces.
    norm = " ".join(src.split())
    assert '"merged_into": None' in norm
    assert '"merged_into": {"$exists": False}' in norm


def test_fuzzy_mapper_cursor_filters_merged_into() -> None:
    src = (
        Path(__file__).resolve().parents[1]
        / "services/imports/pdf_mapper.py"
    ).read_text(encoding="utf-8")
    norm = " ".join(src.split())
    assert '"merged_into": None' in norm
    assert '"merged_into": {"$exists": False}' in norm
