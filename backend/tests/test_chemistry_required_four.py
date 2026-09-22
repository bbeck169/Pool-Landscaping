"""Phase CHEM1 · Feb-2026 — Required Four chemistry gate.

Locks in:
  * The Required Four (free_chlorine, ph, alkalinity, cyanuric_acid)
    is the ONLY set that blocks close/submit.
  * ``total_chlorine`` in the payload is silently tolerated (extra
    keys are dropped by the normaliser, matching the pattern already
    used by ``chemistry_gate`` for unknown/unaliased keys).
  * Every other chemistry reading (calcium_hardness, salt, tds,
    phosphates, water_temp, …) is accepted as ``None`` / ``""`` /
    absent without any 400/422.
  * The one-shot ``$unset`` migration is idempotent — run twice, the
    second run reports zero writes.
  * Multi-body: pool complete + a SECOND pool body missing pH → 422
    that names the offending body's pH.

Uses lightweight in-process fixtures — no HTTP round-trip so the
suite stays under a second and never fights the passlib/bcrypt
version drift that plagued the deferred baseline tests.
"""
from __future__ import annotations

import asyncio
import os
import uuid
from typing import Any, Dict, List

import pytest
from fastapi import HTTPException


_LOOP = asyncio.new_event_loop()
asyncio.set_event_loop(_LOOP)


def _run(coro):
    return _LOOP.run_until_complete(coro)


@pytest.fixture(scope="module", autouse=True)
def _bind_db():
    from motor.motor_asyncio import AsyncIOMotorClient
    from dotenv import load_dotenv
    load_dotenv("/app/backend/.env")
    fresh = AsyncIOMotorClient(os.environ["MONGO_URL"], io_loop=_LOOP)
    fresh_db = fresh[os.environ["DB_NAME"]]
    import config as _cfg
    _cfg.db = fresh_db
    yield


def _db():
    from motor.motor_asyncio import AsyncIOMotorClient
    from dotenv import load_dotenv
    load_dotenv("/app/backend/.env")
    return AsyncIOMotorClient(
        os.environ["MONGO_URL"], io_loop=_LOOP,
    )[os.environ["DB_NAME"]]


# ═════════════════════════════════════════════════════════════════════
# Required Four — gate contract.
# ═════════════════════════════════════════════════════════════════════
def test_gate_passes_with_only_required_four_and_optionals_blank():
    """Required Four filled + every optional field blank → gate passes."""
    from services.chemistry_gate import assert_core_readings_present
    assert_core_readings_present({
        "free_chlorine":  2.5,
        "ph":             7.4,
        "alkalinity":     100,
        "cyanuric_acid":  40,
        # Optionals — must be tolerated as blank.
        "calcium_hardness": None,
        "salt":             "",
        "tds":              None,
        "phosphates":       "",
        "water_temp":       None,
    })  # no raise


def test_gate_raises_with_free_chlorine_missing_names_field():
    """Free Chlorine missing → 422 with ``chlorine`` in the payload.

    Phase P17.1 · Feb-2026 — canonical rename: the 422 wire contract
    emits ``"chlorine"`` / ``"Chlorine"`` (was ``"free_cl"`` /
    ``"Free Cl"`` under P17). Legacy ``free_chlorine`` remains a
    valid source alias in the payload input."""
    from services.chemistry_gate import assert_core_readings_present
    with pytest.raises(HTTPException) as ei:
        assert_core_readings_present({
            "free_chlorine":  None,
            "ph":             7.4,
            "alkalinity":     100,
            "cyanuric_acid":  40,
        })
    d = ei.value.detail
    assert d["detail"] == "chemistry_core_readings_missing"
    assert "chlorine" in d["missing_fields"]
    assert "Chlorine" in d["missing_labels"]


def test_gate_ignores_total_chlorine_in_payload():
    """Payload carries ``total_chlorine`` alongside the Required Four →
    gate passes; the extra key is silently dropped by the normaliser
    (matching how unknown keys have always been treated)."""
    from services.chemistry_gate import (
        assert_core_readings_present, missing_core_readings,
    )
    payload = [
        {"key": "free_chlorine",  "value": 2.5},
        {"key": "total_chlorine", "value": 3.0},   # extra — ignored
        {"key": "ph",             "value": 7.4},
        {"key": "alkalinity",     "value": 100},
        {"key": "cyanuric_acid",  "value": 40},
    ]
    assert missing_core_readings(payload) == []
    assert_core_readings_present(payload)  # no raise


