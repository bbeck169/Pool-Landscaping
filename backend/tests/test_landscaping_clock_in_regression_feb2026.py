"""Feb-2026 · Landscape-tech clock-in regression lock.

Reproduces the pre-existing bug: ``_require_landscaping`` reads
``user.get("department")`` from the ``db.users`` row only, but the
admin team-roster UI and the mobile tech-onboarding flow are not
guaranteed to keep ``db.users.department`` and
``db.technicians.department`` in sync.  Preview-DB evidence (47/50
seed techs have ``users.department=None``) confirms a landscaping
tech whose department was only populated on ``db.technicians``
would get a silent 403 on ``POST /api/timeclock/punch`` even though
the tech is legitimately landscape-authorized.

The fix: :func:`_resolve_tech_department` reads ``db.users`` first,
then falls back to ``db.technicians`` when the users-side value
is null/empty.  The gate uses the resolved value for its
``_LANDSCAPE_DEPTS`` membership check.

Pool-exempt behavior is DELIBERATELY out of scope here (operator's
Phase-2 feature); pool-dept techs continue to 403 on
``/timeclock/punch`` exactly like before.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException


# ─────────────────────────────────────────────────────────────────
# Fakes
# ─────────────────────────────────────────────────────────────────
class _FakeTechnicians:
    def __init__(self, row=None):
        self._row = row
        self.calls = []
    async def find_one(self, query, *_a, **_kw):
        self.calls.append(query)
        return self._row


class _StubDb:
    def __init__(self, technicians=None):
        self.technicians = _FakeTechnicians(technicians)


# ─────────────────────────────────────────────────────────────────
# Pure helper — _resolve_tech_department
# ─────────────────────────────────────────────────────────────────
def test_resolve_prefers_users_department_when_populated():
    """Users-side value wins when non-empty — super_admin edits via the
    team-roster UI take effect immediately without a cross-collection
    sync."""
    from routers import timeclock_landscaping as tl

    stub = _StubDb(technicians={"id": "T", "department": "pool_tech"})
    with patch.object(tl, "db", stub):
        resolved = asyncio.run(tl._resolve_tech_department(
            {"department": "landscaping", "technician_id": "T",
              "tenant_id": "tnt"},
        ))
    assert resolved == "landscaping"
    # The users-side win must NOT trigger a db.technicians round-trip.
    assert stub.technicians.calls == []


def test_resolve_falls_back_to_technicians_department_when_users_is_null():
    """Pre-existing regression — users.department=None + technicians.
    department='landscaping' must now resolve to 'landscaping'."""
    from routers import timeclock_landscaping as tl

    stub = _StubDb(technicians={"id": "T", "department": "landscaping"})
    with patch.object(tl, "db", stub):
        resolved = asyncio.run(tl._resolve_tech_department(
            {"department": None, "technician_id": "T",
              "tenant_id": "tnt"},
        ))
    assert resolved == "landscaping"
    assert stub.technicians.calls == [
        {"id": "T", "tenant_id": "tnt"},
    ]


def test_resolve_returns_none_when_both_sources_empty():
    from routers import timeclock_landscaping as tl

    stub = _StubDb(technicians={"id": "T", "department": None})
    with patch.object(tl, "db", stub):
        resolved = asyncio.run(tl._resolve_tech_department(
            {"department": "", "technician_id": "T",
              "tenant_id": "tnt"},
        ))
    assert resolved is None


def test_resolve_tolerates_whitespace_and_case_on_users_side():
    """Defensive — ``_dept_matches_landscape`` lowercases + strips,
    so admin-roster writes with trailing whitespace don't silently
    fail the gate."""
    from routers import timeclock_landscaping as tl

    stub = _StubDb(technicians=None)
    with patch.object(tl, "db", stub):
        resolved = asyncio.run(tl._resolve_tech_department(
            {"department": "  LANDSCAPING  ", "technician_id": "T",
              "tenant_id": "tnt"},
        ))
    assert resolved == "LANDSCAPING"  # Pre-match raw string preserved.
    assert tl._dept_matches_landscape(resolved) is True


# ─────────────────────────────────────────────────────────────────
# Gate — _require_landscaping
# ─────────────────────────────────────────────────────────────────
def test_gate_admin_passes_regardless_of_department():
    from routers import timeclock_landscaping as tl

    stub = _StubDb(technicians=None)
    with patch.object(tl, "db", stub):
        asyncio.run(tl._require_landscaping({
            "id": "u1", "role": "admin", "department": None,
            "technician_id": None, "tenant_id": "tnt",
        }))


def test_gate_super_admin_passes_regardless_of_department():
    from routers import timeclock_landscaping as tl

    stub = _StubDb(technicians=None)
    with patch.object(tl, "db", stub):
        asyncio.run(tl._require_landscaping({
            "id": "u1", "role": "super_admin", "department": None,
            "technician_id": None, "tenant_id": "tnt",
        }))


def test_gate_tech_with_users_department_landscaping_passes():
    from routers import timeclock_landscaping as tl

    stub = _StubDb(technicians=None)
    with patch.object(tl, "db", stub):
        asyncio.run(tl._require_landscaping({
            "id": "u1", "role": "technician",
            "department": "landscaping",
            "technician_id": "T", "tenant_id": "tnt",
        }))


def test_gate_tech_with_only_technicians_department_landscaping_passes():
    """THE REGRESSION FIX — users.department=None + technicians.
    department='landscaping' now authorizes the clock-in instead
    of silently 403'ing."""
    from routers import timeclock_landscaping as tl

    stub = _StubDb(technicians={"id": "T", "department": "landscaping"})
    with patch.object(tl, "db", stub):
        asyncio.run(tl._require_landscaping({
            "id": "u1", "role": "technician",
            "department": None,
            "technician_id": "T", "tenant_id": "tnt",
        }))