def test_gate_missing_labels_never_include_total_cl():
    """``missing_labels`` / ``missing_fields`` payload no longer
    surfaces ``Total Cl`` / ``total_cl`` when everything is missing."""
    from services.chemistry_gate import assert_core_readings_present
    with pytest.raises(HTTPException) as ei:
        assert_core_readings_present({})
    d = ei.value.detail
    assert "Total Cl" not in d["missing_labels"]
    assert "total_cl" not in d["missing_fields"]
    # Required Four are still surfaced in canonical order — Phase
    # P17.1 · Feb-2026 flipped ``free_cl`` / ``Free Cl`` to
    # ``chlorine`` / ``Chlorine``.
    assert d["missing_fields"] == ["chlorine", "alkalinity", "ph", "cya"]
    assert d["missing_labels"] == ["Chlorine", "Alkalinity", "pH", "CYA"]


# ═════════════════════════════════════════════════════════════════════
# Multi-body — Required Four per pool body.
# ═════════════════════════════════════════════════════════════════════
def test_multi_body_gate_raises_when_second_pool_body_missing_ph():
    """Phase CHEM2 · Feb-2026 — REVERSED from CHEM1.

    Under CHEM1 this test asserted that a report with two pool
    bodies raised 422 when the SECOND body was missing pH. Under
    CHEM2, only the PRIMARY body is gated — the second body may be
    blank without blocking close. The test is retained (and inverted)
    as the drift pin proving that behaviour change didn't regress
    silently.
    """
    from services.chemistry_gate import (
        assert_bodies_required_readings_present,
    )
    bodies = [
        {
            "id": "wb-main",
            "type": "pool",
            "label": "Main Pool",
            "readings": [
                {"key": "free_chlorine",  "value": 2.5},
                {"key": "ph",             "value": 7.4},
                {"key": "alkalinity",     "value": 100},
                {"key": "cyanuric_acid",  "value": 40},
            ],
        },
        {
            "id": "wb-kids",
            "type": "pool",
            "label": "Kids Pool",
            "readings": [
                {"key": "free_chlorine",  "value": 2.0},
                # pH deliberately missing on the SECONDARY body —
                # under CHEM2 this is OPTIONAL. Gate passes.
                {"key": "alkalinity",     "value": 90},
                {"key": "cyanuric_acid",  "value": 35},
            ],
        },
    ]
    # No raise — the primary (first) body is fully filled.
    assert_bodies_required_readings_present(bodies)


def test_multi_body_gate_raises_when_PRIMARY_body_missing_ph_regardless_of_secondary():
    """Phase CHEM2 · Feb-2026 — replacement assertion. The PRIMARY
    body being missing a Required Four reading still raises 422 —
    even if the secondary body is fully filled."""
    from services.chemistry_gate import (
        assert_bodies_required_readings_present,
    )
    bodies = [
        {
            "id": "wb-main",
            "type": "pool",
            "label": "Main Pool",
            "readings": [
                {"key": "free_chlorine",  "value": 2.5},
                # pH deliberately missing on the PRIMARY body.
                {"key": "alkalinity",     "value": 100},
                {"key": "cyanuric_acid",  "value": 40},
            ],
        },
        {
            "id": "wb-kids",
            "type": "pool",
            "label": "Kids Pool",
            "readings": [
                {"key": "free_chlorine",  "value": 2.0},
                {"key": "ph",             "value": 7.3},
                {"key": "alkalinity",     "value": 90},
                {"key": "cyanuric_acid",  "value": 35},
            ],
        },
    ]
    with pytest.raises(HTTPException) as ei:
        assert_bodies_required_readings_present(bodies)
    d = ei.value.detail
    assert d["detail"] == "chemistry_core_readings_missing"
    # The offender IS the primary Main Pool — CHEM2's bodies array
    # contains AT MOST one entry.
    assert len(d["bodies"]) == 1
    assert d["bodies"][0]["label"] == "Main Pool"
    assert d["bodies"][0]["missing_fields"] == ["ph"]
    assert "ph" in d["missing_fields"]