def test_gate_pool_tech_still_403s_pool_exempt_scope_preserved():
    """Pool-dept techs continue to 403 on /timeclock/punch — operator's
    Phase-2 'pool exempt from Time Clock' is out of scope for the
    regression fix."""
    from routers import timeclock_landscaping as tl

    stub = _StubDb(technicians={"id": "T", "department": "pool_tech"})
    with patch.object(tl, "db", stub):
        with pytest.raises(HTTPException) as exc:
            asyncio.run(tl._require_landscaping({
                "id": "u1", "role": "technician",
                "department": "pool_tech",
                "technician_id": "T", "tenant_id": "tnt",
            }))
    assert exc.value.status_code == 403
    assert exc.value.detail["code"] == "not_landscaping"


def test_gate_tech_with_both_sources_empty_403s_with_telemetry(caplog):
    """Unassigned techs still 403 — and the gate emits a structured
    log line so operators can audit which users are being
    rejected (debug-directive #1)."""
    from routers import timeclock_landscaping as tl
    import logging

    stub = _StubDb(technicians={"id": "T", "department": None})
    with patch.object(tl, "db", stub):
        with caplog.at_level(logging.INFO, logger=tl.logger.name):
            with pytest.raises(HTTPException) as exc:
                asyncio.run(tl._require_landscaping({
                    "id": "u-xxx", "role": "technician",
                    "department": None,
                    "technician_id": "T", "tenant_id": "tnt",
                }))
    assert exc.value.status_code == 403
    # Telemetry — must carry user_id + both dept sources + resolved.
    hits = [r for r in caplog.records
             if "[timeclock-landscaping] 403 not_landscaping" in r.getMessage()]
    assert hits, "gate must emit the 403 telemetry log line"
    msg = hits[0].getMessage()
    assert "user_id=u-xxx" in msg
    assert "users.department=None" in msg
    assert "technicians.department=None" in msg
    assert "resolved=None" in msg


def test_gate_tech_with_dept_both_passes():
    """Cross-trained ``both`` techs — Feb-2026 Phase 56.3.B — stay
    authorized through the regression fix."""
    from routers import timeclock_landscaping as tl

    stub = _StubDb(technicians=None)
    with patch.object(tl, "db", stub):
        asyncio.run(tl._require_landscaping({
            "id": "u1", "role": "technician", "department": "both",
            "technician_id": "T", "tenant_id": "tnt",
        }))