def test_multi_body_gate_passes_when_every_pool_body_complete():
    """Two pool bodies, both complete → no raise, extra body types
    still don't gate."""
    from services.chemistry_gate import (
        assert_bodies_required_readings_present,
    )
    bodies = [
        {"id": "wb-1", "type": "pool", "label": "Main Pool",
         "readings": [
             {"key": "free_chlorine", "value": 2.5},
             {"key": "ph",            "value": 7.4},
             {"key": "alkalinity",    "value": 100},
             {"key": "cyanuric_acid", "value": 40},
         ]},
        {"id": "wb-2", "type": "pool", "label": "Kids Pool",
         "readings": [
             {"key": "free_chlorine", "value": 2.0},
             {"key": "ph",            "value": 7.3},
             {"key": "alkalinity",    "value": 90},
             {"key": "cyanuric_acid", "value": 35},
         ]},
        # Spa carries no required readings — its blanks must not gate.
        {"id": "wb-3", "type": "spa", "label": "Spa",
         "readings": []},
    ]
    assert_bodies_required_readings_present(bodies)  # no raise


# ═════════════════════════════════════════════════════════════════════
# Migration — idempotency + non-destructive $unset.
# ═════════════════════════════════════════════════════════════════════
def test_migration_removes_total_chlorine_and_second_run_is_no_op():
    async def _go():
        from services.migrations.chemistry_remove_total_chlorine_v1 import (
            run_remove_total_chlorine_migration,
        )
        # Seed a synthetic tenant + one service report carrying
        # ``total_chlorine`` in BOTH the flat and nested surfaces.
        tid = f"chem1-tenant-{uuid.uuid4().hex[:8]}"
        sid = f"chem1-sr-{uuid.uuid4().hex[:8]}"
        await _db().service_reports.insert_one({
            "id": sid, "tenant_id": tid,
            "job_id": f"chem1-job-{uuid.uuid4().hex[:8]}",
            "chemical_readings": [
                {"key": "free_chlorine",  "value": 2.5},
                {"key": "total_chlorine", "value": 3.0},
                {"key": "ph",             "value": 7.4},
                {"key": "alkalinity",     "value": 100},
                {"key": "cyanuric_acid",  "value": 40},
            ],
            "water_bodies": [
                {"id": "wb-x", "type": "pool", "label": "Pool",
                 "readings": [
                     {"key": "free_chlorine",  "value": 2.5},
                     {"key": "total_chlorine", "value": 3.0},
                     {"key": "ph",             "value": 7.4},
                     {"key": "alkalinity",     "value": 100},
                     {"key": "cyanuric_acid",  "value": 40},
                 ]},
            ],
        })
        try:
            # First run — writes the $unset.
            r1 = await run_remove_total_chlorine_migration(
                force=True, tenant_id=tid,
            )
            t1 = r1["totals"]
            assert t1["updated"] >= 1, r1
            # Post-condition — no ``total_chlorine`` anywhere on the doc.
            after = await _db().service_reports.find_one(
                {"id": sid}, {"_id": 0},
            )
            keys_flat = {r.get("key") for r in
                         (after.get("chemical_readings") or [])}
            assert "total_chlorine" not in keys_flat, keys_flat
            for body in (after.get("water_bodies") or []):
                for r in (body.get("readings") or []):
                    assert r.get("key") != "total_chlorine"
            # Every OTHER reading is preserved verbatim.
            assert "free_chlorine" in keys_flat
            assert "ph" in keys_flat
            assert "alkalinity" in keys_flat
            assert "cyanuric_acid" in keys_flat

            # Second run — the $unset filter no longer matches → zero writes.
            r2 = await run_remove_total_chlorine_migration(
                force=True, tenant_id=tid,
            )
            assert r2["totals"]["updated"] == 0, r2
            assert r2["totals"]["scanned"] == 0, r2
        finally:
            await _db().service_reports.delete_many({"tenant_id": tid})

    _run(_go())
